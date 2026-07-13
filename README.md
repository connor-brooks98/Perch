# Smart Bird Feeder — backend

A no-recurring-cost bird-ID pipeline. A stock Blink camera mounted on a bird
feeder records motion clips; a Raspberry Pi 5 pulls those clips, identifies the
bird with a **local** TFLite model (no API, $0 inference), and serves a
login-gated dashboard you can add to a phone's home screen.

```
Blink cloud ──> puller ──> clips volume ──> classifier ──> SQLite + thumbs + JSON ──> web (Caddy) ──> browser
                (blinkpy)                    (ffmpeg + tflite)                          (basic_auth)
```

Everything runs in Docker on the Pi (64-bit). The same compose project moves to
any other 64-bit Linux host (e.g. a mini PC) unchanged.

## What's in here

| Path | Role |
|------|------|
| `puller/` | `blinkpy` clip fetcher + one-time `auth_setup.py` |
| `classifier/` | ffmpeg frame extraction + TFLite inference (`classify.py`, `watcher.py`) |
| `classifier/model/` | verified MobileNetV2 model bundle (see its README) |
| `common/` | shared SQLite schema/helpers + ntfy notifier |
| `web/` | Caddy config + the static field-log dashboard |
| `scripts/backup-db.sh` | nightly SQLite backup |
| `docker-compose.yml` | the three services |
| `docker-compose.cloudflare.yml` | optional Cloudflare Tunnel edge |

---

## Prerequisites

Before setup, make sure you have:

- A **dedicated** Blink account (not your everyday login) with the feeder camera
  added to it.
- An active **Blink subscription** so clips appear in Blink's cloud-media feed.
  Sync Module 2 local-storage downloading uses a different API and is not yet
  implemented by Perch.
- A Raspberry Pi (64-bit; a Pi 5 is ideal) running Raspberry Pi OS Lite 64-bit
  with Docker and Docker Compose installed.

## First-time setup

**1. Configure**
```bash
cp .env.example .env
chmod 600 .env
nano .env          # Blink creds, camera name, dashboard login, timezone
```

**2. Set the dashboard password**
```bash
docker run --rm caddy:2.11.4-alpine caddy hash-password --plaintext 'your-password'
# paste the full output between single quotes, preserving every $ literally:
# BASIC_AUTH_HASH='$2a$14$the-rest-of-the-generated-hash'
```

**3. Download and verify the model**
```bash
./scripts/download-model.sh
```
This verifies both pinned SHA-256 checksums, then installs the pair together as
`classifier/model/current/model.tflite` and
`classifier/model/current/labels.txt`. A failed update restores the previous
complete bundle instead of leaving a mismatched pair.

If you are upgrading an existing checkout that stored the two files directly
under `classifier/model/`, rerun `./scripts/download-model.sh` once to create the
new `current` bundle before running the preflight.

**4. Authenticate to Blink (one time, interactive)**
```bash
docker compose build puller
docker compose run --rm puller python auth_setup.py
# enter the 2FA code Blink emails; it prints the camera names and saves creds to
# ./data/blink/creds.json. Copy the exact feeder name into CAMERA_NAME if not "all".
```

**5. Verify the installation, then launch**
```bash
./scripts/verify-install.sh --build
docker compose up -d
docker compose logs -f          # watch it pull + classify
```

Open `http://<pi-ip>:8080`, log in, and confirm detections appear as birds
visit the feeder.

---

## Exposing the dashboard remotely

The dashboard listens on `:8080` and is already gated by `basic_auth`. Pick one
way to reach it from outside your home network:

**Tailscale Funnel** (no domain required):
```bash
sudo tailscale funnel 8080
```
This gives an `https://<pi>.<tailnet>.ts.net` URL. `basic_auth` is the login.

**Cloudflare Tunnel** (custom domain, no home-IP exposure): set
`CLOUDFLARE_TUNNEL_TOKEN` in `.env`, point a hostname at `http://web:8080`, then
`docker compose -f docker-compose.yml -f docker-compose.cloudflare.yml up -d`.
Add a Cloudflare Access email policy and you can drop `basic_auth` if you like.

On a phone: open the URL, log in once, **Add to Home Screen** — the manifest
makes it launch standalone like a native app.

---

## Running it hands-off

- All services are `restart: unless-stopped`.
- State (creds, DB, clips, dashboard data) lives under `./data`; each container
  receives only the subdirectories it needs.
- Containers run as the numeric `PUID`/`PGID` from `.env` (normally `1000:1000`),
  with read-only roots, no Linux capabilities, and separate networks.
- Classification work is claimed as `processing`. A restart automatically
  returns interrupted work to the queue; ordinary failures retry with backoff
  before becoming terminal `error` rows.
- Add the DB backup to cron: `0 3 * * * /path/to/bird-feeder/scripts/backup-db.sh`
- Set `NTFY_URL` in `.env` to get a push notification on new visitors and — more
  importantly — on a failed pull or an expired Blink token.
- If detections stop, check the obvious first: is the Blink camera online, and
  are its batteries dead? Both are visible in the Blink app.

## Knobs (all in `.env`)

`POLL_INTERVAL` how often to check Blink · `CONFIDENCE_THRESHOLD` how sure the
model must be to log an ID · `FRAMES_PER_CLIP` frames sampled per clip ·
`RETAIN_DAYS` how long raw clips are kept on disk · `MAX_CLIP_ATTEMPTS` failed
attempts before a clip becomes terminal · `CLIP_RETRY_DELAY` base retry delay in
seconds (the delay doubles after each failure).

## Handy commands

```bash
docker compose logs -f classifier          # tail one service
docker compose restart puller               # bounce a service
docker compose run --rm puller python auth_setup.py   # re-auth if the token expires
sqlite3 data/db/feeder.sqlite 'SELECT common_name, confidence, captured_at FROM detections ORDER BY captured_at DESC LIMIT 10;'
# inspect failed clips
sqlite3 data/db/feeder.sqlite "SELECT filename, attempt_count, note FROM clips WHERE status = 'error';"
# requeue failed clips after correcting the underlying problem
sqlite3 data/db/feeder.sqlite "UPDATE clips SET status = 'pending', attempt_count = 0, next_attempt_at = NULL, processing_started_at = NULL, note = 'manually requeued' WHERE status = 'error';"
```

## Notes & known edges

- `blinkpy` is an unofficial API — the riskiest dependency. `auth_setup.py`
  de-risks it in isolation before anything else runs.
- Use a **dedicated** Blink account. Sharing a personal login fights the app's
  2FA/session handling.
- The classifier is a clean, self-contained reimplementation of the
  blink-bird-id data flow with the cloud-AI call replaced by the local model —
  no upstream fork to track.
- MobileNetV2 is Perch's stable runtime. Its 224×224 TFLite pipeline uses
  aspect-ratio-preserving letterbox resize, bicubic interpolation, black
  padding, and the model's declared tensor dtype. The build preflight performs
  a real synthetic inference so incompatible model/runtime combinations fail
  before launch.
- ONNX remains an experimental future option, not an installable Perch backend.
  Evaluating it responsibly requires a separate image and dependency set,
  model-specific input handling, a bird-cropping stage, Pi 5 memory/latency
  benchmarks, and accuracy comparisons before it can affect the stable path.
- The dashboard is a static export (plain HTML/CSS/JS): nothing to build, trivial
  to serve, light on the Pi. To add filtering/history later, swap the static JSON
  for a small read-only API without touching the frontend contract.
