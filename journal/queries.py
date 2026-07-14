"""SQLite-backed domain queries for the shared family journal."""
from __future__ import annotations

import base64
import json
import sqlite3
from datetime import date, datetime, time, timezone
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from common import db
from journal.labels import LabelCatalog

MAX_PAGE_SIZE = 100

EFFECTIVE_SQL = """
SELECT d.*, COALESCE(NULLIF(a.corrected_common_name,''), d.common_name) AS effective_common,
       CASE WHEN a.corrected_common_name IS NOT NULL
            THEN NULLIF(a.corrected_scientific,'') ELSE d.scientific
       END AS effective_scientific,
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


def _register_sql_functions(conn: sqlite3.Connection) -> None:
    conn.create_function(
        "journal_species_key", 2, species_key, deterministic=True
    )
    conn.create_function(
        "journal_local_hour", 2, _local_hour, deterministic=True
    )
    conn.create_function(
        "journal_casefold",
        1,
        lambda value: (value or "").casefold(),
        deterministic=True,
    )


def _local_hour(captured_at: str, tz_name: str) -> int:
    captured = datetime.fromisoformat(captured_at.replace("Z", "+00:00"))
    return captured.astimezone(_zone(tz_name)).hour


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


def _effective_rows(
    conn: sqlite3.Connection,
    *,
    include_excluded: bool = False,
):
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
    if species_key is not None:
        _register_sql_functions(conn)
        clauses.append(
            "journal_species_key(e.effective_common, e.effective_scientific) = ?"
        )
        parameters.append(species_key)
    parameters.append(bounded + 1)
    rows = conn.execute(
        f"SELECT * FROM ({EFFECTIVE_SQL}) e WHERE {' AND '.join(clauses)} "
        "ORDER BY e.captured_at DESC, e.id DESC LIMIT ?",
        parameters,
    ).fetchall()
    has_more = len(rows) > bounded
    page = rows[:bounded]
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
    if latest:
        latest["is_first_visit"] = sum(
            species_key(row["effective_common"], row["effective_scientific"])
            == latest["species_key"]
            for row in all_rows
        ) == 1
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


def species(
    conn: sqlite3.Connection, *, query: str, sort: str, limit: int = MAX_PAGE_SIZE
) -> dict[str, Any]:
    bounded = _bounded_limit(limit)
    needle = " ".join(query.casefold().split())
    order_by = {
        "newest": "a.first_seen DESC, a.species_key DESC",
        "visits": "a.visits DESC, a.last_seen DESC, a.species_key DESC",
        "recent": "a.last_seen DESC, a.species_key DESC",
        "alphabetical": (
            "journal_casefold(a.common_name) ASC, a.species_key ASC"
        ),
    }
    if sort not in order_by:
        raise ValueError("unsupported species sort")
    _register_sql_functions(conn)
    rows = conn.execute(
        f"WITH keyed AS ("
        f"SELECT e.*, "
        f"journal_species_key(e.effective_common, e.effective_scientific) "
        f"AS species_key FROM ({EFFECTIVE_SQL}) e WHERE e.excluded = 0"
        f"), ranked AS ("
        f"SELECT k.*, "
        f"ROW_NUMBER() OVER (PARTITION BY k.species_key "
        f"ORDER BY k.captured_at DESC, k.id DESC) AS newest_rank, "
        f"ROW_NUMBER() OVER (PARTITION BY k.species_key "
        f"ORDER BY k.favorite DESC, k.captured_at DESC, k.id DESC) "
        f"AS cover_rank FROM keyed k"
        f"), albums AS ("
        f"SELECT r.species_key, "
        f"MAX(CASE WHEN r.newest_rank = 1 THEN r.effective_common END) "
        f"AS common_name, "
        f"MAX(CASE WHEN r.newest_rank = 1 THEN r.effective_scientific END) "
        f"AS scientific, COUNT(*) AS visits, "
        f"MIN(r.captured_at) AS first_seen, MAX(r.captured_at) AS last_seen, "
        f"MAX(CASE WHEN r.cover_rank = 1 THEN r.thumbnail END) AS thumbnail "
        f"FROM ranked r GROUP BY r.species_key"
        f") SELECT a.*, s.species_key IS NULL AS is_new "
        f"FROM albums a LEFT JOIN species_journal_state s "
        f"ON s.species_key = a.species_key "
        f"WHERE ? = '' OR instr(journal_casefold(a.common_name), ?) > 0 "
        f"OR instr(journal_casefold(a.scientific), ?) > 0 "
        f"ORDER BY {order_by[sort]} LIMIT ?",
        (needle, needle, needle, bounded),
    ).fetchall()
    return {
        "species": [
            {
                "species_key": row["species_key"],
                "common_name": row["common_name"],
                "scientific": row["scientific"],
                "visits": row["visits"],
                "first_seen": row["first_seen"],
                "last_seen": row["last_seen"],
                "thumbnail": row["thumbnail"],
                "is_new": bool(row["is_new"]),
            }
            for row in rows
        ]
    }


def species_detail(
    conn: sqlite3.Connection,
    species_key: str,
    *,
    cursor: str | None,
    limit: int,
    tz_name: str = "America/New_York",
) -> dict[str, Any] | None:
    bounded = _bounded_limit(limit)
    _zone(tz_name)
    _register_sql_functions(conn)
    species_clause = (
        "e.excluded = 0 AND "
        "journal_species_key(e.effective_common, e.effective_scientific) = ?"
    )
    summary = conn.execute(
        f"SELECT COUNT(*) AS visits, MIN(e.captured_at) AS first_seen, "
        f"MAX(e.captured_at) AS last_seen FROM ({EFFECTIVE_SQL}) e "
        f"WHERE {species_clause}",
        (species_key,),
    ).fetchone()
    if summary["visits"] == 0:
        return None

    newest = conn.execute(
        f"SELECT * FROM ({EFFECTIVE_SQL}) e WHERE {species_clause} "
        "ORDER BY e.captured_at DESC, e.id DESC LIMIT 1",
        (species_key,),
    ).fetchone()
    favorite_cover = conn.execute(
        f"SELECT * FROM ({EFFECTIVE_SQL}) e WHERE {species_clause} "
        "ORDER BY e.favorite DESC, e.captured_at DESC, e.id DESC LIMIT 1",
        (species_key,),
    ).fetchone()
    hour_rows = conn.execute(
        f"SELECT journal_local_hour(e.captured_at, ?) AS hour, COUNT(*) AS visits "
        f"FROM ({EFFECTIVE_SQL}) e WHERE {species_clause} "
        "GROUP BY hour ORDER BY hour",
        (tz_name, species_key),
    ).fetchall()

    page_clauses = [species_clause]
    page_parameters: list[Any] = [species_key]
    if cursor:
        captured_at, row_id = _decode_cursor(cursor)
        page_clauses.append(
            "(e.captured_at < ? OR (e.captured_at = ? AND e.id < ?))"
        )
        page_parameters.extend((captured_at, captured_at, row_id))
    page_parameters.append(bounded + 1)
    rows = conn.execute(
        f"SELECT * FROM ({EFFECTIVE_SQL}) e "
        f"WHERE {' AND '.join(page_clauses)} "
        "ORDER BY e.captured_at DESC, e.id DESC LIMIT ?",
        page_parameters,
    ).fetchall()
    has_more = len(rows) > bounded
    page = rows[:bounded]
    busiest_count = max(row["visits"] for row in hour_rows)
    return {
        "species_key": species_key,
        "common_name": newest["effective_common"],
        "scientific": newest["effective_scientific"],
        "visits": summary["visits"],
        "first_seen": summary["first_seen"],
        "last_seen": summary["last_seen"],
        "busiest_hours": [
            row["hour"] for row in hour_rows if row["visits"] == busiest_count
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
