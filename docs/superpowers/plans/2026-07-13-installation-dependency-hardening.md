# Installation and Dependency Hardening Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make a fresh Raspberry Pi 5 installation reproducible, reachable on the LAN as documented, safe from Compose bcrypt interpolation, and verifiable before launch.

**Architecture:** Treat Docker Compose as the installation contract. Pass only each service's required settings, mount only its required data directories, constrain binary Python dependencies to compatible major versions, and verify configuration without requiring Blink credentials or a running Docker daemon.

**Tech Stack:** Docker Compose, Python 3.11, TFLite Runtime 2.14, Caddy, POSIX shell, Python `unittest`.

## Global Constraints

- Preserve all pre-existing uncommitted changes.
- Target Raspberry Pi OS Lite 64-bit on Raspberry Pi 5.
- Keep BlinkPy pinned at `0.23.0` during this installation-focused change.
- Keep inference local and retain the existing TFLite model contract.
- Do not require a Docker daemon for static installation-contract tests.

---

### Task 1: Installation contract tests

**Files:**
- Create: `tests/test_installation.py`

**Interfaces:**
- Consumes: repository configuration and the local `docker compose` CLI.
- Produces: a repeatable test command, `python3 -m unittest -v tests.test_installation`.

- [ ] Write tests asserting a LAN port binding, literal bcrypt preservation, per-service secret isolation, least-privilege mounts, NumPy/TensorFlow bounds, required `.dockerignore` entries, and consistent documentation.
- [ ] Run the tests against the current checkout and confirm they fail for the diagnosed reasons.

### Task 2: Reproducible dependencies and containers

**Files:**
- Modify: `classifier/requirements.txt`
- Modify: `puller/requirements.txt`
- Modify: `classifier/Dockerfile`
- Modify: `puller/Dockerfile`
- Create: `.dockerignore`

**Interfaces:**
- Consumes: CPython 3.11 on Debian Bookworm ARM64 and the PyPI TFLite wheel.
- Produces: dependency sets that reject NumPy 2 and TensorFlow versions that remove the used interpreter API.

- [ ] Constrain `numpy` to `<2`, `tensorflow` to `<2.20`, and other libraries below their next major version.
- [ ] Pin the Python image family to `3.11-slim-bookworm` and run `pip check` during builds.
- [ ] Exclude credentials, runtime data, model binaries, VCS data, and caches from Docker build contexts.
- [ ] Run the related contract tests until they pass.

### Task 3: Compose installation boundary

**Files:**
- Modify: `docker-compose.yml`
- Modify: `docker-compose.cloudflare.yml`
- Modify: `.env.example`

**Interfaces:**
- Consumes: the project `.env` file for Compose interpolation.
- Produces: explicit per-service environments and narrowly scoped bind mounts.

- [ ] Replace broad `env_file` injection with explicit required/defaulted variables per service.
- [ ] Publish `8080:8080` so the documented LAN URL works.
- [ ] Restrict the web service to read-only generated web data and keep Blink credentials out of classifier/web containers.
- [ ] Pass the Cloudflare token only to the tunnel container.
- [ ] Document a single-quoted bcrypt hash so `$` remains literal.
- [ ] Run `docker compose config` with a generated safe test environment and confirm no warnings or truncated hash.

### Task 4: Model and installation verification

**Files:**
- Create: `scripts/download-model.sh`
- Create: `scripts/verify-install.sh`
- Modify: `classifier/model/README.md`
- Modify: `README.md`
- Modify: `Perch_Installation_Guide.md`

**Interfaces:**
- Consumes: the two Google Coral artifacts and their pinned SHA-256 digests.
- Produces: verified `classifier/model/model.tflite`, verified `classifier/model/labels.txt`, and an operator-facing preflight command.

- [ ] Download both model artifacts to temporary files, verify SHA-256, then rename atomically.
- [ ] Add a preflight script that checks required commands/files/settings, validates Compose, and optionally builds images when the daemon is available.
- [ ] Replace direct unverified model downloads with the helper script.
- [ ] State that the current puller supports Blink cloud clips and therefore requires a subscription until Sync Module local-manifest downloading is implemented.
- [ ] Align LAN access and bcrypt instructions in every document.

### Task 5: Full verification

**Files:**
- Test: `tests/test_installation.py`
- Test: `scripts/verify-install.sh`

**Interfaces:**
- Consumes: all artifacts from Tasks 1–4.
- Produces: recorded evidence of static, Compose, dependency-resolution, syntax, and available build checks.

- [ ] Run `python3 -m unittest -v tests.test_installation`.
- [ ] Run `bash -n scripts/*.sh` and Python AST parsing.
- [ ] Run `git diff --check` and inspect the complete diff for unrelated changes.
- [ ] Run the preflight helper against a temporary non-secret `.env`.
- [ ] Resolve ARM64 wheels for TFLite Runtime and NumPy and confirm NumPy stays below 2.
- [ ] Build images if a Docker daemon is available; otherwise report that limitation explicitly.
