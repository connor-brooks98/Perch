"""Private HTTP API for the shared family journal."""
from __future__ import annotations

import os
import sqlite3
import time
from collections.abc import Callable
from typing import Any, TypeVar

from flask import Flask, jsonify, request

from common import db
from journal import queries
from journal.labels import LabelCatalog


DEFAULTS = {
    "DB_PATH": os.getenv("DB_PATH", "/data/db/feeder.sqlite"),
    "LABELS_PATH": os.getenv("LABELS_PATH", "/app/model/labels.txt"),
    "TZ": os.getenv("TZ", "America/New_York"),
    "MAX_PAGE_SIZE": 100,
}

T = TypeVar("T")


def with_db_retry(
    operation: Callable[[], T], attempts: int = 3, delay_seconds: float = 0.05
) -> T:
    for attempt in range(attempts):
        try:
            return operation()
        except sqlite3.OperationalError as exc:
            if "locked" not in str(exc).casefold() or attempt == attempts - 1:
                raise
            time.sleep(delay_seconds * (attempt + 1))
    raise RuntimeError("unreachable")


def create_app(config: dict[str, Any] | None = None) -> Flask:
    app = Flask(__name__)
    app.config.from_mapping(DEFAULTS)
    if config:
        app.config.update(config)
    catalog = LabelCatalog.from_file(app.config["LABELS_PATH"])

    def error(code: str, status: int, *, message: str | None = None):
        payload: dict[str, Any] = {"error": code}
        if message is not None:
            payload["message"] = message
        return jsonify(payload), status

    def run_query(operation: Callable[[sqlite3.Connection], T]) -> T:
        def attempt() -> T:
            conn = db.connect(app.config["DB_PATH"])
            try:
                return operation(conn)
            finally:
                conn.close()

        return with_db_retry(attempt)

    def parse_limit(default: int) -> int:
        raw = request.args.get("limit")
        if raw is None:
            return default
        try:
            limit = int(raw)
        except (TypeError, ValueError) as exc:
            raise ValueError("invalid limit") from exc
        maximum = min(int(app.config["MAX_PAGE_SIZE"]), 100)
        if limit < 1 or limit > maximum:
            raise ValueError("invalid limit")
        return limit

    def parse_favorite() -> bool | None:
        raw = request.args.get("favorite")
        if raw is None:
            return None
        if raw.casefold() == "true":
            return True
        if raw.casefold() == "false":
            return False
        raise ValueError("invalid favorite filter")

    @app.errorhandler(queries.InvalidCursor)
    def invalid_cursor(_exc):
        return error("bad_request", 400, message="malformed cursor")

    @app.errorhandler(queries.InvalidCorrection)
    def invalid_correction(_exc):
        return error("invalid_correction", 422)

    @app.errorhandler(ValueError)
    def bad_value(_exc):
        return error("bad_request", 400)

    @app.errorhandler(sqlite3.OperationalError)
    def database_error(exc):
        if "locked" in str(exc).casefold():
            return jsonify(error="database_busy", retryable=True), 503
        return error("internal_error", 500)

    @app.errorhandler(400)
    def bad_request(_exc):
        return error("bad_request", 400)

    @app.errorhandler(404)
    def not_found(_exc):
        return error("not_found", 404)

    @app.get("/api/health")
    def health():
        run_query(lambda conn: conn.execute("SELECT 1").fetchone())
        return jsonify(status="ok")

    @app.get("/api/today")
    def today():
        result = run_query(lambda conn: queries.today(conn, app.config["TZ"]))
        return jsonify(result)

    @app.get("/api/detections")
    def detections():
        limit = parse_limit(20)
        result = run_query(
            lambda conn: queries.detections(
                conn,
                cursor=request.args.get("cursor"),
                limit=limit,
                species_key=request.args.get("species"),
                favorite=parse_favorite(),
                local_date=request.args.get("date"),
                tz_name=app.config["TZ"],
            )
        )
        return jsonify(result)

    @app.get("/api/detections/<int:detection_id>")
    def detection_detail(detection_id: int):
        result = run_query(lambda conn: queries.detection(conn, detection_id))
        if result is None:
            return error("not_found", 404)
        return jsonify(result)

    @app.patch("/api/detections/<int:detection_id>")
    def patch_detection(detection_id: int):
        patch = request.get_json(silent=True)
        if not isinstance(patch, dict):
            return error("bad_request", 400)
        result = run_query(
            lambda conn: queries.patch_detection(conn, detection_id, patch, catalog)
        )
        if result is None:
            return error("not_found", 404)
        return jsonify(result)

    @app.get("/api/species")
    def species():
        result = run_query(
            lambda conn: queries.species(
                conn,
                query=request.args.get("q", ""),
                sort=request.args.get("sort", "newest"),
            )
        )
        return jsonify(result)

    @app.get("/api/species/<species_key>")
    def species_detail(species_key: str):
        limit = parse_limit(24)

        def load_and_mark(conn: sqlite3.Connection):
            result = queries.species_detail(
                conn,
                species_key,
                cursor=request.args.get("cursor"),
                limit=limit,
                tz_name=app.config["TZ"],
            )
            if result is not None:
                queries.mark_species_opened(conn, species_key)
            return result

        result = run_query(load_and_mark)
        if result is None:
            return error("not_found", 404)
        return jsonify(result)

    @app.get("/api/taxa")
    def taxa():
        limit = parse_limit(20)
        return jsonify(
            taxa=[taxon.as_dict() for taxon in catalog.search(request.args.get("q", ""), limit)]
        )

    return app
