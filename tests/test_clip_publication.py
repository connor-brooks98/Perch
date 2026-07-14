from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from common.clip_files import publish_downloaded_clips


class ClipPublicationTests(unittest.TestCase):
    def test_publishes_only_mp4_files(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            incoming = root / ".incoming"
            clips = root / "clips"
            incoming.mkdir()
            clips.mkdir()
            (incoming / "complete.mp4").write_bytes(b"complete")
            (incoming / "partial.tmp").write_bytes(b"partial")

            published = publish_downloaded_clips(incoming, clips)

            self.assertEqual(published, 1)
            self.assertEqual((clips / "complete.mp4").read_bytes(), b"complete")
            self.assertFalse((incoming / "complete.mp4").exists())
            self.assertTrue((incoming / "partial.tmp").exists())

    def test_existing_final_clip_is_never_replaced(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            incoming = root / ".incoming"
            clips = root / "clips"
            incoming.mkdir()
            clips.mkdir()
            (incoming / "same.mp4").write_bytes(b"new")
            (clips / "same.mp4").write_bytes(b"known-good")

            published = publish_downloaded_clips(incoming, clips)

            self.assertEqual(published, 0)
            self.assertEqual((clips / "same.mp4").read_bytes(), b"known-good")
            self.assertFalse((incoming / "same.mp4").exists())


if __name__ == "__main__":
    unittest.main()
