from __future__ import annotations

import inspect
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from common import db
from journal import queries
from journal.app import create_app


LABELS = """0 background
1 Cyanocitta cristata (Blue Jay)
2 Cardinalis cardinalis (Northern Cardinal)
3 Turdus migratorius (American Robin)
"""


class JournalApiTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        root = Path(self.temporary.name)
        self.db_path = root / "feeder.sqlite"
        self.labels_path = root / "labels.txt"
        self.labels_path.write_text(LABELS, encoding="utf-8")
        db.initialize(self.db_path)
        conn = db.connect(self.db_path)
        try:
            self.blue_jay_id = self.add_detection(
                conn,
                "Blue Jay",
                "Cyanocitta cristata",
                "2026-07-13T14:00:00Z",
            )
            self.cardinal_id = self.add_detection(
                conn,
                "Northern Cardinal",
                "Cardinalis cardinalis",
                "2026-07-12T13:00:00Z",
            )
            self.older_blue_jay_id = self.add_detection(
                conn,
                "Blue Jay",
                "Cyanocitta cristata",
                "2026-07-11T12:00:00Z",
            )
        finally:
            conn.close()
        self.app = create_app(
            {
                "TESTING": True,
                "DB_PATH": str(self.db_path),
                "LABELS_PATH": str(self.labels_path),
                "TZ": "America/New_York",
            }
        )
        self.client = self.app.test_client()

    def tearDown(self) -> None:
        self.temporary.cleanup()

    @staticmethod
    def add_detection(
        conn: sqlite3.Connection,
        common: str,
        scientific: str,
        captured_at: str,
    ) -> int:
        clip_id = db.add_clip(conn, f"clip-{captured_at}.mp4", "feeder", captured_at)
        return db.add_detection(
            conn,
            clip_id,
            common,
            scientific,
            0.91,
            captured_at,
            f"thumbs/{clip_id}.jpg",
            f"images/{clip_id}.jpg",
        )

    def assert_error(self, response, status: int, code: str) -> None:
        self.assertEqual(response.status_code, status)
        self.assertEqual(response.json["error"], code)

    def test_health_and_today(self) -> None:
        self.assertEqual(self.client.get("/api/health").json, {"status": "ok"})
        today = self.client.get("/api/today")
        self.assertEqual(today.status_code, 200)
        self.assertIn("hourly_activity", today.json)
        self.assertEqual(len(today.json["recent"]), 3)
        self.assertIn("is_first_visit", today.json["latest"])
        self.assertFalse(today.json["latest"]["is_first_visit"])

    def test_today_status_uses_history_older_than_the_recent_page(self) -> None:
        conn = db.connect(self.db_path)
        try:
            for hour in range(14, 24):
                self.add_detection(
                    conn,
                    "Northern Cardinal",
                    "Cardinalis cardinalis",
                    f"2026-07-12T{hour}:00:00Z",
                )
            for hour in range(0, 3):
                self.add_detection(
                    conn,
                    "American Robin",
                    "Turdus migratorius",
                    f"2026-07-13T0{hour}:00:00Z",
                )
        finally:
            conn.close()

        today = self.client.get("/api/today")

        self.assertEqual(len(today.json["recent"]), 12)
        self.assertNotIn(
            self.older_blue_jay_id,
            [visit["id"] for visit in today.json["recent"]],
        )
        self.assertFalse(today.json["latest"]["is_first_visit"])

    def test_every_route_rejects_unknown_query_parameters(self) -> None:
        species_key = "sci:cyanocitta cristata"
        requests = (
            ("get", "/api/health?unexpected=value", None),
            ("get", "/api/today?unexpected=value", None),
            ("get", "/api/detections?unexpected=value", None),
            ("get", f"/api/detections/{self.blue_jay_id}?unexpected=value", None),
            (
                "patch",
                f"/api/detections/{self.blue_jay_id}?unexpected=value",
                {"favorite": True},
            ),
            ("get", "/api/species?unexpected=value", None),
            ("get", f"/api/species/{species_key}?unexpected=value", None),
            ("get", "/api/taxa?unexpected=value", None),
        )
        for method, path, body in requests:
            with self.subTest(method=method, path=path):
                response = getattr(self.client, method)(path, json=body)
                self.assert_error(response, 400, "bad_request")

    def test_history_filters_and_stable_cursor(self) -> None:
        first = self.client.get("/api/detections?limit=1")
        self.assertEqual(
            [item["id"] for item in first.json["detections"]], [self.blue_jay_id]
        )
        cursor = first.json["next_cursor"]
        self.assertIsNotNone(cursor)

        conn = db.connect(self.db_path)
        try:
            self.add_detection(
                conn, "American Robin", "Turdus migratorius", "2026-07-14T14:00:00Z"
            )
        finally:
            conn.close()

        second = self.client.get("/api/detections", query_string={"limit": 1, "cursor": cursor})
        self.assertEqual(
            [item["id"] for item in second.json["detections"]], [self.cardinal_id]
        )
        favorite = self.client.get("/api/detections?favorite=true")
        self.assertEqual(favorite.json["detections"], [])
        dated = self.client.get("/api/detections?date=2026-07-12")
        self.assertEqual(
            [item["id"] for item in dated.json["detections"]], [self.cardinal_id]
        )
        blue_jays = self.client.get(
            "/api/detections", query_string={"species": "sci:cyanocitta cristata"}
        )
        self.assertEqual(len(blue_jays.json["detections"]), 2)

    def test_history_rejects_bad_bounds_filters_and_cursor(self) -> None:
        for query in (
            "limit=0",
            "limit=101",
            "limit=bird",
            "favorite=perhaps",
            "date=not-a-date",
            "cursor=not-json-base64",
        ):
            with self.subTest(query=query):
                response = self.client.get(f"/api/detections?{query}")
                self.assert_error(response, 400, "bad_request")
        malformed = queries._encode_cursor(
            {"captured_at": "2026-07-13T14:00:00Z", "id": self.blue_jay_id}
        ) + "$"
        response = self.client.get("/api/detections", query_string={"cursor": malformed})
        self.assert_error(response, 400, "bad_request")
        self.assertEqual(response.json["message"], "malformed cursor")

    def test_limit_above_one_hundred_is_rejected_even_if_configured_higher(self) -> None:
        permissive_app = create_app(
            {
                "TESTING": True,
                "DB_PATH": str(self.db_path),
                "LABELS_PATH": str(self.labels_path),
                "MAX_PAGE_SIZE": 500,
            }
        )

        response = permissive_app.test_client().get("/api/detections?limit=101")

        self.assert_error(response, 400, "bad_request")

    def test_detection_detail_patch_and_errors(self) -> None:
        detail = self.client.get(f"/api/detections/{self.blue_jay_id}")
        self.assertEqual(detail.json["id"], self.blue_jay_id)

        favorite = self.client.patch(
            f"/api/detections/{self.blue_jay_id}", json={"favorite": True}
        )
        self.assertTrue(favorite.json["favorite"])
        invalid = self.client.patch(
            f"/api/detections/{self.blue_jay_id}",
            json={"correction": "Invented Finch"},
        )
        self.assert_error(invalid, 422, "invalid_correction")
        for response in (
            self.client.patch(
                f"/api/detections/{self.blue_jay_id}", json={"favorite": "yes"}
            ),
            self.client.patch(f"/api/detections/{self.blue_jay_id}", data="not-json"),
        ):
            self.assert_error(response, 400, "bad_request")

        self.assert_error(self.client.get("/api/detections/99999"), 404, "not_found")
        self.assert_error(self.client.get("/api/detections/not-an-id"), 404, "not_found")
        self.assert_error(
            self.client.patch("/api/detections/99999", json={"favorite": True}),
            404,
            "not_found",
        )

    def test_species_search_sorts_detail_gallery_and_shared_opened_state(self) -> None:
        newest = self.client.get("/api/species?q=blue&sort=newest")
        self.assertEqual(newest.json["species"][0]["common_name"], "Blue Jay")
        self.assertTrue(newest.json["species"][0]["is_new"])
        visits = self.client.get("/api/species?sort=visits")
        self.assertEqual(visits.json["species"][0]["visits"], 2)
        alphabetical = self.client.get("/api/species?sort=alphabetical")
        self.assertEqual(alphabetical.json["species"][0]["common_name"], "Blue Jay")
        recent = self.client.get("/api/species?sort=recent")
        self.assertEqual(recent.status_code, 200)
        self.assert_error(self.client.get("/api/species?sort=unknown"), 400, "bad_request")

        key = newest.json["species"][0]["species_key"]
        detail = self.client.get(
            f"/api/species/{key}", query_string={"limit": 1}
        )
        self.assertEqual(detail.json["visits"], 2)
        self.assertEqual(len(detail.json["gallery"]), 1)
        self.assertIsNotNone(detail.json["next_cursor"])
        self.assertFalse(
            self.client.get("/api/species?q=blue").json["species"][0]["is_new"]
        )
        next_page = self.client.get(
            f"/api/species/{key}",
            query_string={"limit": 1, "cursor": detail.json["next_cursor"]},
        )
        self.assertEqual(next_page.json["gallery"][0]["id"], self.older_blue_jay_id)

    def test_species_collection_is_bounded_by_limit(self) -> None:
        result = self.client.get("/api/species?limit=1")

        self.assertEqual(result.status_code, 200)
        self.assertEqual(len(result.json["species"]), 1)
        for query in ("limit=0", "limit=101", "limit=bird"):
            with self.subTest(query=query):
                self.assert_error(
                    self.client.get(f"/api/species?{query}"), 400, "bad_request"
                )

    def test_species_detail_rejects_bounds_cursor_and_missing_species(self) -> None:
        key = "sci:cyanocitta cristata"
        for query in ("limit=0", "limit=101", "limit=bird", "cursor=broken"):
            with self.subTest(query=query):
                self.assert_error(
                    self.client.get(f"/api/species/{key}?{query}"),
                    400,
                    "bad_request",
                )
        self.assert_error(
            self.client.get("/api/species/sci:not-present"), 404, "not_found"
        )

    def test_taxa_search_is_bounded_and_validated(self) -> None:
        result = self.client.get("/api/taxa?q=card&limit=1")
        self.assertEqual(result.json["taxa"][0]["common_name"], "Northern Cardinal")
        self.assertLessEqual(len(self.client.get("/api/taxa?q=&limit=100").json["taxa"]), 100)
        for query in ("limit=0", "limit=101", "limit=bird"):
            with self.subTest(query=query):
                self.assert_error(
                    self.client.get(f"/api/taxa?q=card&{query}"), 400, "bad_request"
                )

    def test_locked_database_returns_retryable_service_unavailable(self) -> None:
        locked = sqlite3.OperationalError("database is locked")
        with mock.patch("journal.app.db.connect", side_effect=locked) as connect:
            response = self.client.get("/api/health")

        self.assertEqual(response.status_code, 503)
        self.assertEqual(
            response.json, {"error": "database_busy", "retryable": True}
        )
        self.assertEqual(connect.call_count, 3)

    def test_journal_connection_uses_configured_short_busy_timeout(self) -> None:
        self.assertIn("timeout_seconds", inspect.signature(db.connect).parameters)
        default_conn = db.connect(self.db_path)
        try:
            self.assertEqual(
                default_conn.execute("PRAGMA busy_timeout").fetchone()[0], 5000
            )
        finally:
            default_conn.close()

        journal_conn = db.connect(self.db_path, timeout_seconds=0.05)
        try:
            self.assertEqual(
                journal_conn.execute("PRAGMA busy_timeout").fetchone()[0], 50
            )
        finally:
            journal_conn.close()

        with mock.patch("journal.app.db.connect", wraps=db.connect) as connect:
            response = self.client.get("/api/health")

        self.assertEqual(response.status_code, 200)
        connect.assert_called_once_with(str(self.db_path), timeout_seconds=0.05)

    def test_health_read_succeeds_while_wal_writer_holds_immediate_transaction(self) -> None:
        writer = db.connect(self.db_path)
        try:
            writer.execute("BEGIN IMMEDIATE")
            writer.execute(
                "INSERT INTO state(key, value) VALUES('writer-test', 'pending')"
            )

            response = self.client.get("/api/health")

            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.json, {"status": "ok"})
        finally:
            writer.rollback()
            writer.close()

    def test_unexpected_errors_are_sanitized_in_response_and_logs(self) -> None:
        secret = "secret-token-that-must-not-leak"
        self.app.config["PROPAGATE_EXCEPTIONS"] = False
        with mock.patch(
            "journal.app.queries.today", side_effect=RuntimeError(secret)
        ), self.assertLogs("journal", level="ERROR") as captured:
            response = self.client.get("/api/today")

        self.assertEqual(response.status_code, 500)
        self.assertEqual(response.json, {"error": "internal_error"})
        logs = "\n".join(captured.output)
        self.assertIn("category=unexpected", logs)
        self.assertNotIn(secret, logs)
        self.assertNotIn("Traceback", logs)

    def test_http_exceptions_preserve_sanitized_status(self) -> None:
        response = self.client.post("/api/health")

        self.assertEqual(response.status_code, 405)
        self.assertEqual(response.json, {"error": "method_not_allowed"})
        self.assertNotIn("Method Not Allowed", response.get_data(as_text=True))


if __name__ == "__main__":
    unittest.main()
