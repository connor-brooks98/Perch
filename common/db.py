"""Thin SQLite helper shared by the puller and classifier services.

Both containers mount the same /data volume and open the same DB file.
WAL mode + a busy timeout make concurrent access safe for this low
write-rate workload (a handful of clips per minute at most).
"""
from __future__ import annotations

import sqlite3
from datetime import datetime, timezone
from pathlib import Path

SCHEMA_PATH = Path(__file__).with_name("schema.sql")


def now_iso() -> str:
    """UTC timestamp in ISO8601 with a trailing Z."""
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def connect(db_path: str | Path) -> sqlite3.Connection:
    """Open (and initialise, if needed) the shared database."""
    db_path = Path(db_path)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db_path), timeout=10)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON;")
    conn.executescript(SCHEMA_PATH.read_text())
    return conn


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


def mark_clip(conn: sqlite3.Connection, clip_id: int, status: str, note: str | None = None) -> None:
    conn.execute(
        "UPDATE clips SET status = ?, note = ? WHERE id = ?",
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
) -> int:
    cur = conn.execute(
        "INSERT INTO detections"
        "(clip_id, common_name, scientific, confidence, captured_at, thumbnail, created_at) "
        "VALUES(?, ?, ?, ?, ?, ?, ?)",
        (clip_id, common_name, scientific, confidence, captured_at, thumbnail, now_iso()),
    )
    conn.commit()
    return cur.lastrowid


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
