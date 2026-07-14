from __future__ import annotations

import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from common import db
from journal.app import create_app


LABELS = """0 background
1 Cyanocitta cristata (Blue Jay)
"""
SPECIES_KEY = "sci:cyanocitta cristata"


class EnrichmentApiTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        root = Path(self.temporary.name)
        self.db_path = root / "feeder.sqlite"
        labels_path = root / "labels.txt"
        labels_path.write_text(LABELS, encoding="utf-8")
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
        self.service.get.assert_called_once_with(SPECIES_KEY)
        self.service.schedule.assert_called_once_with(
            species_key=SPECIES_KEY,
            common="Blue Jay",
            scientific="Cyanocitta cristata",
        )

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
            "reference_image": "blue-jay.jpg",
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
                    "src": "/enrichment/blue-jay.jpg",
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
        )

    def test_reference_image_requires_complete_attribution(self) -> None:
        self.service.get.return_value = {
            "status": "ready",
            "introduction": "Cached introduction.",
            "reference_image": "https://third-party.example/bird.jpg",
            "image_creator": "Jane Birder",
            "image_license": "CC BY 4.0",
            "image_source_url": "https://third-party.example/source",
        }

        response = self.get_species()

        self.assertEqual(response.status_code, 200)
        self.assertIsNone(response.json["enrichment"]["reference_image"])
        self.assertNotIn("https://third-party.example/bird.jpg", response.get_data(as_text=True))
        self.service.schedule.assert_not_called()


if __name__ == "__main__":
    unittest.main()
