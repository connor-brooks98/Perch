"""Filesystem boundary for publishing completed Blink downloads."""
from __future__ import annotations

from pathlib import Path


def publish_downloaded_clips(incoming_dir: Path, clips_dir: Path) -> int:
    """Atomically expose new MP4s without replacing known-good final files."""
    published = 0
    for source in sorted(incoming_dir.glob("*.mp4")):
        destination = clips_dir / source.name
        if destination.exists():
            source.unlink()
            continue
        source.replace(destination)
        published += 1
    return published
