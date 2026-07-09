"""Local bird classifier (Phase 3).

Wraps the AIY/Coral iNaturalist-birds MobileNet-v2 TFLite model. Preprocessing
mirrors whosatmyfeeder: resize to the model's input size, feed quantized uint8,
dequantize the output to real probabilities.

Model files are NOT bundled. Drop these two into classifier/model/ (see the
README there):
    model/model.tflite    — the quantized iNat bird classifier
    model/labels.txt      — matching labels, one per line
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

import numpy as np
from PIL import Image

try:  # the lightweight runtime we install on the Pi
    from tflite_runtime.interpreter import Interpreter
except ImportError:  # fallback so the module imports anywhere for testing
    from tensorflow.lite import Interpreter  # type: ignore

_PAREN_RE = re.compile(r"^(.*?)\s*\((.*)\)\s*$")
_INDEX_PREFIX_RE = re.compile(r"^\s*(\d+)[\s,]+(.*)$")


@dataclass
class Prediction:
    index: int
    label: str          # raw label text
    common_name: str
    scientific: str | None
    confidence: float

    @property
    def is_bird(self) -> bool:
        return "background" not in self.label.lower() and self.label.strip() != ""


def _split_label(raw: str) -> tuple[str, str | None]:
    """Coral labels read 'Scientific name (Common Name)'. Return (common, sci)."""
    m = _PAREN_RE.match(raw)
    if m:
        scientific, common = m.group(1).strip(), m.group(2).strip()
        return (common or raw, scientific or None)
    return (raw, None)


class BirdClassifier:
    def __init__(self, model_path: str | Path, labels_path: str | Path):
        model_path, labels_path = Path(model_path), Path(labels_path)
        if not model_path.exists() or not labels_path.exists():
            raise FileNotFoundError(
                "Missing model files. Expected:\n"
                f"  {model_path}\n  {labels_path}\n"
                "See classifier/model/README.md for where to get them."
            )
        self.interp = Interpreter(model_path=str(model_path))
        self.interp.allocate_tensors()
        self.inp = self.interp.get_input_details()[0]
        self.out = self.interp.get_output_details()[0]
        _, self.height, self.width, _ = self.inp["shape"]
        self.labels = self._load_labels(labels_path)

    @staticmethod
    def _load_labels(path: Path) -> dict[int, str]:
        labels: dict[int, str] = {}
        for i, line in enumerate(path.read_text(encoding="utf-8").splitlines()):
            text = line.strip()
            if not text:
                continue
            m = _INDEX_PREFIX_RE.match(text)
            if m:
                # File carries explicit indices ("964 Cardinalis ..."): trust them,
                # so a blank/missing line can't silently shift every class by one.
                labels[int(m.group(1))] = m.group(2).strip()
            else:
                labels[i] = text
        return labels

    def _preprocess(self, image: Image.Image) -> np.ndarray:
        img = image.convert("RGB").resize((self.width, self.height))
        arr = np.asarray(img)
        if self.inp["dtype"] == np.float32:
            arr = (np.float32(arr) - 127.5) / 127.5
        else:  # quantized uint8 model — feed bytes straight through
            arr = arr.astype(self.inp["dtype"])
        return np.expand_dims(arr, axis=0)

    def classify(self, image_path: str | Path) -> Prediction:
        image = Image.open(image_path)
        self.interp.set_tensor(self.inp["index"], self._preprocess(image))
        self.interp.invoke()
        raw = self.interp.get_tensor(self.out["index"])[0]

        scale, zero_point = self.out.get("quantization", (0.0, 0))
        scores = (scale * (raw.astype(np.float32) - zero_point)) if scale else raw.astype(np.float32)

        idx = int(np.argmax(scores))
        label = self.labels.get(idx, f"class_{idx}")
        common, scientific = _split_label(label)
        return Prediction(idx, label, common, scientific, float(scores[idx]))
