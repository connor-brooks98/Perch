# Perch

Perch turns a Blink camera and a home server into a private, locally powered
bird-identification feeder. It downloads motion clips, identifies visiting
birds on your own hardware, and serves a password-protected field-log dashboard.

> **Installing Perch for the first time?** Follow the
> [first-time installation guide](Perch_Installation_Guide.md). It assumes no
> Linux, Docker, or command-line experience and uses the primary Raspberry Pi 5
> setup path.

## What to expect

- Bird identification runs locally; clips are not sent to an AI API.
- Raspberry Pi 5 with Raspberry Pi OS Lite 64-bit is the primary and tested installation path.
- Other 64-bit machines that run Linux Docker containers may work as an advanced installation.
- A dedicated Blink account is strongly recommended; an active Blink subscription is required.
- Remote dashboard access is optional. The Pi needs outbound internet access for Blink and installation downloads.

Perch uses TensorFlow Lite (TFLite), a lightweight local model runtime, for bird
identification.

```text
Blink cloud ──> puller ──> clips volume ──> classifier ──> SQLite + thumbs + JSON ──> web (Caddy) ──> browser
                (blinkpy)                    (ffmpeg + TFLite)                          (basic_auth)
```

## Prerequisites

Before setup, make sure you have:

- A dedicated Blink account with the feeder camera added to it. This is strongly
  recommended to prevent session conflicts with a personal Blink login.
- An active Blink subscription so clips appear in Blink's cloud-media feed.
  Sync Module 2 local-storage downloading uses a different API and is not yet
  implemented by Perch.
- A supported home server. The primary path is a Raspberry Pi 5 running
  Raspberry Pi OS Lite 64-bit.

The quick start below assumes you can connect with SSH (Secure Shell) and use
Docker Compose, the tool that defines and runs Perch's three containers.

## Experienced-user quick start

This section is for readers already comfortable with SSH, environment files,
and Docker Compose. Everyone else should use the
[first-time installation guide](Perch_Installation_Guide.md).

1. Configure the environment file:

   ```bash
   cp .env.example .env
   chmod 600 .env
   nano .env
   ```

2. Generate a bcrypt password hash and save it as `BASIC_AUTH_HASH` in `.env`:

   ```bash
   docker run --rm -it caddy:2.11.4-alpine caddy hash-password
   ```

   Enter the dashboard password at the hidden prompt; Caddy does not echo it.
   Preserve every literal `$` from the generated hash, do not double any `$`,
   and keep the complete value between single quotes:

   ```dotenv
   BASIC_AUTH_HASH='$2a$14$the-rest-of-the-generated-hash'
   ```

3. Download the verified model bundle:

   ```bash
   ./scripts/download-model.sh
   ```

4. Authenticate with Blink:

   ```bash
   docker compose build puller
   docker compose run --rm puller python auth_setup.py
   ```

5. Run the installation preflight and start Perch:

   ```bash
   ./scripts/verify-install.sh --build
   docker compose up -d
   ```

## How to know it worked

1. `./scripts/verify-install.sh --build` ends with
   `Container privilege, data-directory, and model inference checks passed.`
2. `docker compose ps` shows `puller`, `classifier`, and `web` running.
3. `http://<pi-ip>:8080` shows the Perch login page. Replace `<pi-ip>` with the
   Raspberry Pi's local address; do not type the angle brackets.
4. After login, an empty dashboard is normal until Blink records a new motion clip.

## Troubleshooting

| Symptom | First check |
|---|---|
| Docker permission or daemon error | Run `docker info`; reconnect after joining the `docker` group and confirm Docker is running. |
| Preflight says `.env` is missing or unsafe | Copy `.env.example`, fill it in, and run `chmod 600 .env`. |
| Model files are missing or invalid | Run `./scripts/download-model.sh`; do not copy one model-bundle file by itself. |
| Blink login or 2FA fails | Confirm the dedicated account works in Blink, wait after repeated attempts, then rerun `auth_setup.py`. |
| Dashboard does not open | Run `docker compose ps`, then try the Pi's local IP on port `8080`. |
| Dashboard opens but has no birds | Confirm Blink recorded a subscribed cloud clip, then inspect `docker compose logs classifier`. |
| A clip reached terminal error | Correct the cause, then use the documented manual requeue command. |

## Everyday operation

- All services use `restart: unless-stopped`, so Perch normally resumes after a
  restart or power outage.
- Watch activity with `docker compose logs -f`, or one service with
  `docker compose logs -f classifier`.
- Restart a service with `docker compose restart puller`.
- Reauthenticate an expired Blink session with
  `docker compose run --rm puller python auth_setup.py`.
- If detections stop, confirm in the Blink app that the camera is online, its
  batteries are charged, and a new subscribed cloud clip exists.
- Set `NTFY_URL` in `.env` to receive notifications for new visitors, failed
  pulls, and expired Blink tokens.

Classification work is claimed as `processing`. A restart returns interrupted
work to the queue; ordinary failures retry with backoff before becoming terminal
`error` rows. Inspect and manually requeue terminal errors after correcting the
underlying cause:

These database inspection and recovery commands use the SQLite command-line
utility installed by the primary Raspberry Pi guide. Advanced hosts must
install their operating system's equivalent `sqlite3` package.

```bash
sqlite3 data/db/feeder.sqlite "SELECT filename, attempt_count, note FROM clips WHERE status = 'error';"
docker compose stop classifier
sqlite3 data/db/feeder.sqlite "UPDATE clips SET status = 'pending', attempt_count = 0, next_attempt_at = NULL, processing_started_at = NULL, note = 'manually requeued' WHERE status = 'error';"
docker compose start classifier
```

To view recent detections directly:

```bash
sqlite3 data/db/feeder.sqlite 'SELECT common_name, confidence, captured_at FROM detections ORDER BY captured_at DESC LIMIT 10;'
```

## Configuration reference

All settings live in `.env`:

| Setting | Purpose |
|---|---|
| `POLL_INTERVAL` | How often to check Blink. |
| `CONFIDENCE_THRESHOLD` | How confident the model must be before logging an identification. |
| `FRAMES_PER_CLIP` | Number of frames sampled from each clip. |
| `RETAIN_DAYS` | Number of days to retain raw clips. |
| `MAX_CLIP_ATTEMPTS` | Failed attempts allowed before a clip becomes terminal. |
| `CLIP_RETRY_DELAY` | Initial retry delay in seconds; the delay doubles after each failure. |
| `PUID` / `PGID` | Numeric host user and group IDs used for data-file ownership. |
| `NTFY_URL` | Optional notification destination. |
| `CLOUDFLARE_TUNNEL_TOKEN` | Optional Cloudflare Tunnel credential. |

## Backups and updates

Runtime state, Blink credentials, the database, clips, and dashboard data live
under `./data`. Containers receive only the subdirectories they need.

Run `./scripts/backup-db.sh` to create a SQLite backup. For a nightly backup,
add this cron entry, replacing the example path with the repository's location:

```cron
0 3 * * * /path/to/Perch/scripts/backup-db.sh
```

After updating the repository, rerun the supported model installer and preflight
before recreating the services:

```bash
./scripts/download-model.sh
./scripts/verify-install.sh --build
docker compose up -d
```

## Remote access (optional)

The dashboard listens on port `8080` and is protected by `basic_auth`. Remote
access is not required for use on the home network.

Tailscale Serve is the recommended private option. It keeps the dashboard
private to your tailnet, so only signed-in devices allowed by that tailnet can
reach it. Configure it to persist across terminal sessions and Pi restarts:

```bash
sudo tailscale serve --bg 8080
```

This provides an `https://<pi>.<tailnet>.ts.net` address. On a phone, open the
Tailscale app, sign into the same tailnet, open the address, log in to Perch,
and use **Add to Home Screen**. Tailscale Funnel makes the dashboard public to
the internet; do not use Funnel for ordinary private phone access.

With Cloudflare Tunnel, set `CLOUDFLARE_TUNNEL_TOKEN` in `.env`, point a hostname
at `http://web:8080`, then start the tunnel overlay:

```bash
docker compose -f docker-compose.yml -f docker-compose.cloudflare.yml up -d
```

Add a Cloudflare Access policy before considering any change to dashboard
authentication.

## Security and privacy

- Bird identification happens on your hardware; Perch does not send clips to
  an AI API. Blink cloud storage is still involved in the current clip-download
  path.
- A dedicated Blink account is strongly recommended. Sharing a personal login
  can cause session conflicts with Blink's app, two-factor authentication, and
  session handling. An active Blink subscription is required for Perch's
  current cloud-media download path.
- Keep `.env` private and restricted with `chmod 600 .env`.
- Containers run as the numeric `PUID`/`PGID` from `.env`, with read-only root
  filesystems, no Linux capabilities, narrow mounts, and separate networks.
- Keep dashboard authentication enabled, especially when enabling remote access.

## Architecture and repository map

| Path | Role |
|---|---|
| `puller/` | `blinkpy` clip fetcher and one-time `auth_setup.py`. |
| `classifier/` | FFmpeg frame extraction and local model inference (`classify.py`, `watcher.py`). |
| `classifier/model/` | Verified model bundle and its model-specific README. |
| `common/` | Shared SQLite schema, helpers, and ntfy notifier. |
| `web/` | Caddy configuration and the static field-log dashboard. |
| `scripts/backup-db.sh` | SQLite backup helper. |
| `scripts/download-model.sh` | Transactional model-bundle downloader and verifier. |
| `scripts/verify-install.sh` | Installation, container, and inference preflight. |
| `docker-compose.yml` | The `puller`, `classifier`, and `web` services. |
| `docker-compose.cloudflare.yml` | Optional Cloudflare Tunnel overlay. |

The classifier replaces a cloud-AI call with a local inference pipeline. The
dashboard is a static HTML/CSS/JavaScript export served by Caddy.

## Model policy and known limitations

- MobileNetV2 is Perch's stable runtime. Its 224×224 TFLite pipeline uses
  aspect-ratio-preserving letterbox resize, bicubic interpolation, black
  padding, and the model's declared tensor data type. The build preflight runs
  a synthetic inference so incompatible model/runtime combinations fail before
  launch.
- Install the model and labels together with `./scripts/download-model.sh`. The
  script verifies pinned SHA-256 checksums and promotes both files as one bundle
  to `classifier/model/current/model.tflite` and
  `classifier/model/current/labels.txt`.
- ONNX remains an experimental future option, not an installable Perch backend.
  It requires a separate image and dependencies, model-specific input handling,
  a bird-cropping stage, Raspberry Pi 5 memory and latency benchmarks, and
  accuracy comparisons before it can affect the stable path.
- `blinkpy` uses an unofficial Blink API and is the project's riskiest
  dependency. `auth_setup.py` isolates account authentication before normal
  operation begins.
- Sync Module 2 local-storage downloading is not implemented; an active Blink
  subscription is currently required.
