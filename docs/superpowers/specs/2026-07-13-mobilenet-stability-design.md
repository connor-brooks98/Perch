# MobileNet Stability Design

## Goal

Ship MobileNetV2 as Perch's only supported production inference runtime while closing the remaining preprocessing, model-installation, and preflight gaps. ONNX remains a documented future experiment and adds no dependency or runtime path in this release.

## Preprocessing contract

The existing classifier continues to derive its input dimensions and dtype from the TFLite interpreter. RGB inputs are resized with aspect ratio preserved, centered on a black canvas at the exact model dimensions, and use Pillow bicubic interpolation. Quantized inputs remain NHWC values in their interpreter dtype; float32 inputs use the existing `[-1, 1]` normalization.

Tests construct classifier instances without loading TensorFlow/TFLite and verify horizontal and vertical letterboxing, black padding, exact tensor shape, quantized dtype, and float normalization. These are regression tests for behavior already present locally.

## Model bundle installation

The model and labels are treated as one versioned bundle rather than two unrelated files. The download helper creates a sibling staging directory, downloads both artifacts there, verifies their pinned SHA-256 checksums, checks that labels contain meaningful non-empty entries, and then installs the staged directory as `classifier/model/current`.

If `current` already exists, it is renamed to a sibling backup before the staged directory is promoted. Any promotion failure restores the backup. A successful promotion removes the backup. The tracked `classifier/model/README.md` remains outside the mutable bundle. Compose and classifier defaults read `/app/model/current/model.tflite` and `/app/model/current/labels.txt`.

The downloader supports an internal test hook that forces failure after the backup rename, allowing the rollback path to be verified without relying on filesystem races.

## Runtime preflight

After building images, `verify-install.sh --build` runs a classifier-container smoke command. The command loads the installed TFLite model, creates a synthetic RGB image, performs one prediction, and confirms the returned index and confidence are finite and the selected label resolves. This catches corrupt models, mismatched labels, unavailable interpreter wheels, unreadable mounts, and incompatible tensor assumptions before launch.

The smoke check is implemented as `classifier/smoke_model.py` so it is independently unit-testable and avoids a fragile shell one-liner.

## Documentation and ONNX boundary

README, installation instructions, and the model README identify MobileNetV2 as the supported stable runtime. ONNX is described only as a future experimental milestone requiring bird-crop evaluation, a model-neutral inference interface, an isolated dependency/image path, and physical Pi 5 benchmarks. No ONNX package, setting, model URL, or dormant code path is added now.

## Acceptance criteria

- Letterbox behavior is covered for wide and tall images.
- Quantized and float preprocessing contracts are covered.
- A failed bundle promotion leaves the previous complete bundle intact.
- A successful bundle install leaves a complete `current` directory and no backup/staging directories.
- Preflight performs real model loading and inference when Docker is available.
- Existing installation, recovery, Compose, and documentation tests remain green.
- No ONNX runtime dependency enters the stable classifier image.
- Work remains local and uncommitted.
