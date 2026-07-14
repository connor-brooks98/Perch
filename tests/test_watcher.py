from __future__ import annotations

import importlib.util
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest import mock

from PIL import Image

from common import db


ROOT = Path(__file__).resolve().parents[1]


def load_watcher():
    fake_classify = types.ModuleType("classify")
    fake_classify.BirdClassifier = object
    fake_notify = types.ModuleType("common.notify")
    fake_notify.push = lambda *args, **kwargs: None
    fake_notify.failure = lambda *args, **kwargs: None
    fake_notify.heartbeat = lambda *args, **kwargs: None
    with mock.patch.dict(
        sys.modules,
        {"classify": fake_classify, "common.notify": fake_notify},
    ):
        spec = importlib.util.spec_from_file_location(
            "watcher_under_test", ROOT / "classifier" / "watcher.py"
        )
        module = importlib.util.module_from_spec(spec)
        assert spec.loader is not None
        spec.loader.exec_module(module)
        return module


watcher = load_watcher()


class WatcherRecoveryTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.conn = db.connect(self.root / "feeder.sqlite")

    def tearDown(self) -> None:
        self.conn.close()
        self.temporary.cleanup()

    def add_clip(self, filename: str) -> int:
        return db.add_clip(
            self.conn, filename, "feeder", f"2026-07-13T12:00:0{filename[0]}Z"
        )

    def test_one_failed_clip_does_not_prevent_next_clip(self) -> None:
        self.add_clip("1.mp4")
        self.add_clip("2.mp4")
        claimed = db.claim_pending_clips(self.conn, limit=10)
        processed: list[str] = []

        def processor(_clf, conn, clip):
            processed.append(clip["filename"])
            if clip["filename"] == "1.mp4":
                raise RuntimeError("bad video")
            db.mark_clip(conn, clip["id"], "done", "test bird")
            return "test bird"

        species = watcher.process_pending_batch(
            object(), self.conn, claimed, processor=processor
        )

        first = self.conn.execute(
            "SELECT * FROM clips WHERE filename = '1.mp4'"
        ).fetchone()
        second = self.conn.execute(
            "SELECT * FROM clips WHERE filename = '2.mp4'"
        ).fetchone()
        self.assertEqual(processed, ["1.mp4", "2.mp4"])
        self.assertEqual(species, ["test bird"])
        self.assertEqual(first["status"], "pending")
        self.assertEqual(first["note"], "bad video")
        self.assertEqual(second["status"], "done")

    def test_no_extracted_frames_is_retryable(self) -> None:
        clip_id = self.add_clip("3.mp4")
        clip = db.claim_pending_clips(self.conn, limit=1)[0]
        clips_dir = self.root / "clips"
        clips_dir.mkdir()
        (clips_dir / "3.mp4").write_bytes(b"video")

        with (
            mock.patch.object(watcher, "CLIPS_DIR", clips_dir),
            mock.patch.object(watcher, "extract_frames", return_value=[]),
        ):
            with self.assertRaisesRegex(RuntimeError, "no frames extracted"):
                watcher.process_clip(object(), self.conn, clip)

        row = self.conn.execute("SELECT * FROM clips WHERE id = ?", (clip_id,)).fetchone()
        self.assertEqual(row["status"], "processing")

    def test_publish_detection_images_creates_two_atomic_sizes(self) -> None:
        frame = self.root / "source.jpg"
        Image.new("RGB", (2000, 1200), "#67805a").save(frame)
        with mock.patch.object(watcher, "IMAGES_DIR", self.root / "images"), mock.patch.object(
            watcher, "THUMBS_DIR", self.root / "thumbs"
        ):
            display, thumb = watcher.publish_detection_images(frame, 42)
        with Image.open(self.root / display) as large, Image.open(self.root / thumb) as small:
            self.assertLessEqual(large.width, 1280)
            self.assertLessEqual(small.width, 480)
        self.assertEqual(list(self.root.rglob("*.tmp")), [])

    def test_regenerate_json_does_not_delete_old_images(self) -> None:
        old = self.root / "thumbs" / "old.jpg"
        old.parent.mkdir()
        old.write_bytes(b"kept")
        with mock.patch.object(watcher, "WEB_DIR", self.root), mock.patch.object(
            watcher, "DATA_DIR", self.root / "data"
        ), mock.patch.object(watcher, "THUMBS_DIR", old.parent):
            watcher.regenerate_json(self.conn)
        self.assertTrue(old.exists())


if __name__ == "__main__":
    unittest.main()
