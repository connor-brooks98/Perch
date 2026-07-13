# MobileNet Stability Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the existing MobileNetV2 path fully regression-tested, bundle-safe to install, and validated by real container inference before launch.

**Architecture:** Keep one production TFLite backend. Store mutable model artifacts in a versioned `current` bundle promoted with backup/rollback semantics, and validate that bundle through a small classifier smoke program during build preflight.

**Tech Stack:** Python 3.11, unittest, Pillow, NumPy, TFLite Runtime, Bash, Docker Compose

## Global Constraints

- MobileNetV2 remains the only supported production runtime.
- Preserve letterbox plus bicubic preprocessing and black padding.
- Preserve quantized NHWC and float32 `[-1, 1]` tensor behavior.
- Add no ONNX dependency or runtime code path.
- Preserve unrelated local changes; do not commit or push.

---

### Task 1: MobileNet preprocessing regression coverage

**Files:**
- Create: `tests/test_classifier.py`
- Modify only if a regression is exposed: `classifier/classify.py`

**Interfaces:**
- Consumes: `BirdClassifier._letterbox(image, padding_color=0)` and `BirdClassifier._preprocess(image)`.
- Produces: executable contracts for geometry, padding, tensor shape, dtype, and normalization.

- [x] Write tests for wide/tall letterboxing, exact output geometry, black padding, quantized tensors, and float32 normalization.
- [x] Temporarily replace bicubic or letterbox behavior in-memory through test patching so each regression assertion is observed failing for the intended reason.
- [x] Restore production behavior and run `python3 -m unittest tests.test_classifier -v`; expect every preprocessing test to pass.

### Task 2: Transactional model bundle installer

**Files:**
- Create: `tests/test_model_installer.py`
- Modify: `scripts/download-model.sh`
- Modify: `classifier/model/README.md`
- Modify: `docker-compose.yml`

**Interfaces:**
- Produces: `classifier/model/current/model.tflite` and `classifier/model/current/labels.txt` as one promoted bundle.
- Consumes: optional `PERCH_MODEL_SOURCE_DIR` for offline fixture copies and `PERCH_MODEL_INSTALL_FAIL_AFTER_BACKUP=1` for rollback testing.

- [x] Write subprocess tests using local fixture artifacts and computed test checksums to verify successful promotion, cleanup, and rollback to an existing bundle.
- [x] Run `python3 -m unittest tests.test_model_installer -v`; expect failure because the current helper installs two files directly.
- [x] Refactor the helper to stage a sibling directory, verify both files and labels, back up `current`, promote the bundle, roll back on failure, and clean temporary paths.
- [x] Point Compose and model documentation at `/app/model/current/...`.
- [x] Re-run the installer tests; expect all success and rollback cases to pass.

### Task 3: Real classifier model smoke check

**Files:**
- Create: `classifier/smoke_model.py`
- Create: `tests/test_model_smoke.py`
- Modify: `scripts/verify-install.sh`

**Interfaces:**
- Produces: `smoke_model.run(model_path, labels_path) -> Prediction` and a zero-exit CLI on successful finite inference.
- Consumes: the normal `BirdClassifier` and the installed current bundle.

- [x] Write a unit test with a fake classifier proving the smoke validator rejects non-finite confidence and accepts a finite resolved prediction.
- [x] Run `python3 -m unittest tests.test_model_smoke -v`; expect failure because the smoke module is missing.
- [x] Implement the smoke validator and CLI using a generated RGB image in a temporary directory.
- [x] Add the classifier-container invocation to the `--build` section of preflight.
- [x] Re-run smoke and installation contract tests; expect them to pass.

### Task 4: Stable-runtime documentation and complete verification

**Files:**
- Modify: `README.md`
- Modify: `Perch_Installation_Guide.md`
- Modify: `tests/test_installation.py`

**Interfaces:**
- Documents MobileNetV2 as stable and ONNX as a future isolated experiment.

- [x] Add documentation contract assertions for the stable runtime, experimental ONNX boundary, new current bundle path, and model smoke command.
- [x] Run the assertions and observe them fail before updating documentation.
- [x] Update all setup and model paths plus the future ONNX prerequisites without advertising ONNX as installable.
- [x] Run the full unit suite, Python parsing, shell parsing, base/Cloudflare Compose rendering, and diff checks.
- [x] If Docker is running, execute `./scripts/verify-install.sh --build`; otherwise report that build and real inference limitation explicitly.
- [x] Review status to confirm no commit or push occurred and no unrelated local changes were overwritten.
