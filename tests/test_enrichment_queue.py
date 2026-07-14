from __future__ import annotations

import tempfile
import threading
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import mock

from common import db
from journal.app import create_app
from journal.enrichment import EnrichmentFailure, EnrichmentService
from journal.providers import PageSummary, PhotoMetadata, ReferenceImage, TaxonMatch


NOW = datetime(2026, 7, 14, 12, 0, tzinfo=timezone.utc)


class FakeProvider:
    def __init__(self, *, failure: BaseException | None = None) -> None:
        self.failure = failure
        self.calls: list[tuple[str, object]] = []
        self.photo = PhotoMetadata(
            url="https://static.inaturalist.org/photos/1.jpg",
            attribution="(c) Jane Birder, CC BY 4.0",
            creator="Jane Birder",
            license_code="cc-by",
        )

    def __bool__(self) -> bool:
        return False

    def match_species(self, scientific_name: str):
        self.calls.append(("match", scientific_name))
        if self.failure is not None:
            raise self.failure
        return TaxonMatch(
            taxon_id=123,
            scientific_name=scientific_name,
            wikipedia_url="https://en.wikipedia.org/wiki/Blue_jay",
            photo=self.photo,
        )

    def fetch_summary(self, wikipedia_url: str):
        self.calls.append(("summary", wikipedia_url))
        return PageSummary(
            extract="The blue jay is a bird.",
            page_url="https://en.wikipedia.org/wiki/Blue_jay",
        )

    def download_reference_image(self, photo: PhotoMetadata, destination: Path):
        self.calls.append(("image", destination))
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(b"safe image")
        return ReferenceImage(
            path=destination,
            creator=photo.creator,
            license_code=photo.license_code,
            source_url=photo.url,
        )


class EnrichmentServiceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.db_path = self.root / "feeder.sqlite"
        self.image_dir = self.root / "enrichment"
        db.connect(self.db_path).close()
        self.provider = FakeProvider()
        self.service = EnrichmentService(
            self.db_path,
            self.image_dir,
            provider=self.provider,
            clock=lambda: NOW,
        )

    def tearDown(self) -> None:
        self.service.stop()
        self.temporary.cleanup()

    def seed_profile(
        self,
        *,
        fetched_at: datetime | None,
        retry_after: datetime | None = None,
        error_category: str | None = None,
    ) -> None:
        conn = db.connect(self.db_path)
        try:
            with conn:
                conn.execute(
                    "INSERT INTO species_profiles("
                    "species_key, inat_taxon_id, introduction, inat_url, "
                    "wikipedia_url, reference_image, image_source_url, "
                    "image_creator, image_license, fetched_at, retry_after, "
                    "error_category, updated_at) VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (
                        "sci:cyanocitta cristata",
                        123,
                        "Cached introduction",
                        "https://www.inaturalist.org/taxa/123",
                        "https://en.wikipedia.org/wiki/Blue_jay",
                        "blue-jay.jpg",
                        "https://static.inaturalist.org/photos/1.jpg",
                        "Jane Birder",
                        "cc-by",
                        self.iso(fetched_at),
                        self.iso(retry_after),
                        error_category,
                        self.iso(NOW),
                    ),
                )
        finally:
            conn.close()

    @staticmethod
    def iso(value: datetime | None) -> str | None:
        return value.strftime("%Y-%m-%dT%H:%M:%SZ") if value else None

    def test_get_distinguishes_fresh_stale_missing_and_active_failure(self) -> None:
        self.assertEqual(
            self.service.get("sci:missing bird"),
            {"status": "pending"},
        )

        self.seed_profile(fetched_at=NOW - timedelta(days=89))
        fresh = self.service.get("sci:cyanocitta cristata")
        self.assertEqual(fresh["status"], "ready")
        self.assertEqual(fresh["introduction"], "Cached introduction")
        self.assertEqual(self.service._queue.qsize(), 0)

        conn = db.connect(self.db_path)
        with conn:
            conn.execute(
                "UPDATE species_profiles SET fetched_at = ? WHERE species_key = ?",
                (self.iso(NOW - timedelta(days=90)), "sci:cyanocitta cristata"),
            )
        conn.close()
        stale = self.service.get("sci:cyanocitta cristata")
        self.assertEqual(stale["status"], "stale")
        self.assertEqual(stale["introduction"], "Cached introduction")

        conn = db.connect(self.db_path)
        with conn:
            conn.execute(
                "UPDATE species_profiles SET error_category = ?, retry_after = ? "
                "WHERE species_key = ?",
                (
                    "timeout",
                    self.iso(NOW + timedelta(minutes=15)),
                    "sci:cyanocitta cristata",
                ),
            )
        conn.close()
        self.assertEqual(
            self.service.get("sci:cyanocitta cristata"),
            {
                "status": "failed",
                "error_category": "timeout",
                "retry_after": self.iso(NOW + timedelta(minutes=15)),
            },
        )

    def test_schedule_collapses_duplicates_and_recovers_after_queue_rejection(self) -> None:
        self.assertTrue(
            self.service.schedule(
                species_key="sci:cyanocitta cristata",
                common="Blue Jay",
                scientific="Cyanocitta cristata",
            )
        )
        self.assertFalse(
            self.service.schedule(
                "sci:cyanocitta cristata", "Blue Jay", "Cyanocitta cristata"
            )
        )
        self.assertEqual(self.service._queue.qsize(), 1)

        for index in range(99):
            self.assertTrue(
                self.service.schedule(
                    f"sci:bird {index}", f"Bird {index}", f"Birdus {index}"
                )
            )
        rejected_key = "sci:queue overflow"
        self.assertFalse(
            self.service.schedule(rejected_key, "Overflow", "Queue overflow")
        )
        with self.service._queued_lock:
            self.assertNotIn(rejected_key, self.service._queued_keys)

    def test_schedule_refuses_fresh_profiles_and_active_retry_delays(self) -> None:
        self.seed_profile(fetched_at=NOW - timedelta(days=1))
        self.assertFalse(
            self.service.schedule(
                "sci:cyanocitta cristata", "Blue Jay", "Cyanocitta cristata"
            )
        )

        conn = db.connect(self.db_path)
        with conn:
            conn.execute(
                "UPDATE species_profiles SET fetched_at = ?, error_category = ?, retry_after = ? "
                "WHERE species_key = ?",
                (
                    self.iso(NOW - timedelta(days=100)),
                    "timeout",
                    self.iso(NOW + timedelta(minutes=15)),
                    "sci:cyanocitta cristata",
                ),
            )
        conn.close()
        self.assertFalse(
            self.service.schedule(
                "sci:cyanocitta cristata", "Blue Jay", "Cyanocitta cristata"
            )
        )

        conn = db.connect(self.db_path)
        with conn:
            conn.execute(
                "UPDATE species_profiles SET retry_after = ? WHERE species_key = ?",
                (self.iso(NOW), "sci:cyanocitta cristata"),
            )
        conn.close()
        self.assertTrue(
            self.service.schedule(
                "sci:cyanocitta cristata", "Blue Jay", "Cyanocitta cristata"
            )
        )

    def test_worker_successfully_caches_sanitized_provider_and_image_data(self) -> None:
        self.service.start()
        self.assertTrue(
            self.service.schedule(
                "sci:cyanocitta cristata", "Blue Jay", "Cyanocitta cristata"
            )
        )
        self.service._queue.join()

        profile = self.service.get("sci:cyanocitta cristata")
        self.assertEqual(profile["status"], "ready")
        self.assertEqual(profile["inat_taxon_id"], 123)
        self.assertEqual(profile["introduction"], "The blue jay is a bird.")
        self.assertEqual(profile["inat_url"], "https://www.inaturalist.org/taxa/123")
        self.assertEqual(profile["image_creator"], "Jane Birder")
        self.assertEqual(profile["image_license"], "cc-by")
        self.assertNotIn("/", profile["reference_image"])
        self.assertTrue((self.image_dir / profile["reference_image"]).is_file())

        conn = db.connect(self.db_path)
        row = conn.execute(
            "SELECT error_category, retry_after FROM species_profiles WHERE species_key = ?",
            ("sci:cyanocitta cristata",),
        ).fetchone()
        conn.close()
        self.assertIsNone(row["error_category"])
        self.assertIsNone(row["retry_after"])

        first_image = profile["reference_image"]
        conn = db.connect(self.db_path)
        with conn:
            conn.execute(
                "UPDATE species_profiles SET fetched_at = ? WHERE species_key = ?",
                (self.iso(NOW - timedelta(days=100)), "sci:cyanocitta cristata"),
            )
        conn.close()
        self.assertTrue(
            self.service.schedule(
                "sci:cyanocitta cristata", "Blue Jay", "Cyanocitta cristata"
            )
        )
        self.service._queue.join()
        refreshed = self.service.get("sci:cyanocitta cristata")
        self.assertNotEqual(refreshed["reference_image"], first_image)
        self.assertTrue((self.image_dir / first_image).is_file())

    def test_worker_restart_processes_new_work_without_stale_duplicate_keys(self) -> None:
        self.service.start()
        self.service.stop()
        self.service.start()
        self.assertTrue(
            self.service.schedule(
                "sci:cyanocitta cristata", "Blue Jay", "Cyanocitta cristata"
            )
        )
        self.service._queue.join()
        self.assertEqual(self.service.get("sci:cyanocitta cristata")["status"], "ready")
        with self.service._queued_lock:
            self.assertEqual(self.service._queued_keys, set())

    def test_worker_survives_a_failure_cache_write_and_processes_next_job(self) -> None:
        reached_second_job = threading.Event()
        original_match = self.provider.match_species
        attempts = 0

        def match(scientific_name: str):
            nonlocal attempts
            attempts += 1
            if attempts == 1:
                raise EnrichmentFailure("unavailable", "secret provider body")
            reached_second_job.set()
            return original_match(scientific_name)

        self.provider.match_species = match
        self.service._store_failure = mock.Mock(
            side_effect=OSError("secret database detail")
        )
        self.assertTrue(self.service.schedule("sci:first bird", "First", "First bird"))
        self.assertTrue(self.service.schedule("sci:second bird", "Second", "Second bird"))
        with self.assertLogs("journal.enrichment", level="ERROR") as logs:
            self.service.start()
            self.assertTrue(reached_second_job.wait(0.5))
        self.assertNotIn("secret database detail", " ".join(logs.output))

    def test_failures_are_categorized_delayed_and_do_not_replace_stale_content(self) -> None:
        cases = {
            "not_found": timedelta(hours=24),
            "throttled": timedelta(hours=1),
            "timeout": timedelta(minutes=15),
            "malformed": timedelta(hours=6),
            "unavailable": timedelta(minutes=15),
        }
        for category, delay in cases.items():
            with self.subTest(category=category):
                key = f"sci:{category} bird"
                conn = db.connect(self.db_path)
                with conn:
                    conn.execute(
                        "INSERT INTO species_profiles(species_key, introduction, fetched_at, updated_at) "
                        "VALUES(?, ?, ?, ?)",
                        (key, "Keep this stale text", self.iso(NOW - timedelta(days=100)), self.iso(NOW)),
                    )
                conn.close()
                provider = FakeProvider(failure=EnrichmentFailure(category, "secret body"))
                service = EnrichmentService(
                    self.db_path,
                    self.image_dir,
                    provider=provider,
                    clock=lambda: NOW,
                )
                service.start()
                with self.assertLogs("journal.enrichment", level="WARNING") as logs:
                    self.assertTrue(
                        service.schedule(key, category.title(), f"{category} bird")
                    )
                    service._queue.join()
                service.stop()

                self.assertEqual(
                    service.get(key),
                    {
                        "status": "failed",
                        "error_category": category,
                        "retry_after": self.iso(NOW + delay),
                    },
                )
                conn = db.connect(self.db_path)
                row = conn.execute(
                    "SELECT introduction, error_category, retry_after FROM species_profiles "
                    "WHERE species_key = ?",
                    (key,),
                ).fetchone()
                dump = " ".join("" if value is None else str(value) for value in row)
                conn.close()
                self.assertEqual(row["introduction"], "Keep this stale text")
                self.assertNotIn("secret body", dump)
                self.assertNotIn("secret body", " ".join(logs.output))


class EnrichmentAppFactoryTests(unittest.TestCase):
    def test_factory_owns_one_injectable_service_and_can_disable_test_autostart(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            labels = root / "labels.txt"
            labels.write_text("0 background\n1 Cyanocitta cristata (Blue Jay)\n")
            provider = FakeProvider()
            with mock.patch.object(EnrichmentService, "start") as start:
                app = create_app(
                    {
                        "TESTING": True,
                        "DB_PATH": str(root / "feeder.sqlite"),
                        "LABELS_PATH": str(labels),
                        "ENRICHMENT_DIR": str(root / "enrichment"),
                        "ENRICHMENT_PROVIDER": provider,
                        "ENRICHMENT_CLOCK": lambda: NOW,
                        "ENRICHMENT_AUTOSTART": False,
                    }
                )

            self.assertIsInstance(app.extensions["enrichment"], EnrichmentService)
            self.assertIs(app.extensions["enrichment"].provider, provider)
            start.assert_not_called()

    def test_testing_apps_do_not_leak_workers_without_an_explicit_opt_in(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            labels = root / "labels.txt"
            labels.write_text("0 background\n1 Cyanocitta cristata (Blue Jay)\n")
            with mock.patch.object(EnrichmentService, "start") as start:
                create_app(
                    {
                        "TESTING": True,
                        "DB_PATH": str(root / "feeder.sqlite"),
                        "LABELS_PATH": str(labels),
                    }
                )
            start.assert_not_called()


if __name__ == "__main__":
    unittest.main()
