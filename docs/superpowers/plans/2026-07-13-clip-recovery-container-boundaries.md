# Clip Recovery and Container Boundaries Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make clip processing restart-safe and retryable while enforcing least-privilege container boundaries.

**Architecture:** SQLite owns a durable clip state machine and the classifier claims work before processing it. Blink publishes downloads through a same-filesystem staging directory, while Compose runs each service as a non-root, capability-free, read-only container on a service-specific network.

**Tech Stack:** Python 3.11, SQLite, unittest, Docker Compose, Caddy, ffmpeg, blinkpy

## Global Constraints

- Preserve the dashboard JSON and detection database contracts.
- Use `MAX_CLIP_ATTEMPTS=3` and `CLIP_RETRY_DELAY=60` as defaults.
- Support one classifier instance.
- Add no new runtime dependencies.
- Preserve unrelated local modifications and do not commit or push.

---

### Task 1: Durable clip lifecycle

**Files:**
- Create: `tests/test_clip_recovery.py`
- Modify: `common/schema.sql`
- Modify: `common/db.py`

**Interfaces:**
- Produces: `claim_pending_clips(conn, limit)`, `recover_processing_clips(conn)`, and `fail_clip(conn, clip_id, attempt_count, error, max_attempts, retry_delay_seconds)`.

- [x] Write tests that create a legacy database, verify additive migration, claim due rows, recover interrupted rows, delay retryable rows, and terminally fail the third attempt.
- [x] Run `python3 -m unittest tests.test_clip_recovery -v`; expect failures because lifecycle columns and helpers do not exist.
- [x] Add lifecycle columns to fresh schema and additive migrations to `connect()`.
- [x] Implement transactional claiming, restart recovery, and exponential retry scheduling.
- [x] Re-run `python3 -m unittest tests.test_clip_recovery -v`; expect all lifecycle tests to pass.

### Task 2: Atomic download publication

**Files:**
- Create: `tests/test_clip_publication.py`
- Create: `common/clip_files.py`
- Modify: `puller/puller.py`

**Interfaces:**
- Produces: `publish_downloaded_clips(incoming_dir, clips_dir)` returning the number of newly published files.
- Consumes: existing `register_new_clips(conn)` after publication.

- [x] Write tests proving only staged MP4s are published, existing final files are preserved, and no temporary file is registered.
- [x] Run `python3 -m unittest tests.test_clip_publication -v`; expect failure because the publication helper is missing.
- [x] Download into a per-poll hidden staging directory, atomically rename new MP4s into the final directory, and leave registration after publication.
- [x] Re-run `python3 -m unittest tests.test_clip_publication -v`; expect all publication tests to pass.

### Task 3: Per-clip recovery in the classifier

**Files:**
- Create: `tests/test_watcher.py`
- Modify: `classifier/watcher.py`
- Modify: `.env.example`

**Interfaces:**
- Consumes: lifecycle helpers from Task 1.
- Produces: `process_pending_batch(clf, conn, clips)` that returns identified species while isolating failures.

- [x] Write tests proving one failing clip is rescheduled without preventing the next clip from being processed and startup recovery makes interrupted clips claimable.
- [x] Run `python3 -m unittest tests.test_watcher -v`; expect failure because batch isolation is missing.
- [x] Raise on frame-extraction failure, claim before processing, catch exceptions per clip, call `fail_clip`, and recover processing rows at startup.
- [x] Add the two retry defaults to `.env.example` and Compose.
- [x] Re-run `python3 -m unittest tests.test_watcher -v`; expect all watcher tests to pass.

### Task 4: Container boundary hardening

**Files:**
- Modify: `tests/test_installation.py`
- Modify: `docker-compose.yml`
- Modify: `docker-compose.cloudflare.yml`
- Modify: `puller/Dockerfile`
- Modify: `classifier/Dockerfile`
- Modify: `web/Dockerfile`

**Interfaces:**
- Produces: rendered Compose services with numeric non-root users, read-only roots, dropped capabilities, no-new-privileges, tmpfs storage, process limits, and separate networks.

- [x] Add Compose contract assertions for every boundary and for tunnel-to-web-only network sharing.
- [x] Run the installation tests; expect the new boundary assertions to fail.
- [x] Add non-root runtime configuration, immutable roots, minimal tmpfs mounts, capability/security restrictions, and isolated networks.
- [x] Set Python bytecode suppression and ensure image contents are readable by the runtime UID.
- [x] Render Compose and re-run installation tests; expect boundary assertions to pass.

### Task 5: Documentation and complete verification

**Files:**
- Modify: `README.md`
- Modify: `Perch_Installation_Guide.md`
- Modify: `scripts/verify-install.sh`

**Interfaces:**
- Documents recovery states, retry configuration, non-root ownership, and commands for inspecting/retrying terminal clips.

- [x] Update user documentation and preflight directory setup for `PUID`/`PGID`.
- [x] Run `python3 -m unittest discover -s tests -v`; expect every test to pass.
- [x] Parse all Python files, validate all shell scripts, render both Compose configurations, and run `git diff --check`.
- [x] Check Docker daemon availability; it was not running, so report that the image build and configured-user smoke checks could not run locally.
- [x] Review `git diff` and `git status` to confirm no unrelated files were overwritten and nothing was committed or pushed.
