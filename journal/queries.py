"""SQLite-backed domain queries for the shared family journal."""
from __future__ import annotations

import base64
import json
import sqlite3
from collections import Counter
from datetime import date, datetime, time, timezone
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from common import db
from journal.labels import LabelCatalog

MAX_PAGE_SIZE = 100

EFFECTIVE_SQL = """
SELECT d.*, COALESCE(NULLIF(a.corrected_common_name,''), d.common_name) AS effective_common,
       COALESCE(NULLIF(a.corrected_scientific,''), d.scientific) AS effective_scientific,
       COALESCE(a.favorite, 0) AS favorite, COALESCE(a.excluded, 0) AS excluded,
       a.corrected_common_name IS NOT NULL AS corrected
FROM detections d LEFT JOIN detection_annotations a ON a.detection_id = d.id
"""


class InvalidCorrection(ValueError):
    pass


class InvalidCursor(ValueError):
    pass


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def species_key(common: str, scientific: str | None) -> str:
    value = " ".join((scientific or common).strip().casefold().split())
    return ("sci:" if scientific else "common:") + value


def _zone(tz_name: str) -> ZoneInfo:
    try:
        return ZoneInfo(tz_name)
    except (ZoneInfoNotFoundError, ValueError) as exc:
        raise ValueError("unknown time zone") from exc


def _iso_utc(value: datetime) -> str:
    return value.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _day_bounds(local_date: str | date, tz_name: str) -> tuple[str, str]:
    try:
        selected = (
            local_date
            if isinstance(local_date, date)
            else date.fromisoformat(local_date)
        )
    except (TypeError, ValueError) as exc:
        raise ValueError("local date must be YYYY-MM-DD") from exc
    zone = _zone(tz_name)
    start = datetime.combine(selected, time.min, zone)
    end = datetime.combine(selected.fromordinal(selected.toordinal() + 1), time.min, zone)
    return _iso_utc(start), _iso_utc(end)


def _bounded_limit(limit: int) -> int:
    try:
        value = int(limit)
    except (TypeError, ValueError) as exc:
        raise ValueError("limit must be an integer") from exc
    if value < 1:
        raise ValueError("limit must be positive")
    return min(value, MAX_PAGE_SIZE)


def _encode_cursor(row: sqlite3.Row | dict[str, Any]) -> str:
    payload = json.dumps(
        {"captured_at": row["captured_at"], "id": row["id"]},
        separators=(",", ":"),
    ).encode("utf-8")
    return base64.urlsafe_b64encode(payload).decode("ascii").rstrip("=")


def _decode_cursor(cursor: str) -> tuple[str, int]:
    try:
        padded = cursor + "=" * (-len(cursor) % 4)
        decoded = base64.b64decode(padded, altchars=b"-_", validate=True)
        value = json.loads(decoded.decode("utf-8"))
        captured_at = value["captured_at"]
        row_id = value["id"]
        if (
            not isinstance(value, dict)
            or set(value) != {"captured_at", "id"}
            or not isinstance(captured_at, str)
            or not isinstance(row_id, int)
            or isinstance(row_id, bool)
            or row_id < 1
        ):
            raise ValueError
        datetime.fromisoformat(captured_at.replace("Z", "+00:00"))
        return captured_at, row_id
    except Exception as exc:
        raise InvalidCursor("malformed cursor") from exc


def _species(common: str, scientific: str | None) -> dict[str, str | None]:
    return {"common_name": common, "scientific": scientific}


def _serialize_detection(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "id": row["id"],
        "captured_at": row["captured_at"],
        "thumbnail": row["thumbnail"],
        "display_image": row["display_image"],
        "confidence": row["confidence"],
        "favorite": bool(row["favorite"]),
        "excluded": bool(row["excluded"]),
        "corrected": bool(row["corrected"]),
        "original_species": _species(row["common_name"], row["scientific"]),
        "effective_species": _species(
            row["effective_common"], row["effective_scientific"]
        ),
        "species_key": species_key(
            row["effective_common"], row["effective_scientific"]
        ),
    }


def _effective_rows(conn: sqlite3.Connection, *, include_excluded: bool = False):
    where = "" if include_excluded else " WHERE e.excluded = 0"
    return conn.execute(
        f"SELECT * FROM ({EFFECTIVE_SQL}) e{where} "
        "ORDER BY e.captured_at DESC, e.id DESC"
    ).fetchall()


def detection(conn: sqlite3.Connection, id: int) -> dict[str, Any] | None:
    row = conn.execute(
        f"SELECT * FROM ({EFFECTIVE_SQL}) e WHERE e.id = ?", (id,)
    ).fetchone()
    return _serialize_detection(row) if row else None


def patch_detection(
    conn: sqlite3.Connection,
    id: int,
    patch: dict[str, Any],
    catalog: LabelCatalog,
) -> dict[str, Any] | None:
    allowed = {"favorite", "correction", "excluded"}
    if not isinstance(patch, dict) or not patch or set(patch) - allowed:
        raise ValueError("unsupported or empty patch")
    if "favorite" in patch and not isinstance(patch["favorite"], bool):
        raise ValueError("favorite must be boolean")
    if "excluded" in patch and not isinstance(patch["excluded"], bool):
        raise ValueError("excluded must be boolean")
    correction = patch.get("correction", ...)
    if correction is not ... and correction is not None and not isinstance(correction, str):
        raise InvalidCorrection("unknown correction")
    taxon = None if correction in (..., None) else catalog.resolve(correction)
    if correction not in (..., None) and taxon is None:
        raise InvalidCorrection("unknown correction")

    with conn:
        current = conn.execute(
            "SELECT d.id, a.favorite, a.corrected_common_name, "
            "a.corrected_scientific, a.excluded "
            "FROM detections d LEFT JOIN detection_annotations a "
            "ON a.detection_id = d.id WHERE d.id = ?",
            (id,),
        ).fetchone()
        if current is None:
            return None
        favorite = int(patch.get("favorite", bool(current["favorite"] or 0)))
        excluded = int(patch.get("excluded", bool(current["excluded"] or 0)))
        if correction is ...:
            corrected_common = current["corrected_common_name"]
            corrected_scientific = current["corrected_scientific"]
        elif correction is None:
            corrected_common = corrected_scientific = None
        else:
            corrected_common = taxon.common_name
            corrected_scientific = taxon.scientific
        conn.execute(
            "INSERT INTO detection_annotations"
            "(detection_id, favorite, corrected_common_name, "
            "corrected_scientific, excluded, updated_at) "
            "VALUES(?, ?, ?, ?, ?, ?) "
            "ON CONFLICT(detection_id) DO UPDATE SET "
            "favorite = excluded.favorite, "
            "corrected_common_name = excluded.corrected_common_name, "
            "corrected_scientific = excluded.corrected_scientific, "
            "excluded = excluded.excluded, updated_at = excluded.updated_at",
            (
                id,
                favorite,
                corrected_common,
                corrected_scientific,
                excluded,
                db.now_iso(),
            ),
        )
    return detection(conn, id)


def detections(
    conn: sqlite3.Connection,
    *,
    cursor: str | None,
    limit: int,
    species_key: str | None,
    favorite: bool | None,
    local_date: str | None,
    tz_name: str,
) -> dict[str, Any]:
    bounded = _bounded_limit(limit)
    clauses = ["e.excluded = 0"]
    parameters: list[Any] = []
    if cursor:
        captured_at, row_id = _decode_cursor(cursor)
        clauses.append("(e.captured_at < ? OR (e.captured_at = ? AND e.id < ?))")
        parameters.extend((captured_at, captured_at, row_id))
    if favorite is not None:
        if not isinstance(favorite, bool):
            raise ValueError("favorite must be boolean")
        clauses.append("e.favorite = ?")
        parameters.append(int(favorite))
    if local_date is not None:
        start, end = _day_bounds(local_date, tz_name)
        clauses.extend(("e.captured_at >= ?", "e.captured_at < ?"))
        parameters.extend((start, end))
    rows = conn.execute(
        f"SELECT * FROM ({EFFECTIVE_SQL}) e WHERE {' AND '.join(clauses)} "
        "ORDER BY e.captured_at DESC, e.id DESC",
        parameters,
    ).fetchall()
    if species_key is not None:
        rows = [
            row
            for row in rows
            if globals()["species_key"](
                row["effective_common"], row["effective_scientific"]
            )
            == species_key
        ]
    page = rows[: bounded + 1]
    has_more = len(page) > bounded
    page = page[:bounded]
    return {
        "detections": [_serialize_detection(row) for row in page],
        "next_cursor": _encode_cursor(page[-1]) if has_more else None,
    }


def today(
    conn: sqlite3.Connection, tz_name: str, recent_limit: int = 12
) -> dict[str, Any]:
    bounded = _bounded_limit(recent_limit)
    zone = _zone(tz_name)
    local_now = _utc_now().astimezone(zone)
    start, end = _day_bounds(local_now.date(), tz_name)
    all_rows = _effective_rows(conn)
    today_rows = [row for row in all_rows if start <= row["captured_at"] < end]
    hours = [0] * 24
    for row in today_rows:
        captured = datetime.fromisoformat(row["captured_at"].replace("Z", "+00:00"))
        hours[captured.astimezone(zone).hour] += 1
    busiest = max(range(24), key=lambda hour: hours[hour]) if today_rows else None
    recent = all_rows[:bounded]
    latest = _serialize_detection(all_rows[0]) if all_rows else None
    day_part = (
        "morning"
        if local_now.hour < 12
        else "afternoon"
        if local_now.hour < 18
        else "evening"
    )
    return {
        "greeting": f"Good {day_part} from the feeder.",
        "latest": latest,
        "visits_today": len(today_rows),
        "species_today": len(
            {
                species_key(row["effective_common"], row["effective_scientific"])
                for row in today_rows
            }
        ),
        "busiest_hour": busiest,
        "hourly_activity": hours,
        "recent": [_serialize_detection(row) for row in recent],
        "has_more": len(all_rows) > bounded,
    }


def _album_rows(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    grouped: dict[str, list[sqlite3.Row]] = {}
    for row in _effective_rows(conn):
        key = species_key(row["effective_common"], row["effective_scientific"])
        grouped.setdefault(key, []).append(row)
    opened = {
        row["species_key"]
        for row in conn.execute("SELECT species_key FROM species_journal_state")
    }
    albums = []
    for key, rows in grouped.items():
        newest = rows[0]
        oldest = rows[-1]
        favorite_cover = next((row for row in rows if row["favorite"]), newest)
        albums.append(
            {
                "species_key": key,
                "common_name": newest["effective_common"],
                "scientific": newest["effective_scientific"],
                "visits": len(rows),
                "first_seen": oldest["captured_at"],
                "last_seen": newest["captured_at"],
                "thumbnail": favorite_cover["thumbnail"],
                "is_new": key not in opened,
            }
        )
    return albums


def species(conn: sqlite3.Connection, *, query: str, sort: str) -> dict[str, Any]:
    albums = _album_rows(conn)
    needle = " ".join(query.casefold().split())
    if needle:
        albums = [
            album
            for album in albums
            if needle in album["common_name"].casefold()
            or needle in (album["scientific"] or "").casefold()
        ]
    sorts = {
        "newest": lambda album: (album["first_seen"], album["species_key"]),
        "visits": lambda album: (album["visits"], album["last_seen"], album["species_key"]),
        "recent": lambda album: (album["last_seen"], album["species_key"]),
    }
    if sort == "alphabetical":
        albums.sort(key=lambda album: (album["common_name"].casefold(), album["species_key"]))
    elif sort in sorts:
        albums.sort(key=sorts[sort], reverse=True)
    else:
        raise ValueError("unsupported species sort")
    return {"species": albums}


def species_detail(
    conn: sqlite3.Connection,
    species_key: str,
    *,
    cursor: str | None,
    limit: int,
    tz_name: str = "America/New_York",
) -> dict[str, Any] | None:
    bounded = _bounded_limit(limit)
    zone = _zone(tz_name)
    rows = [
        row
        for row in _effective_rows(conn)
        if globals()["species_key"](
            row["effective_common"], row["effective_scientific"]
        )
        == species_key
    ]
    if not rows:
        return None
    all_species_rows = rows
    if cursor:
        captured_at, row_id = _decode_cursor(cursor)
        rows = [
            row
            for row in rows
            if row["captured_at"] < captured_at
            or (row["captured_at"] == captured_at and row["id"] < row_id)
        ]
    page = rows[: bounded + 1]
    has_more = len(page) > bounded
    page = page[:bounded]
    favorite_cover = next(
        (row for row in all_species_rows if row["favorite"]), all_species_rows[0]
    )
    local_hours = Counter()
    for row in all_species_rows:
        captured = datetime.fromisoformat(row["captured_at"].replace("Z", "+00:00"))
        local_hours[captured.astimezone(zone).hour] += 1
    newest, oldest = all_species_rows[0], all_species_rows[-1]
    return {
        "species_key": species_key,
        "common_name": newest["effective_common"],
        "scientific": newest["effective_scientific"],
        "visits": len(all_species_rows),
        "first_seen": oldest["captured_at"],
        "last_seen": newest["captured_at"],
        "busiest_hours": [
            hour
            for hour, count in sorted(local_hours.items())
            if count == max(local_hours.values())
        ],
        "cover": _serialize_detection(favorite_cover),
        "gallery": [_serialize_detection(row) for row in page],
        "next_cursor": _encode_cursor(page[-1]) if has_more else None,
    }


def mark_species_opened(conn: sqlite3.Connection, species_key: str) -> bool:
    exists = any(
        globals()["species_key"](row["effective_common"], row["effective_scientific"])
        == species_key
        for row in _effective_rows(conn)
    )
    if not exists:
        return False
    with conn:
        conn.execute(
            "INSERT INTO species_journal_state(species_key, opened_at) VALUES(?, ?) "
            "ON CONFLICT(species_key) DO UPDATE SET opened_at = excluded.opened_at",
            (species_key, db.now_iso()),
        )
    return True
