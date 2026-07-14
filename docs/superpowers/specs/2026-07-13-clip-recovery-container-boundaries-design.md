# Clip Recovery and Container Boundaries Design

## Goal

Make clip ingestion and classification recover automatically from partial downloads, per-clip failures, and classifier restarts while limiting the damage a compromised container can cause.

## Clip lifecycle

Clips use five active/terminal states: `pending`, `processing`, `done`, `error`, and `skipped`. The database records `attempt_count`, `next_attempt_at`, and `processing_started_at`. The classifier atomically claims due pending clips by changing them to `processing` and incrementing their attempt count before inference begins.

On classifier startup, any rows left in `processing` are returned to `pending` immediately because only one classifier instance is supported. An expected absence of the source file remains terminal `skipped`. Frame extraction, image decoding, inference, thumbnail, and database failures are retryable. Failed attempts return to `pending` with exponential delay; the third failed attempt becomes terminal `error`. A failure is handled around one clip so the rest of the claimed batch continues.

Existing databases are migrated in place by inspecting `PRAGMA table_info(clips)` and adding missing lifecycle columns. Fresh databases receive the same columns from `schema.sql`.

## Download publication

Blink downloads into a fresh hidden directory under `/data/clips` for each poll. After `download_videos` returns successfully, each completed MP4 is atomically renamed into `/data/clips`, then the published directory is registered in SQLite. The staging directory and final directory reside on the same bind mount, so rename is atomic. A failed poll removes its entire private staging directory, and a staged file whose final filename already exists is discarded without replacing the known clip.

## Container isolation

All services run as `${PUID:-1000}:${PGID:-1000}` with a read-only root filesystem, all Linux capabilities dropped, `no-new-privileges`, and bounded process counts. Python receives a small executable `/tmp` tmpfs for ffmpeg and temporary frames; Caddy receives tmpfs storage for its runtime data and configuration.

Puller, classifier, and web use separate bridge networks. The optional Cloudflare tunnel shares only the web network. Bind mounts remain limited by responsibility: puller writes credentials, staging/final clips, and SQLite; classifier reads clips/model and writes SQLite/dashboard data; web reads dashboard data only.

## Configuration and operations

`MAX_CLIP_ATTEMPTS=3` and `CLIP_RETRY_DELAY=60` are exposed in `.env.example`. `PUID=1000` and `PGID=1000` document the expected host ownership. The preflight creates required directories and rejects data directories that are not writable by the configured host identity through a short container check when images are available.

## Tests

Database tests cover migration, atomic claiming, restart recovery, delayed retry, and terminal failure. Puller tests cover staged publication without exposing partial MP4s. Watcher tests cover per-clip failure isolation. Installation contract tests inspect rendered Compose output for non-root users, read-only roots, dropped capabilities, `no-new-privileges`, tmpfs mounts, narrow bind mounts, and network separation.

## Constraints

- Preserve the current dashboard and detection schema contract.
- Support Python 3.11 and SQLite bundled with the pinned Python image.
- Support one classifier instance; multi-worker leases are outside this change.
- Do not add a broker, migration framework, or new runtime dependency.
- Keep all changes local and uncommitted until the owner chooses to publish them.
