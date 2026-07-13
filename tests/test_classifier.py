from __future__ import annotations

import importlib
import sys
import types
import unittest
from unittest import mock

import numpy as np
from PIL import Image


# The host test environment does not need a native TFLite wheel to exercise
# preprocessing. Supply the import surface classify.py expects before loading it.
if "tflite_runtime.interpreter" not in sys.modules:
    runtime = types.ModuleType("tflite_runtime")
    interpreter = types.ModuleType("tflite_runtime.interpreter")
    interpreter.Interpreter = object
    runtime.interpreter = interpreter
    sys.modules["tflite_runtime"] = runtime
    sys.modules["tflite_runtime.interpreter"] = interpreter

classify = importlib.import_module("classifier.classify")
BirdClassifier = classify.BirdClassifier


def classifier_with_dtype(dtype: type[np.generic]) -> BirdClassifier:
    classifier = object.__new__(BirdClassifier)
    classifier.width = 224
    classifier.height = 224
    classifier.inp = {"dtype": dtype}
    return classifier


class ClassifierPreprocessingTests(unittest.TestCase):
    def test_wide_image_is_centered_with_black_horizontal_padding(self) -> None:
        classifier = classifier_with_dtype(np.uint8)
        image = Image.new("RGB", (400, 200), (20, 40, 60))

        result = np.asarray(classifier._letterbox(image))

        self.assertEqual(result.shape, (224, 224, 3))
        self.assertTrue(np.all(result[:56] == 0))
        self.assertTrue(np.all(result[168:] == 0))
        self.assertTrue(np.all(result[56:168] == (20, 40, 60)))

    def test_tall_image_is_centered_with_black_vertical_padding(self) -> None:
        classifier = classifier_with_dtype(np.uint8)
        image = Image.new("RGB", (200, 400), (60, 40, 20))

        result = np.asarray(classifier._letterbox(image))

        self.assertEqual(result.shape, (224, 224, 3))
        self.assertTrue(np.all(result[:, :56] == 0))
        self.assertTrue(np.all(result[:, 168:] == 0))
        self.assertTrue(np.all(result[:, 56:168] == (60, 40, 20)))

    def test_letterbox_uses_bicubic_interpolation(self) -> None:
        classifier = classifier_with_dtype(np.uint8)
        image = Image.new("RGB", (400, 200), "white")
        original_resize = Image.Image.resize

        with mock.patch.object(
            Image.Image,
            "resize",
            autospec=True,
            side_effect=original_resize,
        ) as resize:
            classifier._letterbox(image)

        self.assertEqual(resize.call_args.args[1:], ((224, 112), Image.Resampling.BICUBIC))

    def test_quantized_preprocessing_returns_batched_uint8_tensor(self) -> None:
        classifier = classifier_with_dtype(np.uint8)

        result = classifier._preprocess(Image.new("RGB", (320, 180), "white"))

        self.assertEqual(result.shape, (1, 224, 224, 3))
        self.assertEqual(result.dtype, np.uint8)
        self.assertEqual(int(result[0, 112, 112, 0]), 255)
        self.assertEqual(int(result[0, 0, 0, 0]), 0)

    def test_float_preprocessing_normalizes_pixels_to_minus_one_through_one(self) -> None:
        classifier = classifier_with_dtype(np.float32)

        black = classifier._preprocess(Image.new("RGB", (224, 224), "black"))
        white = classifier._preprocess(Image.new("RGB", (224, 224), "white"))

        self.assertEqual(black.dtype, np.float32)
        self.assertEqual(white.dtype, np.float32)
        self.assertTrue(np.all(black == -1.0))
        self.assertTrue(np.all(white == 1.0))


if __name__ == "__main__":
    unittest.main()
