"""Classifier watcher (Phases 4 & 5).

Polls the DB for 'pending' clips. For each: pull a few representative frames
with ffmpeg, classify them, keep the single highest-confidence identification,
publish display and thumbnail images, and record the detection. After each pass
it regenerates the static JSON the dashboard reads.
"""
from __future__ import annotations

import json
import logging
import os
import subprocess
import sys
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path

from PIL import Image

sys.path.insert(0, "/app")
from common import db, notify  # noqa: E402
from classify import BirdClassifier  # noqa: E402

logging.basicConfig(
    level=os.getenv("LOG_LEVEL", "INFO"),
    format="%(asctime)s %(levelname)s [classifier] %(message)s",
)
log = logging.getLogger("classifier")

CLIPS_DIR = Path(os.getenv("CLIPS_DIR", "/data/clips"))
DB_PATH = os.getenv("DB_PATH", "/data/db/feeder.sqlite")
WEB_DIR = Path(os.getenv("WEB_DIR", "/data/web"))
MODEL_PATH = os.getenv("MODEL_PATH", "/app/model/current/model.tflite")
LABELS_PATH = os.getenv("LABELS_PATH", "/app/model/current/labels.txt")
THRESHOLD = float(os.getenv("CONFIDENCE_THRESHOLD", "0.30"))
FRAMES_PER_CLIP = int(os.getenv("FRAMES_PER_CLIP", "4"))
WATCH_INTERVAL = int(os.getenv("WATCH_INTERVAL", "20"))
DISPLAY_WIDTH = int(os.getenv("DISPLAY_WIDTH", "1280"))
THUMB_WIDTH = int(os.getenv("THUMB_WIDTH", "480"))
MAX_CLIP_ATTEMPTS = max(1, int(os.getenv("MAX_CLIP_ATTEMPTS", "3")))
CLIP_RETRY_DELAY = max(0, int(os.getenv("CLIP_RETRY_DELAY", "60")))

IMAGES_DIR = WEB_DIR / "images"
THUMBS_DIR = WEB_DIR / "thumbs"
DATA_DIR = WEB_DIR / "data"


def ffprobe_duration(path: Path) -> float:
    try:
        out = subprocess.run(
            ["ffprobe", "-v", "error", "-show_entries", "format=duration",
             "-of", "default=nokey=1:noprint_wrappers=1", str(path)],
            capture_output=True, text=True, timeout=30,
        )
        return float(out.stdout.strip() or 0.0)
    except (subprocess.SubprocessError, ValueError):
        return 0.0


def extract_frames(path: Path, count: int, workdir: Path) -> list[Path]:
    """Grab `count` frames spread across the clip (skipping the very edges)."""
    duration = ffprobe_duration(path)
    if duration <= 0:
        timestamps = [0.0]
    else:
        # evenly spaced points at, e.g. for 4: 0.2, 0.4, 0.6, 0.8 of the clip
        timestamps = [duration * (i + 1) / (count + 1) for i in range(count)]

    frames: list[Path] = []
    for i, ts in enumerate(timestamps):
        out = workdir / f"frame_{i}.jpg"
        try:
            subprocess.run(
                ["ffmpeg", "-nostdin", "-y", "-ss", f"{ts:.2f}", "-i", str(path),
                 "-frames:v", "1", "-q:v", "2", str(out)],
                capture_output=True, timeout=60, check=True,
            )
            if out.exists():
                frames.append(out)
        except subprocess.SubprocessError as exc:
            log.warning("frame extract failed at %.2fs for %s: %s", ts, path.name, exc)
    return frames


def _atomic_jpeg(source: Image.Image, target: Path, max_width: int, quality: int) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    image = source.copy()
    if image.width > max_width:
        height = round(image.height * max_width / image.width)
        image = image.resize((max_width, height), Image.Resampling.LANCZOS)
    temporary = target.with_suffix(target.suffix + ".tmp")
    image.save(temporary, "JPEG", quality=quality, optimize=True)
    temporary.replace(target)


def publish_detection_images(frame: Path, clip_id: int) -> tuple[str, str]:
    name = f"{clip_id}.jpg"
    with Image.open(frame) as opened:
        rgb = opened.convert("RGB")
        _atomic_jpeg(rgb, IMAGES_DIR / name, DISPLAY_WIDTH, 88)
        _atomic_jpeg(rgb, THUMBS_DIR / name, THUMB_WIDTH, 82)
    return f"images/{name}", f"thumbs/{name}"


def process_clip(clf: BirdClassifier, conn, clip) -> str | None:
    clip_path = CLIPS_DIR / clip["filename"]
    if not clip_path.exists():
        db.mark_clip(conn, clip["id"], "skipped", "clip file missing")
        return None

    with tempfile.TemporaryDirectory() as td:
        frames = extract_frames(clip_path, FRAMES_PER_CLIP, Path(td))
        if not frames:
            raise RuntimeError("no frames extracted")

        best = None
        best_frame = None
        for frame in frames:
            pred = clf.classify(frame)
            if not pred.is_bird:
                continue
            if best is None or pred.confidence > best.confidence:
                best, best_frame = pred, frame

        if best is None or best.confidence < THRESHOLD:
            note = "no confident bird ID" if best is None else \
                f"below threshold ({best.common_name} {best.confidence:.2f})"
            db.mark_clip(conn, clip["id"], "done", note)
            return None

        display, thumb = publish_detection_images(best_frame, clip["id"])
        db.finish_clip_with_detection(
            conn,
            clip["id"],
            best.common_name,
            best.scientific,
            best.confidence,
            clip["captured_at"],
            thumb,
            display,
        )
        log.info("clip %s -> %s (%.2f)", clip["filename"], best.common_name, best.confidence)
        return best.common_name


def process_pending_batch(clf, conn, clips, *, processor=None) -> list[str]:
    """Process claimed clips independently so one bad file cannot block a batch."""
    processor = processor or process_clip
    new_species: list[str] = []
    for clip in clips:
        try:
            result = processor(clf, conn, clip)
            if result:
                new_species.append(result)
        except Exception as exc:  # noqa: BLE001 — clip failures are isolated here
            terminal = db.fail_clip(
                conn,
                clip["id"],
                clip["attempt_count"],
                str(exc),
                max_attempts=MAX_CLIP_ATTEMPTS,
                retry_delay_seconds=CLIP_RETRY_DELAY,
            )
            if terminal:
                log.exception(
                    "clip %s failed permanently after %d attempts",
                    clip["filename"],
                    clip["attempt_count"],
                )
                notify.failure(
                    "classifier",
                    f"gave up on {clip['filename']} after {clip['attempt_count']} attempts: {exc}",
                )
            else:
                log.warning(
                    "clip %s attempt %d failed; scheduled retry: %s",
                    clip["filename"],
                    clip["attempt_count"],
                    exc,
                )
    return new_species


def _today_count(rows) -> int:
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    return sum(1 for r in rows if (r["captured_at"] or "").startswith(today))


def regenerate_json(conn) -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    detections = db.recent_detections(conn, limit=300)
    species = db.species_tally(conn)

    payload = {
        "generated_at": db.now_iso(),
        "stats": {
            "total": db.detection_count(conn),
            "species": len(species),
            "today": _today_count(detections),
        },
        "species": [
            {"common": s["common_name"], "scientific": s["scientific"],
             "count": s["n"], "last_seen": s["last_seen"]}
            for s in species
        ],
        "detections": [
            {"id": d["id"], "common": d["common_name"], "scientific": d["scientific"],
             "confidence": round(d["confidence"], 3),
             "captured_at": d["captured_at"], "thumb": d["thumbnail"]}
            for d in detections
        ],
    }
    tmp = DATA_DIR / "detections.json.tmp"
    tmp.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    tmp.replace(DATA_DIR / "detections.json")  # atomic swap so readers never see half a file

def run() -> None:
    WEB_DIR.mkdir(parents=True, exist_ok=True)
    conn = db.connect(DB_PATH)
    recovered = db.recover_processing_clips(conn)
    if recovered:
        log.warning("recovered %d interrupted clip(s)", recovered)
    clf = BirdClassifier(MODEL_PATH, LABELS_PATH)
    log.info("model loaded (%d labels); watching every %ss", len(clf.labels), WATCH_INTERVAL)
    notify.push("classifier started", title="🐦 feeder", tags="robot")
    regenerate_json(conn)  # ensure the dashboard has a file to read on first boot

    idle_cycles = 0
    failures = 0
    while True:
        try:
            pending = db.claim_pending_clips(conn, limit=25)
            failures = 0
            new_species = process_pending_batch(clf, conn, pending)
            if pending:
                regenerate_json(conn)
                idle_cycles = 0
                if new_species:
                    notify.push("identified: " + ", ".join(new_species),
                                title="🐦 new visitor", tags="bird")
            else:
                idle_cycles += 1
                if idle_cycles % 180 == 0:  # ~ hourly at 20s cadence
                    notify.heartbeat("classifier", "idle, awaiting clips")
        except Exception as exc:  # noqa: BLE001
            failures += 1
            log.exception("watch cycle failed: %s", exc)
            notify.failure("classifier", f"cycle failed: {exc}")
            if failures >= 10:
                raise RuntimeError("classifier failed 10 consecutive cycles") from exc
        time.sleep(WATCH_INTERVAL)


if __name__ == "__main__":
    run()
