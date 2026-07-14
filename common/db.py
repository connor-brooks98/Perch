"""Thin SQLite helper shared by the puller and classifier services.

Both containers mount the same /data volume and open the same DB file.
WAL mode + a busy timeout make concurrent access safe for this low
write-rate workload (a handful of clips per minute at most).
"""
from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path

SCHEMA_PATH = Path(__file__).with_name("schema.sql")


def now_iso() -> str:
    """UTC timestamp in ISO8601 with a trailing Z."""
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _open(db_path: str | Path, *, timeout_seconds: float) -> sqlite3.Connection:
    db_path = Path(db_path)
    timeout = float(timeout_seconds)
    if timeout < 0:
        raise ValueError("timeout must not be negative")
    busy_timeout_ms = int(timeout * 1000)
    conn = sqlite3.connect(str(db_path), timeout=timeout)
    try:
        conn.row_factory = sqlite3.Row
        conn.execute(f"PRAGMA busy_timeout = {busy_timeout_ms};")
        conn.execute("PRAGMA synchronous = NORMAL;")
        conn.execute("PRAGMA foreign_keys = ON;")
        return conn
    except BaseException:
        conn.close()
        raise


def initialize(db_path: str | Path, *, timeout_seconds: float = 5) -> None:
    """Create/migrate the shared database once during service startup."""
    path = Path(db_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    conn: sqlite3.Connection | None = None
    try:
        conn = _open(path, timeout_seconds=timeout_seconds)
        conn.execute("PRAGMA journal_mode = WAL;")
        conn.execute("PRAGMA synchronous = NORMAL;")
        conn.executescript(SCHEMA_PATH.read_text())
        _migrate_clips(conn)
        _migrate_detections(conn)
    finally:
        if conn is not None:
            conn.close()


def connect(db_path: str | Path, *, timeout_seconds: float = 5) -> sqlite3.Connection:
    """Open an initialized database using connection-local runtime settings."""
    return _open(db_path, timeout_seconds=timeout_seconds)


def _migrate_clips(conn: sqlite3.Connection) -> None:
    """Add recovery columns to databases created before durable processing."""
    columns = {row["name"] for row in conn.execute("PRAGMA table_info(clips)")}
    additions = {
        "attempt_count": "INTEGER NOT NULL DEFAULT 0",
        "next_attempt_at": "TEXT",
        "processing_started_at": "TEXT",
    }
    with conn:
        for name, definition in additions.items():
            if name not in columns:
                conn.execute(f"ALTER TABLE clips ADD COLUMN {name} {definition}")
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_clips_ready "
            "ON clips(status, next_attempt_at, captured_at)"
        )


def _migrate_detections(conn: sqlite3.Connection) -> None:
    columns = {row["name"] for row in conn.execute("PRAGMA table_info(detections)")}
    with conn:
        if "display_image" not in columns:
            conn.execute("ALTER TABLE detections ADD COLUMN display_image TEXT")
        conn.execute(
            "UPDATE detections SET display_image = thumbnail "
            "WHERE display_image IS NULL OR display_image = ''"
        )


# ---- state (key/value cursors) ------------------------------------------

def get_state(conn: sqlite3.Connection, key: str, default: str | None = None) -> str | None:
    row = conn.execute("SELECT value FROM state WHERE key = ?", (key,)).fetchone()
    return row["value"] if row else default


def set_state(conn: sqlite3.Connection, key: str, value: str) -> None:
    conn.execute(
        "INSERT INTO state(key, value) VALUES(?, ?) "
        "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
        (key, value),
    )
    conn.commit()


# ---- clips ---------------------------------------------------------------

def clip_exists(conn: sqlite3.Connection, filename: str) -> bool:
    row = conn.execute("SELECT 1 FROM clips WHERE filename = ?", (filename,)).fetchone()
    return row is not None


def clip_status(conn: sqlite3.Connection, filename: str) -> str | None:
    row = conn.execute("SELECT status FROM clips WHERE filename = ?", (filename,)).fetchone()
    return row["status"] if row else None


def add_clip(conn: sqlite3.Connection, filename: str, camera: str, captured_at: str) -> int:
    cur = conn.execute(
        "INSERT OR IGNORE INTO clips(filename, camera, captured_at, pulled_at) "
        "VALUES(?, ?, ?, ?)",
        (filename, camera, captured_at, now_iso()),
    )
    conn.commit()
    return cur.lastrowid


def pending_clips(conn: sqlite3.Connection, limit: int = 25):
    return conn.execute(
        "SELECT * FROM clips WHERE status = 'pending' ORDER BY captured_at ASC LIMIT ?",
        (limit,),
    ).fetchall()


def claim_pending_clips(conn: sqlite3.Connection, limit: int = 25):
    """Atomically claim due work for the single supported classifier."""
    now = now_iso()
    with conn:
        rows = conn.execute(
            "WITH due AS ("
            "  SELECT id FROM clips WHERE status = 'pending' "
            "  AND (next_attempt_at IS NULL OR next_attempt_at <= ?) "
            "  ORDER BY captured_at ASC LIMIT ?"
            ") "
            "UPDATE clips SET status = 'processing', "
            "attempt_count = attempt_count + 1, next_attempt_at = NULL, "
            "processing_started_at = ?, note = NULL "
            "WHERE status = 'pending' AND id IN (SELECT id FROM due) "
            "RETURNING *",
            (now, limit, now),
        ).fetchall()
    return sorted(rows, key=lambda row: row["captured_at"])


def recover_processing_clips(conn: sqlite3.Connection) -> int:
    """Return work interrupted by a classifier stop to the ready queue."""
    with conn:
        cur = conn.execute(
            "UPDATE clips SET status = 'pending', next_attempt_at = NULL, "
            "processing_started_at = NULL, note = 'interrupted; retrying' "
            "WHERE status = 'processing'"
        )
    return cur.rowcount


def fail_clip(
    conn: sqlite3.Connection,
    clip_id: int,
    attempt_count: int,
    error: str,
    *,
    max_attempts: int,
    retry_delay_seconds: int,
) -> bool:
    """Reschedule a failed clip, or mark it terminal after its last attempt."""
    note = str(error)[:1000]
    terminal = attempt_count >= max_attempts
    if terminal:
        status = "error"
        next_attempt_at = None
    else:
        status = "pending"
        delay = retry_delay_seconds * (2 ** max(0, attempt_count - 1))
        next_attempt_at = (
            datetime.now(timezone.utc) + timedelta(seconds=delay)
        ).strftime("%Y-%m-%dT%H:%M:%SZ")
    with conn:
        conn.execute(
            "UPDATE clips SET status = ?, note = ?, next_attempt_at = ?, "
            "processing_started_at = NULL WHERE id = ?",
            (status, note, next_attempt_at, clip_id),
        )
    return terminal


def mark_clip(conn: sqlite3.Connection, clip_id: int, status: str, note: str | None = None) -> None:
    conn.execute(
        "UPDATE clips SET status = ?, note = ?, next_attempt_at = NULL, "
        "processing_started_at = NULL WHERE id = ?",
        (status, note, clip_id),
    )
    conn.commit()


# ---- detections ----------------------------------------------------------

def add_detection(
    conn: sqlite3.Connection,
    clip_id: int,
    common_name: str,
    scientific: str | None,
    confidence: float,
    captured_at: str,
    thumbnail: str,
    display_image: str,
) -> int:
    cur = conn.execute(
        "INSERT INTO detections"
        "(clip_id, common_name, scientific, confidence, captured_at, thumbnail, display_image, created_at) "
        "VALUES(?, ?, ?, ?, ?, ?, ?, ?) "
        "ON CONFLICT(clip_id) DO UPDATE SET "
        "  common_name = excluded.common_name, scientific = excluded.scientific, "
        "  confidence  = excluded.confidence,  captured_at = excluded.captured_at, "
        "  thumbnail   = excluded.thumbnail, display_image = excluded.display_image, "
        "  created_at  = excluded.created_at",
        (
            clip_id,
            common_name,
            scientific,
            confidence,
            captured_at,
            thumbnail,
            display_image,
            now_iso(),
        ),
    )
    conn.commit()
    return cur.lastrowid


def finish_clip_with_detection(
    conn: sqlite3.Connection,
    clip_id: int,
    common_name: str,
    scientific: str | None,
    confidence: float,
    captured_at: str,
    thumbnail: str,
    display_image: str,
) -> None:
    """Atomically upsert a detection and mark its source clip done."""
    with conn:
        conn.execute(
            "INSERT INTO detections"
            "(clip_id, common_name, scientific, confidence, captured_at, thumbnail, display_image, created_at) "
            "VALUES(?, ?, ?, ?, ?, ?, ?, ?) "
            "ON CONFLICT(clip_id) DO UPDATE SET "
            "  common_name = excluded.common_name, scientific = excluded.scientific, "
            "  confidence  = excluded.confidence,  captured_at = excluded.captured_at, "
            "  thumbnail   = excluded.thumbnail, display_image = excluded.display_image, "
            "  created_at  = excluded.created_at",
            (
                clip_id,
                common_name,
                scientific,
                confidence,
                captured_at,
                thumbnail,
                display_image,
                now_iso(),
            ),
        )
        conn.execute(
            "UPDATE clips SET status = ?, note = ?, next_attempt_at = NULL, "
            "processing_started_at = NULL WHERE id = ?",
            ("done", common_name, clip_id),
        )


def detection_count(conn: sqlite3.Connection) -> int:
    """Total detections ever recorded (not limited by the dashboard window)."""
    return conn.execute("SELECT COUNT(*) AS n FROM detections").fetchone()["n"]


def recent_detections(conn: sqlite3.Connection, limit: int = 200):
    return conn.execute(
        "SELECT * FROM detections ORDER BY captured_at DESC LIMIT ?",
        (limit,),
    ).fetchall()


def species_tally(conn: sqlite3.Connection):
    return conn.execute(
        "SELECT common_name, scientific, COUNT(*) AS n, MAX(captured_at) AS last_seen "
        "FROM detections GROUP BY common_name ORDER BY n DESC"
    ).fetchall()
