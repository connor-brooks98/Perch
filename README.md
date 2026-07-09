# Smart Bird Feeder — backend

A no-recurring-cost bird-ID pipeline. A stock Blink camera on a 3D-printed
feeder records motion clips; a Raspberry Pi 5 at your house pulls those clips,
identifies the bird with a **local** TFLite model (no API, $0 inference), and
serves a login-gated dashboard she can add to her phone's home screen.

```
Blink cloud ──> puller ──> clips volume ──> classifier ──> SQLite + thumbs + JSON ──> web (Caddy) ──> her phone
                (blinkpy)                    (ffmpeg + tflite)                          (basic_auth)
```

Everything runs in Docker on the Pi (64-bit). The same compose project moves to
the NUC later, unchanged.

## What's in here

| Path | Role |
|------|------|
| `puller/` | `blinkpy` clip fetcher + one-time `auth_setup.py` |
| `classifier/` | ffmpeg frame extraction + TFLite inference (`classify.py`, `watcher.py`) |
| `classifier/model/` | **you drop the model + labels here** (see its README) |
| `common/` | shared SQLite schema/helpers + ntfy notifier |
| `web/` | Caddy config + the static field-log dashboard |
| `scripts/backup-db.sh` | nightly SQLite backup |
| `docker-compose.yml` | the three services |
| `docker-compose.cloudflare.yml` | optional Cloudflare Tunnel edge |

---

## First-time setup

Assumes Phase 0–1 are done: dedicated Blink account created, camera on her
WiFi, a storage option enabled (subscription **or** Sync Module 2 + USB — clips
must be retained somewhere `blinkpy` can reach), and the Pi running Raspberry Pi
OS Lite 64-bit with Docker + Compose installed.

**1. Configure**
```bash
cp .env.example .env
nano .env          # Blink creds, camera name, login, timezone
```

**2. Set the dashboard password**
```bash
docker run --rm caddy:2-alpine caddy hash-password --plaintext 'her-password'
# paste the $2a$... output into BASIC_AUTH_HASH in .env
```

**3. Drop in the model** — see `classifier/model/README.md`. Two files:
`classifier/model/model.tflite` and `classifier/model/labels.txt`.

**4. Authenticate to Blink (one time, interactive)**
```bash
docker compose build puller
docker compose run --rm puller python auth_setup.py
# enter the 2FA code Blink emails; it prints the camera names + saves creds to
# ./data/blink/creds.json. Copy the exact feeder name into CAMERA_NAME if not "all".
```

**5. Launch**
```bash
docker compose up -d --build
docker compose logs -f          # watch it pull + classify
```

Open `http://<pi-ip>:8080`, log in, and confirm detections appear as birds
visit the feeder.

---

## Exposing it to her phone (Phase 6)

The dashboard listens on `:8080` and is already gated by `basic_auth`. Pick one
way to reach it from outside your house:

**Tailscale Funnel** (uses what you already run, no domain):
```bash
sudo tailscale funnel 8080
```
This gives an `https://<pi>.<tailnet>.ts.net` URL. `basic_auth` is the login.

**Cloudflare Tunnel** (nicer login, custom domain, no home-IP exposure): set
`CLOUDFLARE_TUNNEL_TOKEN` in `.env`, point a hostname at `http://web:8080`, then
`docker compose -f docker-compose.yml -f docker-compose.cloudflare.yml up -d`.
Add a Cloudflare Access email policy and you can drop `basic_auth` if you like.

On her phone: open the URL, log in once, **Add to Home Screen** — the manifest
makes it launch standalone like a real app.

---

## Running it hands-off (Phase 7)

- All services are `restart: unless-stopped`.
- State (creds, DB, clips, dashboard data) is on the `./data` bind mount.
- Add the DB backup to cron: `0 3 * * * /path/to/bird-feeder/scripts/backup-db.sh`
- Set `NTFY_URL` in `.env` to get a phone ping on new visitors, and — more
  importantly — on a dead pull or expired Blink token.
- If detections stop, first check she can answer herself: **is the Blink camera
  online / are the batteries dead?** — visible in her own Blink app.

## Knobs (all in `.env`)

`POLL_INTERVAL` how often to check Blink · `CONFIDENCE_THRESHOLD` how sure the
model must be to log an ID · `FRAMES_PER_CLIP` frames sampled per clip ·
`RETAIN_DAYS` how long raw clips are kept on disk.

## Handy commands

```bash
docker compose logs -f classifier          # tail one service
docker compose restart puller               # bounce a service
docker compose run --rm puller python auth_setup.py   # re-auth if the token expires
sqlite3 data/db/feeder.sqlite 'SELECT common_name, confidence, captured_at FROM detections ORDER BY captured_at DESC LIMIT 10;'
```

## Notes & known edges

- `blinkpy` is an unofficial API — the riskiest dependency. Phase 2's
  `auth_setup.py` de-risks it in isolation before anything else runs.
- Use a **dedicated** Blink account. Sharing her personal login fights the app's
  2FA/session handling.
- The classifier is a clean, self-contained reimplementation of the
  blink-bird-id data flow with the cloud-AI call replaced by the local model —
  no upstream fork to track.
- Dashboard is a static export (plain HTML/CSS/JS): nothing to build, trivial to
  serve, light on the Pi. To add filtering/history later, swap the static JSON
  for a tiny read-only API without touching the frontend contract.
