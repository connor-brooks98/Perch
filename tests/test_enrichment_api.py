from __future__ import annotations

import sqlite3
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

from common import db
from journal.app import create_app
from journal.enrichment import EnrichmentService


LABELS = """0 background
1 Cyanocitta cristata (Blue Jay)
"""
SPECIES_KEY = "sci:cyanocitta cristata"
GENERATED_IMAGE = "a" * 24 + "-" + "b" * 32 + ".jpg"


class EnrichmentApiTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        root = Path(self.temporary.name)
        self.db_path = root / "feeder.sqlite"
        labels_path = root / "labels.txt"
        labels_path.write_text(LABELS, encoding="utf-8")
        db.initialize(self.db_path)
        conn = db.connect(self.db_path)
        try:
            self.add_detection(conn, "2026-07-13T14:00:00Z")
            self.add_detection(conn, "2026-07-11T12:00:00Z")
        finally:
            conn.close()
        self.app = create_app(
            {
                "TESTING": True,
                "DB_PATH": str(self.db_path),
                "LABELS_PATH": str(labels_path),
                "ENRICHMENT_DIR": str(root / "enrichment"),
            }
        )
        self.client = self.app.test_client()
        self.service = mock.Mock()
        self.app.extensions["enrichment"] = self.service

    def tearDown(self) -> None:
        self.temporary.cleanup()

    @staticmethod
    def add_detection(conn: sqlite3.Connection, captured_at: str) -> None:
        clip_id = db.add_clip(conn, f"clip-{captured_at}.mp4", "feeder", captured_at)
        db.add_detection(
            conn,
            clip_id,
            "Blue Jay",
            "Cyanocitta cristata",
            0.91,
            captured_at,
            f"thumbs/{clip_id}.jpg",
            f"images/{clip_id}.jpg",
        )

    def get_species(self):
        return self.client.get("/api/species/sci%3Acyanocitta%20cristata")

    def test_pending_profile_is_returned_and_scheduled_by_keyword(self) -> None:
        self.service.get.return_value = {"status": "pending"}

        response = self.get_species()

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json["visits"], 2)
        self.assertEqual(
            response.json["enrichment"],
            {
                "status": "pending",
                "introduction": None,
                "sources": {"inaturalist": None, "wikipedia": None},
                "reference_image": None,
            },
        )
        self.service.get.assert_called_once_with(SPECIES_KEY, timeout_seconds=0.01)
        self.service.schedule.assert_called_once_with(
            species_key=SPECIES_KEY,
            common="Blue Jay",
            scientific="Cyanocitta cristata",
            cached_profile={"status": "pending"},
        )

    def test_common_only_species_has_terminal_local_only_enrichment(self) -> None:
        conn = db.connect(self.db_path)
        try:
            clip_id = db.add_clip(
                conn, "house-sparrow.mp4", "feeder", "2026-07-12T15:00:00Z"
            )
            db.add_detection(
                conn, clip_id, "House Sparrow", None, 0.88,
                "2026-07-12T15:00:00Z", f"thumbs/{clip_id}.jpg", f"images/{clip_id}.jpg",
            )
        finally:
            conn.close()

        response = self.client.get("/api/species/common%3Ahouse%20sparrow")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json["enrichment"]["status"], "unavailable")
        self.service.get.assert_not_called()
        self.service.schedule.assert_not_called()

    def test_scheduling_failure_never_replaces_local_species_data(self) -> None:
        self.service.get.return_value = {
            "status": "pending",
            "provider_body": "private upstream response",
            "exception": "provider stack trace",
        }
        self.service.schedule.side_effect = RuntimeError("queue/provider detail")

        response = self.get_species()

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json["visits"], 2)
        self.assertEqual(len(response.json["gallery"]), 2)
        serialized = response.get_data(as_text=True)
        self.assertNotIn("provider_body", serialized)
        self.assertNotIn("exception", serialized)
        self.assertNotIn("queue/provider detail", serialized)

    def test_stale_cached_content_is_sanitized_and_refreshed(self) -> None:
        self.service.get.return_value = {
            "status": "stale",
            "introduction": "Cached blue jay introduction.",
            "inat_url": "https://www.inaturalist.org/taxa/8229",
            "wikipedia_url": "https://en.wikipedia.org/wiki/Blue_jay",
            "reference_image": GENERATED_IMAGE,
            "image_creator": "Jane Birder",
            "image_license": "CC BY 4.0",
            "image_source_url": "https://static.inaturalist.org/photos/1.jpg",
            "provider_body": "must not leak",
            "exception": "must not leak",
        }

        response = self.get_species()

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.json["enrichment"],
            {
                "status": "stale",
                "introduction": "Cached blue jay introduction.",
                "sources": {
                    "inaturalist": "https://www.inaturalist.org/taxa/8229",
                    "wikipedia": "https://en.wikipedia.org/wiki/Blue_jay",
                },
                "reference_image": {
                    "src": "/enrichment/" + GENERATED_IMAGE,
                    "creator": "Jane Birder",
                    "license": "CC BY 4.0",
                    "source": "https://static.inaturalist.org/photos/1.jpg",
                },
            },
        )
        self.service.schedule.assert_called_once_with(
            species_key=SPECIES_KEY,
            common="Blue Jay",
            scientific="Cyanocitta cristata",
            cached_profile=self.service.get.return_value,
        )

    def test_reference_image_requires_a_service_generated_filename(self) -> None:
        unsafe_filenames = (
            "https://third-party.example/bird.jpg",
            "..\\secret.jpg",
            "%2e%2e%2fsecret.jpg",
            "%5csecret.jpg",
            "nested/secret.jpg",
        )
        for filename in unsafe_filenames:
            with self.subTest(filename=filename):
                self.service.reset_mock()
                self.service.get.return_value = {
                    "status": "ready",
                    "introduction": "Cached introduction.",
                    "reference_image": filename,
                    "image_creator": "Jane Birder",
                    "image_license": "CC BY 4.0",
                    "image_source_url": "https://third-party.example/source",
                }

                response = self.get_species()

                self.assertEqual(response.status_code, 200)
                self.assertIsNone(response.json["enrichment"]["reference_image"])
                self.assertNotIn(filename, response.get_data(as_text=True))
                self.service.schedule.assert_not_called()

    def test_malformed_cache_status_falls_back_without_losing_local_data(self) -> None:
        for malformed in (["stale"], {"status": "stale"}, None):
            with self.subTest(malformed=malformed):
                self.service.reset_mock()
                self.service.get.return_value = {"status": malformed}

                response = self.get_species()

                self.assertEqual(response.status_code, 200)
                self.assertEqual(response.json["visits"], 2)
                self.assertEqual(response.json["enrichment"]["status"], "pending")

    def test_contended_real_cache_is_tightly_bounded_and_local_data_stays_200(self) -> None:
        root = Path(self.temporary.name)
        cache_path = root / "contended-enrichment.sqlite"
        db.initialize(cache_path)
        real_service = EnrichmentService(cache_path, root / "real-enrichment")
        self.app.extensions["enrichment"] = real_service
        self.app.config["ENRICHMENT_DB_TIMEOUT_SECONDS"] = 0.01
        blocker = sqlite3.connect(cache_path, isolation_level=None)
        try:
            blocker.execute("PRAGMA journal_mode = DELETE")
            blocker.execute("BEGIN EXCLUSIVE")
            started = time.monotonic()

            with mock.patch.object(
                real_service, "get", wraps=real_service.get
            ) as cache_get:
                response = self.get_species()

            elapsed = time.monotonic() - started
        finally:
            blocker.rollback()
            blocker.close()
            real_service.stop()

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json["visits"], 2)
        self.assertEqual(cache_get.call_count, 1)
        self.assertLess(elapsed, 0.25)


if __name__ == "__main__":
    unittest.main()
