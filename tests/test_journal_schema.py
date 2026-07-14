from __future__ import annotations

import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from common import db


OLD_SCHEMA = """
CREATE TABLE clips (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    filename TEXT NOT NULL UNIQUE,
    camera TEXT,
    captured_at TEXT NOT NULL,
    pulled_at TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending',
    note TEXT
);

CREATE TABLE detections (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    clip_id INTEGER NOT NULL REFERENCES clips(id) ON DELETE CASCADE,
    common_name TEXT NOT NULL,
    scientific TEXT,
    confidence REAL NOT NULL,
    captured_at TEXT NOT NULL,
    thumbnail TEXT NOT NULL,
    created_at TEXT NOT NULL
);
"""


class JournalSchemaTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.connections: list[sqlite3.Connection] = []

    def tearDown(self) -> None:
        for conn in reversed(self.connections):
            conn.close()
        self.temporary.cleanup()

    def connect(self, path: Path) -> sqlite3.Connection:
        conn = db.connect(path)
        self.connections.append(conn)
        return conn

    def test_old_detection_database_migrates_without_rewriting_prediction(self) -> None:
        path = self.root / "old.sqlite"
        conn = sqlite3.connect(path)
        conn.executescript(OLD_SCHEMA)
        conn.execute(
            "INSERT INTO clips(id, filename, captured_at, pulled_at) "
            "VALUES(1,'one.mp4','2026-07-13T12:00:00Z','2026-07-13T12:01:00Z')"
        )
        conn.execute(
            "INSERT INTO detections(clip_id,common_name,scientific,confidence,"
            "captured_at,thumbnail,created_at) "
            "VALUES(1,'Blue Jay','Cyanocitta cristata',.91,"
            "'2026-07-13T12:00:00Z','thumbs/1.jpg','2026-07-13T12:02:00Z')"
        )
        conn.commit()
        conn.close()

        db.initialize(path)
        migrated = self.connect(path)
        row = migrated.execute("SELECT * FROM detections").fetchone()

        self.assertEqual(row["common_name"], "Blue Jay")
        self.assertEqual(row["display_image"], "thumbs/1.jpg")
        self.assertEqual(
            migrated.execute(
                "SELECT COUNT(*) n FROM detection_annotations"
            ).fetchone()["n"],
            0,
        )

    def test_migration_is_repeatable(self) -> None:
        path = self.root / "feeder.sqlite"
        db.initialize(path)
        first = self.connect(path)
        first.close()
        self.connections.remove(first)

        db.initialize(path)
        second = self.connect(path)

        self.assertEqual(second.execute("PRAGMA foreign_key_check").fetchall(), [])

    def test_runtime_connect_does_not_rerun_schema_or_migrations(self) -> None:
        path = self.root / "feeder.sqlite"
        db.initialize(path)
        with mock.patch("pathlib.Path.read_text", side_effect=AssertionError("schema rerun")):
            conn = self.connect(path)
            self.assertEqual(conn.execute("SELECT 1").fetchone()[0], 1)

    def test_initialization_failure_closes_its_connection(self) -> None:
        path = self.root / "broken.sqlite"
        connection = sqlite3.connect(path)
        connection.row_factory = sqlite3.Row
        with mock.patch("common.db._open", return_value=connection), mock.patch(
            "common.db._migrate_clips", side_effect=RuntimeError("migration failed")
        ):
            with self.assertRaisesRegex(RuntimeError, "migration failed"):
                db.initialize(path)
        with self.assertRaises(sqlite3.ProgrammingError):
            connection.execute("SELECT 1")


if __name__ == "__main__":
    unittest.main()
