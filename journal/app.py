"""Private HTTP API for the shared family journal."""
from __future__ import annotations

import logging
import os
import sqlite3
import time
from collections.abc import Callable
from typing import Any, TypeVar

from flask import Flask, jsonify, request
from werkzeug.exceptions import HTTPException

from common import db
from journal import queries
from journal.enrichment import EnrichmentService
from journal.labels import LabelCatalog


DEFAULTS = {
    "DB_PATH": os.getenv("DB_PATH", "/data/db/feeder.sqlite"),
    "LABELS_PATH": os.getenv("LABELS_PATH", "/app/model/labels.txt"),
    "TZ": os.getenv("TZ", "America/New_York"),
    "MAX_PAGE_SIZE": 100,
    "DB_TIMEOUT_SECONDS": 0.05,
    "ENRICHMENT_DB_TIMEOUT_SECONDS": 0.01,
    "ENRICHMENT_DIR": os.getenv("ENRICHMENT_DIR", "/data/web/enrichment"),
    "ENRICHMENT_AUTOSTART": None,
}

T = TypeVar("T")
log = logging.getLogger("journal")


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
    provider = app.config.get("ENRICHMENT_PROVIDER")
    enrichment = EnrichmentService(
        app.config["DB_PATH"],
        app.config["ENRICHMENT_DIR"],
        provider=provider,
        clock=app.config.get("ENRICHMENT_CLOCK"),
    )
    app.extensions["enrichment"] = enrichment
    autostart = app.config.get("ENRICHMENT_AUTOSTART")
    if autostart is None:
        autostart = not app.config.get("TESTING")
    if autostart:
        enrichment.start()

    def error(code: str, status: int, *, message: str | None = None):
        payload: dict[str, Any] = {"error": code}
        if message is not None:
            payload["message"] = message
        return jsonify(payload), status

    def run_query(operation: Callable[[sqlite3.Connection], T]) -> T:
        def attempt() -> T:
            conn = db.connect(
                app.config["DB_PATH"],
                timeout_seconds=app.config["DB_TIMEOUT_SECONDS"],
            )
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

    def allow_query_parameters(allowed: set[str]) -> None:
        if set(request.args) - allowed:
            raise ValueError("unknown query parameter")

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
        log.error("journal_api_error category=database")
        return error("internal_error", 500)

    @app.errorhandler(Exception)
    def unexpected_error(exc):
        if isinstance(exc, HTTPException):
            status = exc.code or 500
            code = {
                400: "bad_request",
                404: "not_found",
                405: "method_not_allowed",
            }.get(status, "http_error")
            return error(code, status)
        log.error("journal_api_error category=unexpected")
        return error("internal_error", 500)

    @app.errorhandler(400)
    def bad_request(_exc):
        return error("bad_request", 400)

    @app.errorhandler(404)
    def not_found(_exc):
        return error("not_found", 404)

    @app.get("/api/health")
    def health():
        allow_query_parameters(set())
        run_query(lambda conn: conn.execute("SELECT 1").fetchone())
        return jsonify(status="ok")

    @app.get("/api/today")
    def today():
        allow_query_parameters(set())
        result = run_query(lambda conn: queries.today(conn, app.config["TZ"]))
        return jsonify(result)

    @app.get("/api/detections")
    def detections():
        allow_query_parameters(
            {"cursor", "limit", "species", "favorite", "date"}
        )
        limit = parse_limit(20)
        favorite = parse_favorite()
        result = run_query(
            lambda conn: queries.detections(
                conn,
                cursor=request.args.get("cursor"),
                limit=limit,
                species_key=request.args.get("species"),
                favorite=favorite,
                local_date=request.args.get("date"),
                tz_name=app.config["TZ"],
            )
        )
        return jsonify(result)

    @app.get("/api/detections/<int:detection_id>")
    def detection_detail(detection_id: int):
        allow_query_parameters(set())
        result = run_query(lambda conn: queries.detection(conn, detection_id))
        if result is None:
            return error("not_found", 404)
        return jsonify(result)

    @app.patch("/api/detections/<int:detection_id>")
    def patch_detection(detection_id: int):
        allow_query_parameters(set())
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
        allow_query_parameters({"q", "sort", "limit"})
        limit = parse_limit(100)
        result = run_query(
            lambda conn: queries.species(
                conn,
                query=request.args.get("q", ""),
                sort=request.args.get("sort", "newest"),
                limit=limit,
            )
        )
        return jsonify(result)

    @app.get("/api/species/<species_key>")
    def species_detail(species_key: str):
        allow_query_parameters({"cursor", "limit"})
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
        try:
            profile = app.extensions["enrichment"].get(
                species_key,
                timeout_seconds=app.config["ENRICHMENT_DB_TIMEOUT_SECONDS"],
            )
        except Exception:
            log.warning(
                "species_enrichment_failure category=cache species_key=%s",
                species_key,
            )
            profile = {"status": "pending"}
        status = profile.get("status") if isinstance(profile, dict) else None
        if not isinstance(status, str) or status not in {
            "pending",
            "ready",
            "stale",
            "failed",
        }:
            profile = {"status": "pending"}
        if profile["status"] in {"pending", "stale"}:
            try:
                app.extensions["enrichment"].schedule(
                    species_key=species_key,
                    common=result["common_name"],
                    scientific=result["scientific"],
                    cached_profile=profile,
                )
            except Exception:
                log.warning(
                    "species_enrichment_failure category=schedule species_key=%s",
                    species_key,
                )
        result["enrichment"] = queries.serialize_enrichment(profile)
        return jsonify(result)

    @app.get("/api/taxa")
    def taxa():
        allow_query_parameters({"q", "limit"})
        limit = parse_limit(20)
        return jsonify(
            taxa=[taxon.as_dict() for taxon in catalog.search(request.args.get("q", ""), limit)]
        )

    return app
