from __future__ import annotations

import inspect
import sqlite3
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest import mock

from common import db
from journal import queries
from journal.labels import LabelCatalog


LABELS = """0 background
1 Cyanocitta cristata (Blue Jay)
2 Cardinalis cardinalis (Northern Cardinal)
3 Turdus migratorius (American Robin)
4 House Sparrow
"""


class JournalQueryTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        root = Path(self.temporary.name)
        self.db_path = root / "feeder.sqlite"
        labels_path = root / "labels.txt"
        labels_path.write_text(LABELS, encoding="utf-8")
        self.catalog = LabelCatalog.from_file(labels_path)
        db.initialize(self.db_path)
        self.conn = db.connect(self.db_path)

    def tearDown(self) -> None:
        self.conn.close()
        self.temporary.cleanup()

    def add_detection(
        self,
        common: str = "Blue Jay",
        scientific: str | None = "Cyanocitta cristata",
        captured_at: str = "2026-07-13T14:00:00Z",
        *,
        filename: str | None = None,
    ) -> int:
        count = self.conn.execute("SELECT COUNT(*) FROM clips").fetchone()[0]
        filename = filename or f"clip-{count}.mp4"
        clip_id = db.add_clip(self.conn, filename, "feeder", captured_at)
        return db.add_detection(
            self.conn,
            clip_id,
            common,
            scientific,
            0.91,
            captured_at,
            f"thumbs/{clip_id}.jpg",
            f"images/{clip_id}.jpg",
        )

    def test_catalog_parses_searches_and_resolves_installed_taxa(self) -> None:
        cardinal = self.catalog.resolve(" northern   cardinal ")

        self.assertIsNotNone(cardinal)
        self.assertEqual(cardinal.common_name, "Northern Cardinal")
        self.assertEqual(cardinal.scientific, "Cardinalis cardinalis")
        self.assertEqual(
            [taxon.common_name for taxon in self.catalog.search("card", limit=1)],
            ["Northern Cardinal"],
        )
        self.assertIsNone(self.catalog.resolve("Invented Finch"))
        self.assertEqual(self.catalog.search("", limit=500)[0].common_name, "American Robin")
        self.assertLessEqual(len(self.catalog.search("", limit=500)), 100)

    def test_favorite_is_idempotent_and_original_prediction_is_preserved(self) -> None:
        detection_id = self.add_detection()

        updated = queries.patch_detection(
            self.conn, detection_id, {"favorite": True}, self.catalog
        )
        repeated = queries.patch_detection(
            self.conn, detection_id, {"favorite": True}, self.catalog
        )
        corrected = queries.patch_detection(
            self.conn,
            detection_id,
            {"correction": "Northern Cardinal"},
            self.catalog,
        )

        self.assertTrue(updated["favorite"])
        self.assertEqual(repeated, updated)
        self.assertEqual(corrected["original_species"]["common_name"], "Blue Jay")
        self.assertEqual(
            corrected["effective_species"]["common_name"], "Northern Cardinal"
        )
        stored = self.conn.execute(
            "SELECT common_name, scientific FROM detections WHERE id = ?", (detection_id,)
        ).fetchone()
        self.assertEqual(tuple(stored), ("Blue Jay", "Cyanocitta cristata"))

    def test_unknown_correction_is_rejected_and_null_clears_correction(self) -> None:
        detection_id = self.add_detection()
        with self.assertRaises(queries.InvalidCorrection):
            queries.patch_detection(
                self.conn, detection_id, {"correction": "Invented Finch"}, self.catalog
            )
        queries.patch_detection(
            self.conn,
            detection_id,
            {"correction": "Northern Cardinal"},
            self.catalog,
        )

        restored = queries.patch_detection(
            self.conn, detection_id, {"correction": None}, self.catalog
        )

        self.assertFalse(restored["corrected"])
        self.assertEqual(restored["effective_species"], restored["original_species"])

    def test_exclusion_hides_visit_but_restoration_recovers_favorite(self) -> None:
        detection_id = self.add_detection()
        queries.patch_detection(
            self.conn, detection_id, {"favorite": True}, self.catalog
        )
        now = datetime(2026, 7, 13, 18, tzinfo=timezone.utc)

        queries.patch_detection(
            self.conn, detection_id, {"excluded": True}, self.catalog
        )
        with mock.patch.object(queries, "_utc_now", return_value=now):
            self.assertEqual(
                queries.today(self.conn, "America/New_York")["visits_today"], 0
            )
        self.assertEqual(
            queries.detections(
                self.conn,
                cursor=None,
                limit=20,
                species_key=None,
                favorite=True,
                local_date=None,
                tz_name="America/New_York",
            )["detections"],
            [],
        )

        restored = queries.patch_detection(
            self.conn, detection_id, {"excluded": False}, self.catalog
        )
        with mock.patch.object(queries, "_utc_now", return_value=now):
            self.assertEqual(
                queries.today(self.conn, "America/New_York")["visits_today"], 1
            )
        self.assertTrue(restored["favorite"])

    def test_correction_drives_species_counts_and_shared_opened_state(self) -> None:
        detection_id = self.add_detection()
        queries.patch_detection(
            self.conn,
            detection_id,
            {"correction": "Northern Cardinal"},
            self.catalog,
        )

        collection = queries.species(self.conn, query="", sort="newest")

        self.assertEqual(len(collection["species"]), 1)
        album = collection["species"][0]
        self.assertEqual(album["common_name"], "Northern Cardinal")
        self.assertEqual(album["visits"], 1)
        self.assertTrue(album["is_new"])
        self.assertTrue(queries.mark_species_opened(self.conn, album["species_key"]))
        self.assertFalse(
            queries.species(self.conn, query="", sort="newest")["species"][0][
                "is_new"
            ]
        )

    def test_species_collection_limit_bounds_rows_in_sql(self) -> None:
        for index in range(6):
            self.add_detection(
                common=f"Bird {index}",
                scientific=f"Avis {index}",
                captured_at=f"2026-07-13T{index:02d}:00:00Z",
            )
        statements: list[str] = []
        self.conn.set_trace_callback(statements.append)
        try:
            self.assertIn("limit", inspect.signature(queries.species).parameters)
            collection = queries.species(
                self.conn, query="", sort="newest", limit=3
            )
        finally:
            self.conn.set_trace_callback(None)

        bounded_queries = [
            statement
            for statement in statements
            if "GROUP BY" in statement and "LIMIT 3" in statement
        ]
        self.assertEqual(len(collection["species"]), 3)
        self.assertTrue(bounded_queries)
        self.assertLess(
            bounded_queries[-1].rindex("GROUP BY"),
            bounded_queries[-1].rindex("LIMIT 3"),
        )

    def test_species_limit_is_applied_after_complete_album_aggregation(self) -> None:
        self.add_detection(
            common="American Robin",
            scientific="Turdus migratorius",
            captured_at="2026-01-01T12:00:00Z",
        )
        oldest_blue_id = self.add_detection(
            captured_at="2026-02-01T12:00:00Z"
        )
        queries.patch_detection(
            self.conn, oldest_blue_id, {"favorite": True}, self.catalog
        )
        for index in range(101):
            self.add_detection(
                captured_at=(
                    f"2026-07-{13 + index // 24:02d}T{index % 24:02d}:00:00Z"
                )
            )

        collection = queries.species(
            self.conn, query="", sort="recent", limit=2
        )
        searched = queries.species(
            self.conn, query="robin", sort="recent", limit=1
        )

        self.assertEqual(len(collection["species"]), 2)
        blue_jay = collection["species"][0]
        self.assertEqual(blue_jay["common_name"], "Blue Jay")
        self.assertEqual(blue_jay["visits"], 102)
        self.assertEqual(blue_jay["first_seen"], "2026-02-01T12:00:00Z")
        self.assertEqual(blue_jay["thumbnail"], f"thumbs/{oldest_blue_id}.jpg")
        self.assertEqual(
            searched["species"][0]["common_name"], "American Robin"
        )
        self.assertEqual(searched["species"][0]["visits"], 1)

    def test_common_only_correction_does_not_retain_original_scientific_name(self) -> None:
        corrected_id = self.add_detection()
        original_id = self.add_detection(
            common="House Sparrow", scientific=None, filename="house-sparrow.mp4"
        )

        corrected = queries.patch_detection(
            self.conn,
            corrected_id,
            {"correction": "House Sparrow"},
            self.catalog,
        )
        collection = queries.species(self.conn, query="sparrow", sort="newest")
        album = collection["species"][0]
        history = queries.detections(
            self.conn,
            cursor=None,
            limit=20,
            species_key="common:house sparrow",
            favorite=None,
            local_date=None,
            tz_name="America/New_York",
        )

        self.assertIsNone(corrected["effective_species"]["scientific"])
        self.assertEqual(corrected["species_key"], "common:house sparrow")
        self.assertEqual(len(collection["species"]), 1)
        self.assertIsNone(album["scientific"])
        self.assertEqual(album["species_key"], "common:house sparrow")
        self.assertEqual(album["visits"], 2)
        self.assertEqual(
            {corrected_id, original_id},
            {item["id"] for item in history["detections"]},
        )

    def test_mark_species_opened_rejects_missing_or_excluded_album(self) -> None:
        detection_id = self.add_detection()
        key = queries.species_key("Blue Jay", "Cyanocitta cristata")
        queries.patch_detection(
            self.conn, detection_id, {"excluded": True}, self.catalog
        )

        self.assertFalse(queries.mark_species_opened(self.conn, key))
        self.assertFalse(queries.mark_species_opened(self.conn, "sci:not present"))

    def test_history_cursor_is_stable_after_newer_insert_and_limit_is_capped(self) -> None:
        for hour in range(105):
            self.add_detection(
                captured_at=f"2026-07-{9 + hour // 24:02d}T{hour % 24:02d}:00:00Z"
            )

        first = queries.detections(
            self.conn,
            cursor=None,
            limit=2,
            species_key=None,
            favorite=None,
            local_date=None,
            tz_name="America/New_York",
        )
        first_ids = [item["id"] for item in first["detections"]]
        self.add_detection(captured_at="2026-07-20T00:00:00Z", filename="new.mp4")
        second = queries.detections(
            self.conn,
            cursor=first["next_cursor"],
            limit=2,
            species_key=None,
            favorite=None,
            local_date=None,
            tz_name="America/New_York",
        )
        capped = queries.detections(
            self.conn,
            cursor=None,
            limit=1000,
            species_key=None,
            favorite=None,
            local_date=None,
            tz_name="America/New_York",
        )

        self.assertTrue(set(first_ids).isdisjoint(item["id"] for item in second["detections"]))
        self.assertEqual(len(capped["detections"]), 100)

    def test_species_history_filters_and_limits_inside_sql(self) -> None:
        for index in range(6):
            self.add_detection(captured_at=f"2026-07-13T{index:02d}:00:00Z")
            self.add_detection(
                common="American Robin",
                scientific="Turdus migratorius",
                captured_at=f"2026-07-12T{index:02d}:00:00Z",
            )
        statements: list[str] = []
        self.conn.set_trace_callback(statements.append)
        try:
            result = queries.detections(
                self.conn,
                cursor=None,
                limit=2,
                species_key="sci:cyanocitta cristata",
                favorite=None,
                local_date=None,
                tz_name="America/New_York",
            )
        finally:
            self.conn.set_trace_callback(None)

        page_queries = [
            statement
            for statement in statements
            if "ORDER BY e.captured_at DESC, e.id DESC" in statement
        ]
        self.assertEqual(len(result["detections"]), 2)
        self.assertIsNotNone(result["next_cursor"])
        self.assertTrue(page_queries)
        self.assertIn("journal_species_key", page_queries[-1])
        self.assertIn("LIMIT 3", page_queries[-1])

    def test_malformed_cursor_is_rejected(self) -> None:
        malformed = [
            "not-json-base64",
            queries._encode_cursor(
                {"captured_at": "2026-07-13T12:00:00Z", "id": 1}
            )
            + "$",
        ]
        for cursor in malformed:
            with self.subTest(cursor=cursor), self.assertRaises(queries.InvalidCursor):
                queries.detections(
                    self.conn,
                    cursor=cursor,
                    limit=20,
                    species_key=None,
                    favorite=None,
                    local_date=None,
                    tz_name="America/New_York",
                )

    def test_cursor_requires_canonical_utc_z_timestamp(self) -> None:
        malformed = [
            queries._encode_cursor({"captured_at": "2026-07-13T12:00:00+00:00", "id": 1}),
            queries._encode_cursor({"captured_at": "2026-07-13T08:00:00-04:00", "id": 1}),
            queries._encode_cursor({"captured_at": "2026-07-13T12:00:00.000Z", "id": 1}),
        ]
        for cursor in malformed:
            with self.subTest(cursor=cursor), self.assertRaises(queries.InvalidCursor):
                queries.detections(
                    self.conn, cursor=cursor, limit=20, species_key=None,
                    favorite=None, local_date=None, tz_name="America/New_York",
                )

    def test_today_and_mark_opened_do_not_materialize_lifetime_rows(self) -> None:
        for index in range(30):
            self.add_detection(captured_at=f"2026-07-{10 + index // 24:02d}T{index % 24:02d}:00:00Z")
        statements: list[str] = []
        self.conn.set_trace_callback(statements.append)
        try:
            summary = queries.today(self.conn, "America/New_York", recent_limit=3)
            key = queries.species_key("Blue Jay", "Cyanocitta cristata")
            self.assertTrue(queries.mark_species_opened(self.conn, key))
        finally:
            self.conn.set_trace_callback(None)

        self.assertEqual(len(summary["recent"]), 3)
        self.assertTrue(summary["has_more"])
        self.assertFalse(any(
            "ORDER BY e.captured_at DESC, e.id DESC" in sql and "LIMIT" not in sql
            for sql in statements
        ))

    def test_local_date_filter_handles_midnight_and_dst_fallback(self) -> None:
        before_midnight = self.add_detection(captured_at="2026-07-13T03:59:59Z")
        at_midnight = self.add_detection(captured_at="2026-07-13T04:00:00Z")
        first_one_thirty = self.add_detection(captured_at="2026-11-01T05:30:00Z")
        second_one_thirty = self.add_detection(captured_at="2026-11-01T06:30:00Z")

        july = queries.detections(
            self.conn,
            cursor=None,
            limit=20,
            species_key=None,
            favorite=None,
            local_date="2026-07-13",
            tz_name="America/New_York",
        )
        fallback = queries.detections(
            self.conn,
            cursor=None,
            limit=20,
            species_key=None,
            favorite=None,
            local_date="2026-11-01",
            tz_name="America/New_York",
        )

        self.assertNotIn(before_midnight, [item["id"] for item in july["detections"]])
        self.assertIn(at_midnight, [item["id"] for item in july["detections"]])
        self.assertEqual(
            {first_one_thirty, second_one_thirty},
            {item["id"] for item in fallback["detections"]},
        )

    def test_today_counts_both_repeated_dst_hours_in_one_bucket(self) -> None:
        self.add_detection(captured_at="2026-11-01T05:30:00Z")
        self.add_detection(captured_at="2026-11-01T06:30:00Z")
        now = datetime(2026, 11, 1, 17, tzinfo=timezone.utc)

        with mock.patch.object(queries, "_utc_now", return_value=now):
            summary = queries.today(self.conn, "America/New_York")

        self.assertEqual(summary["visits_today"], 2)
        self.assertEqual(summary["species_today"], 1)
        self.assertEqual(summary["busiest_hour"], 1)
        self.assertEqual(summary["hourly_activity"][1], 2)

    def test_today_latest_status_uses_lifetime_effective_species_history(self) -> None:
        self.add_detection(captured_at="2026-07-10T14:00:00Z")
        self.add_detection(
            common="Northern Cardinal",
            scientific="Cardinalis cardinalis",
            captured_at="2026-07-11T14:00:00Z",
        )
        self.add_detection(
            common="American Robin",
            scientific="Turdus migratorius",
            captured_at="2026-07-12T14:00:00Z",
        )
        self.add_detection(captured_at="2026-07-13T14:00:00Z")

        summary = queries.today(self.conn, "America/New_York", recent_limit=2)

        self.assertEqual(len(summary["recent"]), 2)
        self.assertNotEqual(
            summary["recent"][1]["species_key"], summary["latest"]["species_key"]
        )
        self.assertIn("is_first_visit", summary["latest"])
        self.assertFalse(summary["latest"]["is_first_visit"])

    def test_species_detail_uses_favorite_cover_and_paginates_gallery(self) -> None:
        older = self.add_detection(captured_at="2026-07-12T14:00:00Z")
        newer = self.add_detection(captured_at="2026-07-13T14:00:00Z")
        queries.patch_detection(self.conn, older, {"favorite": True}, self.catalog)
        key = queries.species_key("Blue Jay", "Cyanocitta cristata")

        detail = queries.species_detail(self.conn, key, cursor=None, limit=1)

        self.assertEqual(detail["visits"], 2)
        self.assertEqual(detail["cover"]["id"], older)
        self.assertEqual(detail["gallery"][0]["id"], newer)
        self.assertIsNotNone(detail["next_cursor"])
        self.assertEqual(detail["busiest_hours"], [10])

    def test_species_detail_filters_and_limits_gallery_inside_sql(self) -> None:
        for index in range(5):
            self.add_detection(captured_at=f"2026-07-13T{index:02d}:00:00Z")
            self.add_detection(
                common="American Robin",
                scientific="Turdus migratorius",
                captured_at=f"2026-07-12T{index:02d}:00:00Z",
            )
        statements: list[str] = []
        self.conn.set_trace_callback(statements.append)
        try:
            detail = queries.species_detail(
                self.conn,
                "sci:cyanocitta cristata",
                cursor=None,
                limit=2,
            )
        finally:
            self.conn.set_trace_callback(None)

        page_queries = [
            statement
            for statement in statements
            if statement.startswith("SELECT * FROM (")
            and "ORDER BY e.captured_at DESC, e.id DESC" in statement
        ]
        self.assertEqual(len(detail["gallery"]), 2)
        self.assertEqual(detail["visits"], 5)
        self.assertIsNotNone(detail["next_cursor"])
        self.assertTrue(page_queries)
        self.assertIn("journal_species_key", page_queries[-1])
        self.assertIn("LIMIT 3", page_queries[-1])

    def test_open_journal_connection_does_not_block_second_wal_writer(self) -> None:
        self.add_detection()
        self.conn.execute("SELECT * FROM detections").fetchall()
        writer = db.connect(self.db_path)
        try:
            clip_id = db.add_clip(
                writer, "wal-writer.mp4", "feeder", "2026-07-13T15:00:00Z"
            )
            db.add_detection(
                writer,
                clip_id,
                "American Robin",
                "Turdus migratorius",
                0.88,
                "2026-07-13T15:00:00Z",
                "thumbs/wal.jpg",
                "images/wal.jpg",
            )
        finally:
            writer.close()

        result = queries.detections(
            self.conn,
            cursor=None,
            limit=20,
            species_key=None,
            favorite=None,
            local_date=None,
            tz_name="America/New_York",
        )
        self.assertEqual(len(result["detections"]), 2)


if __name__ == "__main__":
    unittest.main()
