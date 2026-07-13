from __future__ import annotations

import math
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from classifier.smoke_model import run_smoke


class FakeClassifier:
    prediction = SimpleNamespace(index=1, label="Fixture bird", confidence=0.75)
    received_image: Path | None = None

    def __init__(self, model_path: str | Path, labels_path: str | Path):
        self.model_path = Path(model_path)
        self.labels_path = Path(labels_path)

    def classify(self, image_path: str | Path) -> SimpleNamespace:
        type(self).received_image = Path(image_path)
        return type(self).prediction


class ModelSmokeTests(unittest.TestCase):
    def setUp(self) -> None:
        FakeClassifier.prediction = SimpleNamespace(
            index=1,
            label="Fixture bird",
            confidence=0.75,
        )
        FakeClassifier.received_image = None

    def test_smoke_creates_an_image_and_accepts_a_finite_resolved_prediction(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            model = root / "model.tflite"
            labels = root / "labels.txt"
            model.write_bytes(b"fixture")
            labels.write_text("0 background\n1 Fixture bird\n", encoding="utf-8")

            prediction = run_smoke(model, labels, classifier_factory=FakeClassifier)

        self.assertEqual(prediction.index, 1)
        self.assertTrue(math.isfinite(prediction.confidence))
        self.assertIsNotNone(FakeClassifier.received_image)

    def test_smoke_rejects_non_finite_confidence(self) -> None:
        FakeClassifier.prediction = SimpleNamespace(index=1, label="Fixture bird", confidence=math.nan)

        with self.assertRaisesRegex(RuntimeError, "finite"):
            run_smoke("model.tflite", "labels.txt", classifier_factory=FakeClassifier)

    def test_smoke_rejects_a_label_that_did_not_resolve(self) -> None:
        FakeClassifier.prediction = SimpleNamespace(index=4, label="class_4", confidence=0.2)

        with self.assertRaisesRegex(RuntimeError, "label"):
            run_smoke("model.tflite", "labels.txt", classifier_factory=FakeClassifier)


if __name__ == "__main__":
    unittest.main()
