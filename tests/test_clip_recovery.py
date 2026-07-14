from __future__ import annotations

import sqlite3
import tempfile
import unittest
from pathlib import Path

from common import db


class ClipRecoveryTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.db_path = Path(self.temporary.name) / "feeder.sqlite"
        self.connections: list[sqlite3.Connection] = []

    def tearDown(self) -> None:
        for conn in reversed(self.connections):
            conn.close()
        self.connections.clear()
        self.temporary.cleanup()

    def connect(self) -> sqlite3.Connection:
        conn = db.connect(self.db_path)
        self.connections.append(conn)
        return conn

    def test_teardown_closes_connections_created_by_helper(self) -> None:
        case = self.__class__("test_connect_migrates_legacy_clips_table")
        case.setUp()
        conn = case.connect()
        case.tearDown()

        with self.assertRaises(sqlite3.ProgrammingError):
            conn.execute("SELECT 1")

    def add_clip(self, conn, filename: str = "clip.mp4") -> int:
        return db.add_clip(conn, filename, "feeder", "2026-07-13T12:00:00Z")

    def test_connect_migrates_legacy_clips_table(self) -> None:
        legacy = sqlite3.connect(self.db_path)
        legacy.execute(
            "CREATE TABLE clips ("
            "id INTEGER PRIMARY KEY AUTOINCREMENT, filename TEXT NOT NULL UNIQUE, "
            "camera TEXT, captured_at TEXT NOT NULL, pulled_at TEXT NOT NULL, "
            "status TEXT NOT NULL DEFAULT 'pending', note TEXT)"
        )
        legacy.commit()
        legacy.close()

        conn = self.connect()
        columns = {row["name"] for row in conn.execute("PRAGMA table_info(clips)")}

        self.assertTrue(
            {"attempt_count", "next_attempt_at", "processing_started_at"} <= columns
        )

    def test_claim_marks_due_clips_processing_and_increments_attempt(self) -> None:
        conn = self.connect()
        clip_id = self.add_clip(conn)

        claimed = db.claim_pending_clips(conn, limit=10)

        self.assertEqual([row["id"] for row in claimed], [clip_id])
        self.assertEqual(claimed[0]["status"], "processing")
        self.assertEqual(claimed[0]["attempt_count"], 1)
        self.assertIsNotNone(claimed[0]["processing_started_at"])
        self.assertEqual(db.claim_pending_clips(conn, limit=10), [])

    def test_claim_ignores_retry_scheduled_for_the_future(self) -> None:
        conn = self.connect()
        clip_id = self.add_clip(conn)
        conn.execute(
            "UPDATE clips SET next_attempt_at = '2999-01-01T00:00:00Z' WHERE id = ?",
            (clip_id,),
        )
        conn.commit()

        self.assertEqual(db.claim_pending_clips(conn, limit=10), [])

    def test_recover_processing_clips_makes_interrupted_work_claimable(self) -> None:
        conn = self.connect()
        self.add_clip(conn)
        db.claim_pending_clips(conn, limit=10)

        recovered = db.recover_processing_clips(conn)
        claimed_again = db.claim_pending_clips(conn, limit=10)

        self.assertEqual(recovered, 1)
        self.assertEqual(len(claimed_again), 1)
        self.assertEqual(claimed_again[0]["attempt_count"], 2)

    def test_failed_clip_is_delayed_before_retry(self) -> None:
        conn = self.connect()
        self.add_clip(conn)
        clip = db.claim_pending_clips(conn, limit=1)[0]

        terminal = db.fail_clip(
            conn,
            clip["id"],
            clip["attempt_count"],
            "decoder failed",
            max_attempts=3,
            retry_delay_seconds=60,
        )
        row = conn.execute("SELECT * FROM clips WHERE id = ?", (clip["id"],)).fetchone()

        self.assertFalse(terminal)
        self.assertEqual(row["status"], "pending")
        self.assertEqual(row["note"], "decoder failed")
        self.assertIsNotNone(row["next_attempt_at"])
        self.assertIsNone(row["processing_started_at"])
        self.assertEqual(db.claim_pending_clips(conn, limit=1), [])

    def test_third_failed_attempt_becomes_terminal_error(self) -> None:
        conn = self.connect()
        clip_id = self.add_clip(conn)

        terminal = db.fail_clip(
            conn,
            clip_id,
            attempt_count=3,
            error="decoder failed",
            max_attempts=3,
            retry_delay_seconds=60,
        )
        row = conn.execute("SELECT * FROM clips WHERE id = ?", (clip_id,)).fetchone()

        self.assertTrue(terminal)
        self.assertEqual(row["status"], "error")
        self.assertIsNone(row["next_attempt_at"])


if __name__ == "__main__":
    unittest.main()
