"""Fire-and-forget push notifications via ntfy (Phase 7 heartbeat/failure ping).

Set NTFY_URL to a full topic URL, e.g. https://ntfy.sh/connor-birdfeeder-9f3a
Leave it unset and every call becomes a silent no-op, so the pipeline runs
fine without monitoring configured.
"""
from __future__ import annotations

import logging
import os

import requests

log = logging.getLogger("notify")

NTFY_URL = os.getenv("NTFY_URL", "").strip()
_TIMEOUT = 8


def push(message: str, *, title: str | None = None, priority: str = "default",
         tags: str | None = None) -> None:
    """Send a notification. Never raises — monitoring must not crash the app."""
    if not NTFY_URL:
        return
    headers = {"Priority": priority}
    if title:
        headers["Title"] = title
    if tags:
        headers["Tags"] = tags
    try:
        requests.post(NTFY_URL, data=message.encode("utf-8"),
                      headers=headers, timeout=_TIMEOUT)
    except Exception as exc:  # noqa: BLE001 — deliberately swallow
        log.warning("ntfy push failed: %s", exc)


def heartbeat(service: str, detail: str = "") -> None:
    push(f"{service} ok {detail}".strip(), title="🐦 feeder heartbeat", tags="green_circle")


def failure(service: str, detail: str) -> None:
    push(f"{service}: {detail}", title="⚠️ feeder problem",
         priority="high", tags="rotating_light")
