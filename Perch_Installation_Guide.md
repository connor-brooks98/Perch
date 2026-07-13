# Perch Installation Guide
### Setting up your Smart Bird Feeder — no IT background required

This guide walks you through everything, start to finish: buying/setting up the camera, preparing the Raspberry Pi, and getting the dashboard running on your phone. Follow the steps in order and don't skip any — each one sets up something the next step needs.

Budget about 2 hours the first time. You'll only need to do this once.

---

## What you'll need before you start

- **A Raspberry Pi 5** (with power adapter and a microSD card, 32GB or larger)
- **A Blink camera** already set up outdoors pointed at the feeder
- **A computer** (Mac or Windows) to prepare the Pi's memory card
- **Your home WiFi name and password**
- **About 2 hours**, and patience for one part that involves waiting on an email code

---

## Part 1: Create a dedicated Blink account

Don't use your personal Blink account for this — use a brand-new one, just for the feeder camera. This avoids login conflicts between your phone and the Pi fighting over the same account.

1. Download the Blink app on your phone (if not already installed).
2. Sign out of your existing account (if any), or use a different phone/browser.
3. Create a **new** Blink account with a new email address (a free Gmail address works fine — e.g., `yourname.birdfeeder@gmail.com`).
4. Add your Blink camera to this new account, following Blink's normal setup steps (connect it to your WiFi, name it something simple like "Feeder").
5. Activate a **paid Blink subscription** for this account. Perch currently pulls
   from Blink's cloud-media feed. A Sync Module 2 USB drive uses a different
   local-storage API that Perch does not support yet.
6. Write down: the Blink login email, the Blink password, and the exact camera name you gave it. You'll need these shortly.

---

## Part 2: Prepare the Raspberry Pi

### 2a. Flash the operating system

1. On your computer, download and install **Raspberry Pi Imager** from [raspberrypi.com/software](https://www.raspberrypi.com/software/).
2. Insert the microSD card into your computer.
3. Open Raspberry Pi Imager:
   - **Device:** choose your Raspberry Pi model
   - **Operating System:** choose "Raspberry Pi OS Lite (64-bit)" (it's under "Raspberry Pi OS (other)")
   - **Storage:** choose your microSD card
4. Click the **gear/settings icon** (or "Edit Settings") before writing. This lets you pre-configure WiFi and remote access so you never need a monitor/keyboard for the Pi:
   - Set a hostname (e.g., `birdfeeder`)
   - Enable SSH, and set a username/password you'll remember
   - Enter your home WiFi name and password
5. Click **Write**, wait for it to finish, then eject the card and put it in the Raspberry Pi.
6. Plug in power. Wait 2–3 minutes for it to boot.

### 2b. Connect to the Pi remotely

You won't plug a monitor into the Pi — you'll control it from your computer's Terminal (Mac) or PowerShell (Windows).

1. Open **Terminal** (Mac) or **PowerShell** (Windows).
2. Type (replacing `pi` and `birdfeeder` with the username/hostname you set):
   ```
   ssh pi@birdfeeder.local
   ```
3. Type "yes" if asked to trust the connection, then enter the password you set in Raspberry Pi Imager.
4. You're now controlling the Pi. Every command below is typed into this same window.

### 2c. Install Docker


Docker is the tool that runs Perch's three components for you. Copy-paste this one line, press Enter, and wait (a few minutes):

```
curl -fsSL https://get.docker.com | sh
```

When it finishes, run these two commands so you don't need to type `sudo` every time:

```
sudo usermod -aG docker $USER
newgrp docker
```

Confirm it worked:

```
docker --version
docker compose version
```

You should see version numbers printed for both, with no errors.

---

## Part 3: Download the Perch project

Still in the same Terminal window, connected to the Pi:

```
git clone https://github.com/connor-brooks98/Perch.git
cd Perch
```

You're now inside the project folder on the Pi.


---

## Part 4: Configure Perch

### 4a. Create your settings file

```
cp .env.example .env
chmod 600 .env
nano .env
```

This opens a simple text editor. Fill in:

- Your dedicated Blink account email and password
- The exact camera name from Part 1
- Your timezone (e.g., `America/New_York`)
- Anything else the file asks for (each line has a short comment explaining it)

Leave `PUID=1000` and `PGID=1000` unchanged for the usual first user on a
Raspberry Pi. If the `id` command reports different `uid` or `gid` numbers, use
those values instead. Perch uses them to write its data without running the
containers as root.

To save and exit `nano`: press `Ctrl + O`, then `Enter`, then `Ctrl + X`.

### 4b. Set your dashboard login password

This is the password you'll use to log into the bird dashboard from your phone. Run:

```
docker run --rm caddy:2.11.4-alpine caddy hash-password --plaintext 'your-password'
```

Replace `your-password` with a real password you'll remember. This command prints out a scrambled version starting with `$2a$...` — copy that entire output.

Open the settings file again:

```
nano .env
```

Find `BASIC_AUTH_HASH=` and paste the full generated hash between the existing
single quotes. For example:

```
BASIC_AUTH_HASH='$2a$14$the-rest-of-the-generated-hash'
```

Keep every `$` exactly as generated—do not double them. The single quotes tell
Docker Compose to treat the hash literally.

Save and exit (`Ctrl + O`, `Enter`, `Ctrl + X`).

### 4c. Add the bird identification model

The camera needs a "brain" to identify bird species — two small files that need to end up in a specific folder on the Pi:

- `model.tflite`
- `labels.txt`

MobileNetV2 is Perch's stable runtime. ONNX models are still experimental and
are not supported by these installation steps.

Option A downloads the supported files straight onto the Pi and is the
recommended path. Options B and C are recovery methods for transferring the
same pinned MobileNetV2 files on a new installation. Custom models are not
accepted by the standard preflight because their model/label compatibility has
not been validated.

**Option A — Download the files directly onto the Pi (easiest — this is the recommended method)**

These files come from Google's Coral model archive. Perch includes a helper that
downloads them, verifies pinned SHA-256 checksums, and only then installs them:

```
cd ~/Perch
./scripts/download-model.sh
```

Success ends with `Verified model bundle installed in
.../classifier/model/current`. The two verified files are promoted together,
so an interrupted update cannot leave a new model paired with old labels.

If you are updating an older Perch installation, rerun
`./scripts/download-model.sh` once even if model files already exist. Older
versions stored them directly in `classifier/model/`; current versions use the
transactional bundle at `classifier/model/current/model.tflite` and
`classifier/model/current/labels.txt`.

**Option B — The files are already on your computer, and you're comfortable with Terminal**

If you had to download the files onto your Mac or Windows PC first (rather than getting a direct link), copy them over the network to the Pi using `scp`. Do this from a **new** Terminal/PowerShell window on your **own computer** — not the one still connected to the Pi:

```
ssh pi@birdfeeder.local "mkdir -p ~/Perch/classifier/model/current"
scp /path/to/your/model.tflite pi@birdfeeder.local:~/Perch/classifier/model/current/
scp /path/to/your/labels.txt pi@birdfeeder.local:~/Perch/classifier/model/current/
```

Replace `/path/to/your/` with wherever the files actually landed (often your `Downloads` folder, e.g. `~/Downloads/model.tflite`), and `pi@birdfeeder.local` with your own Pi username/hostname from Part 2a. It'll ask for your Pi password again — that's normal.

**Option C — You'd rather drag-and-drop with a window, no typing file paths**

If Terminal commands feel error-prone, use a free file-transfer app that gives you a familiar two-pane, drag-and-drop window:

1. Download **Cyberduck** (Mac or Windows) from [cyberduck.io](https://cyberduck.io) or **FileZilla** from [filezilla-project.org](https://filezilla-project.org).
2. Open it and choose to connect via **SFTP**.
3. Server: `birdfeeder.local` (or your Pi's IP address) — Username/Password: whatever you set in Part 2a.
4. Once connected, you'll see your Pi's folders on one side. Navigate to
   `Perch/classifier/model/`, create a folder named `current` if it does not
   exist, then open `current`.
5. Drag `model.tflite` and `labels.txt` from your computer's folder on the other side directly into that window.

**Double-check it worked**

Back in your Terminal window connected to the Pi, run:

```
ls -lh ~/Perch/classifier/model/current/
```

You should see both `model.tflite` and `labels.txt` listed with a file size next to each (not `0`). If either is missing or shows `0` bytes, redo that file's transfer before moving on — Perch won't start correctly without both.

---

## Part 5: Connect Perch to your Blink camera (one-time)

This step logs the Pi into your Blink account and requires a code emailed to you.

```
docker compose build puller
docker compose run --rm puller python auth_setup.py
```

- Blink will email a verification code to the account's inbox — check that email and type the code in when prompted.
- Once accepted, it will print your camera's name(s). Double-check the name matches what you put in `.env` under `CAMERA_NAME` (if it doesn't match exactly, go back into `nano .env` and fix it).

---

---

## Part 6: Launch everything

First run the complete preflight. It validates settings, Compose, model
checksums, and builds all images:

```
./scripts/verify-install.sh --build
```

Only continue if it ends with `Container images built successfully.` Then run:

```
docker compose up -d
```

This builds and starts all three parts of Perch (camera puller, bird-ID classifier, and the dashboard website). The first run takes a few minutes.

Watch it working (optional, press `Ctrl + C` to stop watching — this does **not** stop the program):

```
docker compose logs -f
```

---

## Part 7: View your dashboard

1. On any device connected to your home WiFi, open a web browser.
2. Go to: `http://birdfeeder.local:8080` (replace `birdfeeder` with whatever hostname you chose in Part 2a). If that doesn't load, use the Pi's IP address instead, e.g. `http://192.168.1.50:8080`.
3. Log in with the password you set in Part 4b (the username is whatever you configured in `.env`, often just any value).
4. You should see the dashboard, and detections will start appearing as birds visit the feeder.

---

## Part 8: View it from your phone, from anywhere (optional)

By default the dashboard only works at home, on your WiFi. To check it from anywhere:

1. Install **Tailscale** on the Pi:
   ```
   curl -fsSL https://tailscale.com/install.sh | sh
   sudo tailscale up
   ```
   Follow the link it gives you to sign in (a free personal account is fine).
2. Turn on remote access:
   ```
   sudo tailscale funnel 8080
   ```
3. Install the **Tailscale app** on your phone and sign into the same account.
4. On your phone, open the `https://....ts.net` web address Tailscale gives you, log in with your dashboard password, then use your phone's "Add to Home Screen" option so it opens like a normal app icon.

---

## Everyday use — what you need to know

- **You don't need to do anything day-to-day.** The Pi keeps running and restarts itself automatically, even after a power outage.
- **If Part 5's login step fails** with something like `Login endpoint failed` or `Cannot setup Blink platform`: this means Blink itself rejected the login, not a problem with your Pi. Open the Blink app and confirm the same email/password logs in there directly — that catches typos or an unverified new account immediately. If you've retried the command several times in a row, wait 15–20 minutes first; Blink temporarily rate-limits repeated login attempts from the same account.
- **If Compose reports part of the password hash as an unset variable**, make sure
  the entire generated hash is between single quotes as shown in Part 4b.
- **If you ever need to restart something**, reconnect with `ssh pi@birdfeeder.local`, go to the folder (`cd Perch`), and run:
  ```
  docker compose restart
  ```
- **If the Blink login stops working after a while** (rare, but happens if a session expires), reconnect and run:
  ```
  docker compose run --rm puller python auth_setup.py
  ```
  and re-enter the emailed code, same as Part 5.
- **If one video cannot be decoded**, Perch retries it automatically. The
  defaults are `MAX_CLIP_ATTEMPTS=3` and `CLIP_RETRY_DELAY=60`, which means the
  first two failures wait 60 and 120 seconds. A third failure is saved with
  `status = 'error'` so it cannot block newer clips.
- **To retry failed videos after correcting the cause**, stop the classifier,
  reset those rows, and start it again:
  ```
  docker compose stop classifier
  sqlite3 data/db/feeder.sqlite "UPDATE clips SET status = 'pending', attempt_count = 0, next_attempt_at = NULL, processing_started_at = NULL, note = 'manually requeued' WHERE status = 'error';"
  docker compose start classifier
  ```

---

## Quick reference: all commands used

| What | Command |
|---|---|
| Connect to the Pi | `ssh pi@birdfeeder.local` |
| Go to the project folder | `cd Perch` |
| Edit settings | `nano .env` |
| Start everything | `docker compose up -d --build` |
| Watch activity | `docker compose logs -f` |
| Restart everything | `docker compose restart` |
| Re-login to Blink | `docker compose run --rm puller python auth_setup.py` |

---

*If you get stuck on any single step, note the exact command you ran and the exact error message shown — that's all that's needed to troubleshoot it.*
