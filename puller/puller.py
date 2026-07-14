"""Puller service (Phases 2 & 4).

Every POLL_INTERVAL seconds: refresh the Blink session, download any motion
clips newer than our saved cursor into the shared clips volume, and register
each new file in SQLite as a 'pending' clip for the classifier to pick up.

Deliberately dumb and restartable: all state lives in the DB and on disk, so
`restart: unless-stopped` is enough to survive crashes and reboots.
"""
from __future__ import annotations

import asyncio
import logging
import os
import re
import sys
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

from aiohttp import ClientSession
from blinkpy.auth import Auth
from blinkpy.blinkpy import Blink
from blinkpy.helpers.util import json_load

sys.path.insert(0, "/app")  # so `common` resolves inside the container
from common import db, notify  # noqa: E402
from common.clip_files import publish_downloaded_clips  # noqa: E402

logging.basicConfig(
    level=os.getenv("LOG_LEVEL", "INFO"),
    format="%(asctime)s %(levelname)s [puller] %(message)s",
)
log = logging.getLogger("puller")

CREDS_PATH = os.getenv("BLINK_CREDS", "/data/blink/creds.json")
CLIPS_DIR = Path(os.getenv("CLIPS_DIR", "/data/clips"))
DB_PATH = os.getenv("DB_PATH", "/data/db/feeder.sqlite")
CAMERA_NAME = os.getenv("CAMERA_NAME", "all").strip() or "all"
POLL_INTERVAL = max(60, int(os.getenv("POLL_INTERVAL", "300")))
RETAIN_DAYS = int(os.getenv("RETAIN_DAYS", "14"))
HEARTBEAT_EVERY = int(os.getenv("HEARTBEAT_EVERY", "12"))  # cycles between "ok" pings

# Matches blinkpy's to_alphanumeric(created_at): FeederCam_20240105T1322090000.mp4
TS_RE = re.compile(r"(\d{8})T(\d{6})")


def parse_captured_at(filename: str, fallback_path: Path) -> str:
    m = TS_RE.search(filename)
    if m:
        try:
            dt = datetime.strptime(m.group(1) + m.group(2), "%Y%m%d%H%M%S")
            return dt.replace(tzinfo=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        except ValueError:
            pass
    mtime = datetime.fromtimestamp(fallback_path.stat().st_mtime, tz=timezone.utc)
    return mtime.strftime("%Y-%m-%dT%H:%M:%SZ")


async def make_blink(session: ClientSession) -> Blink:
    if not Path(CREDS_PATH).exists():
        raise FileNotFoundError(
            f"No Blink credentials at {CREDS_PATH}. Run auth_setup.py first."
        )
    blink = Blink(session=session)
    blink.auth = Auth(await json_load(CREDS_PATH), no_prompt=True, session=session)
    await blink.start()
    await blink.refresh()
    # blinkpy rotates the auth token (and stores the trusted-device id) in memory.
    # Persist it now so the on-disk creds don't go stale — otherwise a restart
    # after long uptime can re-trigger 2FA, which is unrecoverable headless.
    await blink.save(CREDS_PATH)
    return blink


def register_new_clips(conn) -> int:
    """Scan the clips dir and insert any file not already tracked."""
    added = 0
    for path in sorted(CLIPS_DIR.glob("*.mp4")):
        if db.clip_exists(conn, path.name):
            continue
        captured = parse_captured_at(path.name, path)
        camera = path.name.rsplit("_", 1)[0] if "_" in path.name else CAMERA_NAME
        db.add_clip(conn, path.name, camera, captured)
        added += 1
        log.info("new clip %s (captured %s)", path.name, captured)
    return added


def prune_old_clips(conn) -> None:
    """Delete raw clip files past the retention window (DB rows are kept)."""
    if RETAIN_DAYS <= 0:
        return
    cutoff = datetime.now(timezone.utc) - timedelta(days=RETAIN_DAYS)
    for path in CLIPS_DIR.glob("*.mp4"):
        try:
            old = datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc) < cutoff
            terminal = db.clip_status(conn, path.name) in {"done", "error", "skipped"}
            if old and terminal:
                path.unlink()
                log.info("pruned old clip %s", path.name)
        except OSError:
            pass


async def poll_once(blink: Blink, conn) -> int:
    await blink.refresh()

    last_since = db.get_state(conn, "last_since")
    if not last_since:
        last_since = (datetime.now(timezone.utc) - timedelta(hours=1)).strftime("%Y/%m/%d %H:%M")

    # download_videos is the most version-fragile blinkpy call. Let failures
    # bubble to the outer loop so they trigger ntfy + session rebuild instead
    # of being mistaken for a healthy "no new clips" cycle.
    try:
        # Blink writes into a per-cycle staging directory. Only a successfully
        # completed download call publishes MP4s into the classifier-visible
        # directory, using same-filesystem atomic renames.
        with tempfile.TemporaryDirectory(prefix=".incoming-", dir=CLIPS_DIR) as incoming:
            await blink.download_videos(
                incoming,
                since=last_since,
                camera=CAMERA_NAME,
                stop=20,
                delay=1,
            )
            publish_downloaded_clips(Path(incoming), CLIPS_DIR)
    except TypeError as exc:
        raise RuntimeError(
            "blinkpy download_videos() signature/behavior may have changed; "
            "review the pinned blinkpy version before unattended use"
        ) from exc
    except Exception as exc:  # noqa: BLE001
        raise RuntimeError(f"Blink video download failed: {exc}") from exc

    added = register_new_clips(conn)

    # Advance the cursor to just before the newest clip so we never miss one
    # that landed mid-cycle, while still moving forward over time.
    newest = conn.execute("SELECT MAX(captured_at) AS m FROM clips").fetchone()["m"]
    if newest:
        dt = datetime.strptime(newest, "%Y-%m-%dT%H:%M:%SZ") - timedelta(minutes=2)
        db.set_state(conn, "last_since", dt.strftime("%Y/%m/%d %H:%M"))

    prune_old_clips(conn)
    return added


async def run() -> None:
    CLIPS_DIR.mkdir(parents=True, exist_ok=True)
    conn = db.connect(DB_PATH)
    cycle = 0

    async with ClientSession() as session:
        blink = await make_blink(session)
        log.info("authenticated; polling every %ss for camera '%s'", POLL_INTERVAL, CAMERA_NAME)
        notify.push("puller started", title="🐦 feeder", tags="hatching_chick")

        while True:
            cycle += 1
            try:
                added = await poll_once(blink, conn)
                if added:
                    notify.push(f"pulled {added} new clip(s)", title="🐦 feeder", tags="camera")
                elif cycle % HEARTBEAT_EVERY == 0:
                    notify.heartbeat("puller", f"cycle {cycle}, no new clips")
                    # Keep on-disk creds fresh even without a restart.
                    try:
                        await blink.save(CREDS_PATH)
                    except Exception:  # noqa: BLE001
                        log.warning("could not persist refreshed creds", exc_info=True)
            except FileNotFoundError as exc:
                log.error("%s", exc)
                notify.failure("puller", str(exc))
                # Under `restart: unless-stopped` a bare return would exit(0) and
                # respawn within seconds, spamming ntfy. Back off before exiting.
                await asyncio.sleep(60)
                return
            except Exception as exc:  # noqa: BLE001
                log.exception("poll failed: %s", exc)
                notify.failure("puller", f"poll failed: {exc}")
                # Try to rebuild the session in case the token expired.
                try:
                    blink = await make_blink(session)
                except Exception as reauth:  # noqa: BLE001
                    log.error("re-auth failed: %s", reauth)
            await asyncio.sleep(POLL_INTERVAL)


if __name__ == "__main__":
    asyncio.run(run())
