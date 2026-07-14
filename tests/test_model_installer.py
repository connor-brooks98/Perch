from __future__ import annotations

import hashlib
import os
import subprocess
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
INSTALLER = ROOT / "scripts" / "download-model.sh"


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


class ModelInstallerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.source = self.root / "source"
        self.target = self.root / "model"
        self.source.mkdir()
        (self.source / "model.tflite").write_bytes(b"new-model-fixture")
        (self.source / "labels.txt").write_text(
            "0 background\n1 Test bird (Fixture bird)\n",
            encoding="utf-8",
        )

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def run_installer(self, *, fail_after_backup: bool = False) -> subprocess.CompletedProcess[str]:
        environment = os.environ.copy()
        environment.update(
            {
                "PERCH_MODEL_SOURCE_DIR": str(self.source),
                "PERCH_MODEL_SHA256": sha256(self.source / "model.tflite"),
                "PERCH_LABELS_SHA256": sha256(self.source / "labels.txt"),
            }
        )
        if fail_after_backup:
            environment["PERCH_MODEL_INSTALL_FAIL_AFTER_BACKUP"] = "1"
        return subprocess.run(
            [str(INSTALLER), str(self.target)],
            cwd=ROOT,
            env=environment,
            capture_output=True,
            text=True,
            check=False,
        )

    def assert_no_transaction_debris(self) -> None:
        names = {path.name for path in self.target.iterdir()}
        self.assertFalse(any(name.startswith(".download.") for name in names), names)
        self.assertFalse(any(name.startswith(".backup.") for name in names), names)

    def test_installs_verified_model_and_labels_as_one_current_bundle(self) -> None:
        result = self.run_installer()

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(
            (self.target / "current" / "model.tflite").read_bytes(),
            (self.source / "model.tflite").read_bytes(),
        )
        self.assertEqual(
            (self.target / "current" / "labels.txt").read_bytes(),
            (self.source / "labels.txt").read_bytes(),
        )
        self.assert_no_transaction_debris()

    def test_failure_after_backup_restores_the_entire_previous_bundle(self) -> None:
        current = self.target / "current"
        current.mkdir(parents=True)
        (current / "model.tflite").write_bytes(b"old-model")
        (current / "labels.txt").write_text("0 old-label\n", encoding="utf-8")

        result = self.run_installer(fail_after_backup=True)

        self.assertNotEqual(result.returncode, 0)
        self.assertEqual((current / "model.tflite").read_bytes(), b"old-model")
        self.assertEqual((current / "labels.txt").read_text(encoding="utf-8"), "0 old-label\n")
        self.assert_no_transaction_debris()


if __name__ == "__main__":
    unittest.main()
