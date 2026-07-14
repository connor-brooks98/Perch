"""Load the installed model and perform one synthetic inference."""
from __future__ import annotations

import argparse
import math
import os
import re
import tempfile
from pathlib import Path
from typing import Any, Callable

from PIL import Image


_UNRESOLVED_LABEL = re.compile(r"^class_\d+$")


def _default_classifier() -> type[Any]:
    try:
        from .classify import BirdClassifier
    except ImportError:
        from classify import BirdClassifier
    return BirdClassifier


def run_smoke(
    model_path: str | Path,
    labels_path: str | Path,
    *,
    classifier_factory: Callable[[str | Path, str | Path], Any] | None = None,
) -> Any:
    """Run inference and reject output that cannot prove the bundle is usable."""
    classifier = (classifier_factory or _default_classifier())(model_path, labels_path)

    with tempfile.TemporaryDirectory(prefix="perch-model-smoke-") as temporary:
        image_path = Path(temporary) / "synthetic.jpg"
        Image.new("RGB", (320, 180), (96, 128, 160)).save(image_path, format="JPEG")
        prediction = classifier.classify(image_path)

    if not isinstance(prediction.index, int) or prediction.index < 0:
        raise RuntimeError("Model smoke test returned an invalid class index.")
    if not math.isfinite(float(prediction.confidence)):
        raise RuntimeError("Model smoke test confidence is not finite.")
    label = str(prediction.label).strip()
    if not label or _UNRESOLVED_LABEL.fullmatch(label):
        raise RuntimeError("Model smoke test could not resolve the predicted label.")
    return prediction


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--model",
        default=os.getenv("MODEL_PATH", "/app/model/current/model.tflite"),
    )
    parser.add_argument(
        "--labels",
        default=os.getenv("LABELS_PATH", "/app/model/current/labels.txt"),
    )
    args = parser.parse_args()
    prediction = run_smoke(args.model, args.labels)
    print(
        "Model inference smoke test passed: "
        f"class {prediction.index}, {prediction.label!r}, confidence {prediction.confidence:.6f}"
    )


if __name__ == "__main__":
    main()
