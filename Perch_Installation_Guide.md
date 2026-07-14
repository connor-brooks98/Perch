# Perch Installation Guide

### Setting up your Smart Bird Feeder — no IT background required

This is Perch's single authoritative first-time installation guide. It follows
the primary and tested setup: a Raspberry Pi 5 running Raspberry Pi OS Lite
64-bit. No Linux, Docker, Git, or command-line experience is assumed.

**Primary and tested setup:** Follow the steps in order and do not skip any.
Each step prepares something the next step needs.

Other 64-bit machines that run Linux Docker containers may work, but those are
advanced installations and can require different permission, networking, or
inference dependencies.

Budget about two hours the first time. You only need to complete this setup
once.

Remote dashboard access is optional. The Pi needs outbound internet access for Blink and installation downloads.

---

## What you need before you start

- **A Raspberry Pi 5** with its power adapter and a microSD card (32 GB or larger)
- **A Blink camera** already set up outdoors and pointed at the feeder
- **A computer** (Mac or Windows) for preparing the Pi and connecting to it
- **Your home Wi-Fi name and password**
- **About two hours**, including time to wait for an emailed Blink code

---

## Part 1: Create a dedicated Blink account

Use a new Blink account just for the feeder camera, rather than your personal
account. This avoids login conflicts between the Blink app and the Pi.

1. Download the Blink app on your phone if it is not already installed.
2. Sign out of any existing account, or use a different phone or browser.
3. Create a new Blink account with a new email address.
4. Add the feeder camera, connect it to your Wi-Fi, and give it a simple name
   such as `Feeder`.
5. Activate a **paid Blink subscription** for this account. Perch reads Blink's
   cloud-media feed. Sync Module 2 USB storage uses a different API that Perch
   does not support yet.
6. Save the Blink email, password, and exact camera name for Part 4.

---

## Part 2: Prepare the Raspberry Pi

### 2a. Flash Raspberry Pi OS

1. On your computer, install **Raspberry Pi Imager** from
   [raspberrypi.com/software](https://www.raspberrypi.com/software/).
2. Insert the microSD card into your computer.
3. In Raspberry Pi Imager choose:
   - **Device:** Raspberry Pi 5
   - **Operating System:** Raspberry Pi OS Lite (64-bit), under Raspberry Pi OS
     (other)
   - **Storage:** your microSD card
4. Select **Edit Settings** before writing, then:
   - Choose a hostname, such as `birdfeeder`.
   - Enable SSH and choose your own username and password.
   - Enter your home Wi-Fi name and password.
5. Select **Write** and wait for Raspberry Pi Imager to report that writing and
   verification are complete.
6. Eject the card, insert it into the Pi, connect power, and wait 2–3 minutes.

**Checkpoint:** Raspberry Pi Imager shows that the card was written and
verified successfully, and the powered Pi has finished its first boot.

### 2b. Connect to the Pi

You control the Pi from Terminal on a Mac or PowerShell on Windows.

Text inside angle brackets is a placeholder. Replace it with your own value;
do not type the angle brackets themselves. For example, `<username>` is the
username you chose, `<hostname>` is the hostname you chose, `<pi-ip>` is the
Pi's numeric address if its hostname does not work, and `<path>` means a path
specific to your computer. Do not type the angle brackets in any command.

Open Terminal or PowerShell.

**Run on your computer:**

```bash
ssh <username>@<hostname>.local
```

Type `yes` if asked to trust the connection, then enter the password you chose
in Raspberry Pi Imager. If the hostname does not work and you know the Pi's IP
address, use `ssh <username>@<pi-ip>` instead. Do not assume the username is
`pi`; Raspberry Pi Imager uses the username you configured.

**Checkpoint:** The prompt changes after login and shows the Pi's hostname. You
can now type commands on the Raspberry Pi in this same window.

### 2c. Install Docker and SQLite

Docker runs Perch's three services. Copy each block into the connected window,
press Enter, and wait for it to finish.

**Run on the Raspberry Pi:**

```bash
curl -fsSL https://get.docker.com | sh
```

Install the SQLite command-line utility used by Perch's database inspection
and manual-requeue commands.

**Run on the Raspberry Pi:**

```bash
sudo apt-get update
sudo apt-get install -y sqlite3
```

Allow your configured user to run Docker, then refresh the group membership.

**Run on the Raspberry Pi:**

```bash
sudo usermod -aG docker "$USER"
newgrp docker
```

Check Docker, Compose, and SQLite.

**Run on the Raspberry Pi:**

```bash
docker --version
docker compose version
sqlite3 --version
```

**Checkpoint:** Docker, Compose, and SQLite each print a version number without
an error.

---

## Part 3: Download Perch

Keep using the window connected to the Raspberry Pi.

**Run on the Raspberry Pi:**

```bash
git clone https://github.com/connor-brooks98/Perch.git
cd Perch
```

**Checkpoint:** The clone finishes without an error and the prompt shows that
you are inside the `Perch` folder.

---

## Part 4: Configure Perch

### 4a. Create the settings file

**Run on the Raspberry Pi:**

```bash
cp .env.example .env
chmod 600 .env
nano .env
```

In the editor, enter:

- The dedicated Blink account email and password from Part 1
- The exact Blink camera name
- Your timezone, such as `America/New_York`
- The other requested values described by comments in the file

Leave `PUID=1000` and `PGID=1000` unchanged for the usual first Raspberry Pi
user. If the `id` command reports different `uid` or `gid` numbers, use those
values instead. Perch uses them to write its data without running containers as
root.

Save with `Ctrl + O`, press Enter, and exit with `Ctrl + X`.

### 4b. Set the dashboard password

Choose a dashboard password you will remember. The following command asks for
it at a hidden prompt, so the password is not echoed or placed in the command.

**Run on the Raspberry Pi:**

```bash
docker run --rm -it caddy:2.11.4-alpine caddy hash-password
```

Copy the entire generated hash, which starts with `$2a$`, `$2b$`, or `$2y$`.
Open the settings file again.

**Run on the Raspberry Pi:**

```bash
nano .env
```

Paste the generated value between the existing single quotes after
`BASIC_AUTH_HASH=`. A valid line looks like
`BASIC_AUTH_HASH='$2a$14$the-rest-of-the-generated-hash'`. Keep every `$`
exactly as generated; do not double them. Save and exit the editor.

**Checkpoint:** `.env` contains your Blink details, exact camera name, timezone,
and a complete single-quoted bcrypt hash, and `chmod 600 .env` has protected the
file.

### 4c. Install the bird-identification model

MobileNetV2 is Perch's stable runtime. ONNX models are experimental and are not
part of this installation path. Perch's helper downloads the supported model
and labels, verifies their pinned SHA-256 checksums, and promotes both files
together as one bundle. An interrupted update therefore cannot pair a new
model with old labels.

**Run on the Raspberry Pi:**

```bash
./scripts/download-model.sh
```

**Checkpoint:** The command ends with `Verified model bundle installed in
.../classifier/model/current`. The bundle contains both `model.tflite` and
`labels.txt`.

If you are upgrading an older Perch installation, rerun
`./scripts/download-model.sh` once even if model files already exist. Older
versions stored files directly in `classifier/model/`; current versions use
`classifier/model/current/model.tflite` and
`classifier/model/current/labels.txt`.

---

## Part 5: Authenticate with Blink

This one-time step signs the Pi into the dedicated Blink account. Blink will
email a verification code.

**Run on the Raspberry Pi:**

```bash
docker compose build puller
docker compose run --rm puller python auth_setup.py
```

Enter the emailed code when prompted. The command then prints the camera names
available to the account. If the intended name does not exactly match
`CAMERA_NAME` in `.env`, reopen `.env`, correct it, save, and exit.

**Checkpoint:** Authentication is accepted and the command prints the feeder
camera name exactly as it appears in `CAMERA_NAME`.

---

## Part 6: Verify and launch Perch

### 6a. Run the complete preflight

The preflight checks settings, file permissions, Compose configuration, model
checksums, container privileges, data-directory access, and real model
inference. It also builds the container images.

**Run on the Raspberry Pi:**

```bash
./scripts/verify-install.sh --build
```

**Checkpoint:** Continue only when the final line is `Container privilege, data-directory, and model inference checks passed.` A prior `Container images
built successfully.` line is not the final checkpoint.

### 6b. Start the services

**Run on the Raspberry Pi:**

```bash
docker compose up -d
```

The camera puller, bird classifier, and dashboard now run in the background.
The first start can take a few minutes.

**Checkpoint:** Docker Compose lists the Perch services as started and returns
without an error.

To watch activity, use the following command. Press `Ctrl + C` to stop watching;
this does not stop Perch.

**Run on the Raspberry Pi:**

```bash
docker compose logs -f
```

---

## Part 7: Open the dashboard

1. On a device connected to your home Wi-Fi, open a web browser.
2. Visit `http://<hostname>.local:8080`. If that does not load, visit
   `http://<pi-ip>:8080` instead.
3. Log in with the dashboard username from `.env` and the password whose hash
   you created in Part 4.

**Checkpoint:** The Perch dashboard opens and accepts your login. It may be
empty at first. A detection appears only after a new clip is recorded by the
subscribed Blink camera, uploaded to Blink cloud storage, and processed by
Perch.

---

## Part 8: Optional remote phone access

By default, the dashboard works only on your home Wi-Fi. Tailscale Serve is the
recommended way to add remote access while keeping the dashboard private to your tailnet.

Install Tailscale and follow the sign-in link it prints.

**Run on the Raspberry Pi:**

```bash
curl -fsSL https://tailscale.com/install.sh | sh
sudo tailscale up
```

Enable access to the dashboard.

**Run on the Raspberry Pi:**

```bash
sudo tailscale serve --bg 8080
```

Install the Tailscale app on your phone, sign into the same account, and open
the `https://....ts.net` address that Tailscale provides. The `--bg` flag keeps
Serve active after you close the terminal and across Pi restarts.

Tailscale Funnel makes the dashboard public to the internet, including to
people who are not signed into your tailnet. Do not use Funnel for ordinary
private phone access.

---

## Everyday use and troubleshooting

- **Normal operation:** The Pi keeps Perch running and restarts the services
  after a power outage.
- **Blink login failure:** If authentication reports `Login endpoint failed`
  or `Cannot setup Blink platform`, confirm the same email and password in the
  Blink app. After several attempts, wait 15–20 minutes because Blink can
  temporarily limit repeated logins.
- **Unset hash variable:** Make sure the full bcrypt hash in `.env` is enclosed
  in single quotes exactly as shown in Part 4.
- **Video retries:** Perch defaults to `MAX_CLIP_ATTEMPTS=3` and
  `CLIP_RETRY_DELAY=60`. The first two failures wait 60 and 120 seconds. A third
  failure is stored with `status = 'error'` so it cannot block newer clips.

To restart all services, reconnect to the Pi, enter the Perch folder, and run:

**Run on the Raspberry Pi:**

```bash
docker compose restart
```

If the Blink session expires, authenticate again:

**Run on the Raspberry Pi:**

```bash
docker compose run --rm puller python auth_setup.py
```

To retry failed videos after correcting their cause, stop the classifier,
reset the failed rows, and start it again:

**Run on the Raspberry Pi:**

```bash
docker compose stop classifier
sqlite3 data/db/feeder.sqlite "UPDATE clips SET status = 'pending', attempt_count = 0, next_attempt_at = NULL, processing_started_at = NULL, note = 'manually requeued' WHERE status = 'error';"
docker compose start classifier
```

---

## Quick reference

| What | Command |
|---|---|
| Connect from your computer | `ssh <username>@<hostname>.local` |
| Enter the project folder | `cd Perch` |
| Edit settings | `nano .env` |
| Verify installation | `./scripts/verify-install.sh --build` |
| Start everything | `docker compose up -d` |
| Watch activity | `docker compose logs -f` |
| Restart everything | `docker compose restart` |
| Re-authenticate with Blink | `docker compose run --rm puller python auth_setup.py` |

If you get stuck, record the exact command you ran and the exact error message.
Those two details are enough to begin troubleshooting.
