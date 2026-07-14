"""One-time Blink authentication (Phase 2).

Run this ONCE, interactively, to log the dedicated feeder Blink account in and
persist a credentials file the puller can reuse headlessly afterwards.

    docker compose run --rm puller python auth_setup.py

Blink sends a 2FA code on login; enter it when prompted. The resulting creds
file lands on the persistent /data volume so the token survives container
restarts.
"""
from __future__ import annotations

import asyncio
import os
import sys

from aiohttp import ClientSession
from blinkpy.auth import Auth, BlinkTwoFARequiredError
from blinkpy.blinkpy import Blink

CREDS_PATH = os.getenv("BLINK_CREDS", "/data/blink/creds.json")
USERNAME = os.getenv("BLINK_USERNAME", "")
PASSWORD = os.getenv("BLINK_PASSWORD", "")


async def main() -> int:
    if not USERNAME or not PASSWORD:
        print("Set BLINK_USERNAME and BLINK_PASSWORD in your .env first.", file=sys.stderr)
        return 2

    os.makedirs(os.path.dirname(CREDS_PATH), exist_ok=True)

    async with ClientSession() as session:
        blink = Blink(session=session)
        blink.auth = Auth(
            {"username": USERNAME, "password": PASSWORD},
            no_prompt=True,
            session=session,
        )
        try:
            started = await blink.start()
        except BlinkTwoFARequiredError:
            code = input("Enter the 2FA code Blink just sent you: ").strip()
            started = await blink.send_2fa_code(code)

        if not started:
            print(
                "\nBlink rejected the login or verification code. This is usually one of:\n"
                "  - BLINK_USERNAME / BLINK_PASSWORD in .env don't match a real Blink login\n"
                "  - This account hasn't verified its email yet (check the Blink welcome email)\n"
                "  - The 2FA code expired or was entered incorrectly\n"
                "  - Blink is temporarily rate-limiting this account/IP after repeated attempts\n"
                "    (wait 15-20 minutes, then try again)\n"
                "Confirm the same email/password logs in from the Blink app itself, fix "
                ".env if needed, then re-run this command.",
                file=sys.stderr,
            )
            return 1

        await blink.refresh()
        cameras = list(blink.cameras.keys())
        if not cameras:
            print("Authenticated, but no cameras were found on this account.", file=sys.stderr)
            print("Add the feeder camera in the Blink app, then re-run.", file=sys.stderr)
            return 1

        await blink.save(CREDS_PATH)
        print(f"\nSaved credentials to {CREDS_PATH}")
        print("Cameras on this account:")
        for name in cameras:
            print(f"  • {name}")
        print("\nCopy the exact feeder camera name into CAMERA_NAME in your .env.")
        return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
