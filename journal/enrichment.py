"""Bounded, asynchronous species-profile enrichment cache."""
from __future__ import annotations

import hashlib
import logging
import threading
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from queue import Full, Queue
from typing import Callable

import requests

from common import db
from journal.providers import ProviderClient, ProviderFailure


FRESH_FOR = timedelta(days=90)
RETRY_DELAYS = {
    "not_found": timedelta(hours=24),
    "throttled": timedelta(hours=1),
    "timeout": timedelta(minutes=15),
    "malformed": timedelta(hours=6),
    "unavailable": timedelta(minutes=15),
}
_SENTINEL = object()
log = logging.getLogger("journal.enrichment")


EnrichmentFailure = ProviderFailure


@dataclass(frozen=True)
class _Job:
    species_key: str
    common_name: str
    scientific_name: str


class EnrichmentService:
    def __init__(
        self,
        db_path: str | Path,
        image_dir: str | Path,
        *,
        provider: ProviderClient | None = None,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self.db_path = Path(db_path)
        self.image_dir = Path(image_dir)
        self.provider = (
            provider if provider is not None else ProviderClient(raise_failures=True)
        )
        self._clock = clock or (lambda: datetime.now(timezone.utc))
        self._queue: Queue[_Job | object] = Queue(maxsize=100)
        self._queued_keys: set[str] = set()
        self._queued_lock = threading.Lock()
        self._lifecycle_lock = threading.Lock()
        self._thread: threading.Thread | None = None
        self._stopping = False

    def get(self, species_key: str) -> dict | None:
        if not isinstance(species_key, str) or not species_key:
            return None
        conn = db.connect(self.db_path)
        try:
            row = conn.execute(
                "SELECT * FROM species_profiles WHERE species_key = ?",
                (species_key,),
            ).fetchone()
        finally:
            conn.close()
        if row is None:
            return {"status": "pending"}

        now = self._now()
        retry_after = self._parse_time(row["retry_after"])
        if row["error_category"] in RETRY_DELAYS and retry_after and retry_after > now:
            return {
                "status": "failed",
                "error_category": row["error_category"],
                "retry_after": row["retry_after"],
            }

        fetched_at = self._parse_time(row["fetched_at"])
        if fetched_at is None:
            return {"status": "pending"}
        result = {key: row[key] for key in row.keys()}
        result["status"] = "ready" if now - fetched_at < FRESH_FOR else "stale"
        return result

    def schedule(
        self, species_key: str, common_name: str, scientific_name: str
    ) -> bool:
        if not all(
            isinstance(value, str) and value.strip()
            for value in (species_key, common_name, scientific_name)
        ):
            return False
        current = self.get(species_key)
        if current is None or current["status"] not in {"pending", "stale"}:
            return False
        job = _Job(
            species_key=species_key,
            common_name=common_name.strip(),
            scientific_name=scientific_name.strip(),
        )
        with self._lifecycle_lock:
            if self._stopping:
                return False
            with self._queued_lock:
                if species_key in self._queued_keys:
                    return False
                self._queued_keys.add(species_key)
            try:
                self._queue.put_nowait(job)
            except Full:
                with self._queued_lock:
                    self._queued_keys.discard(species_key)
                return False
        return True

    def start(self) -> None:
        with self._lifecycle_lock:
            if self._thread is not None and self._thread.is_alive():
                return
            self._stopping = False
            self._thread = threading.Thread(
                target=self._run,
                name="species-enrichment",
                daemon=True,
            )
            self._thread.start()

    def stop(self) -> None:
        with self._lifecycle_lock:
            thread = self._thread
            if thread is None or not thread.is_alive():
                self._thread = None
                self._stopping = False
                return
            self._stopping = True
            self._queue.put(_SENTINEL)
        thread.join()
        with self._lifecycle_lock:
            if self._thread is thread:
                self._thread = None
            self._stopping = False

    def _run(self) -> None:
        while True:
            item = self._queue.get()
            try:
                if item is _SENTINEL:
                    return
                assert isinstance(item, _Job)
                try:
                    self._process(item)
                except Exception:
                    log.error(
                        "species_enrichment_failure category=cache species_key=%s",
                        item.species_key,
                    )
            finally:
                if isinstance(item, _Job):
                    with self._queued_lock:
                        self._queued_keys.discard(item.species_key)
                self._queue.task_done()

    def _process(self, job: _Job) -> None:
        try:
            match = self.provider.match_species(job.scientific_name)
            if match is None:
                raise EnrichmentFailure("not_found")

            introduction = None
            wikipedia_url = None
            if match.wikipedia_url:
                summary = self.provider.fetch_summary(match.wikipedia_url)
                if summary is None:
                    raise EnrichmentFailure("malformed")
                introduction = summary.extract
                wikipedia_url = summary.page_url

            reference_image = None
            image_source_url = None
            image_creator = None
            image_license = None
            if match.photo:
                filename = self._image_filename(job.species_key)
                image = self.provider.download_reference_image(
                    match.photo, self.image_dir / filename
                )
                if image is None:
                    raise EnrichmentFailure("malformed")
                reference_image = filename
                image_source_url = image.source_url
                image_creator = image.creator
                image_license = image.license_code

            self._store_success(
                job.species_key,
                inat_taxon_id=match.taxon_id,
                introduction=introduction,
                inat_url=f"https://www.inaturalist.org/taxa/{match.taxon_id}",
                wikipedia_url=wikipedia_url,
                reference_image=reference_image,
                image_source_url=image_source_url,
                image_creator=image_creator,
                image_license=image_license,
            )
        except BaseException as exc:
            if isinstance(exc, (KeyboardInterrupt, SystemExit)):
                raise
            category = self._failure_category(exc)
            self._store_failure(job.species_key, category)
            log.warning(
                "species_enrichment_failure category=%s species_key=%s",
                category,
                job.species_key,
            )

    def _store_success(self, species_key: str, **profile: object) -> None:
        now = self._format_time(self._now())
        conn = db.connect(self.db_path)
        try:
            with conn:
                conn.execute(
                    "INSERT INTO species_profiles("
                    "species_key, inat_taxon_id, introduction, inat_url, wikipedia_url, "
                    "reference_image, image_source_url, image_creator, image_license, "
                    "fetched_at, retry_after, error_category, updated_at) "
                    "VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, NULL, NULL, ?) "
                    "ON CONFLICT(species_key) DO UPDATE SET "
                    "inat_taxon_id=excluded.inat_taxon_id, introduction=excluded.introduction, "
                    "inat_url=excluded.inat_url, wikipedia_url=excluded.wikipedia_url, "
                    "reference_image=excluded.reference_image, "
                    "image_source_url=excluded.image_source_url, "
                    "image_creator=excluded.image_creator, image_license=excluded.image_license, "
                    "fetched_at=excluded.fetched_at, retry_after=NULL, error_category=NULL, "
                    "updated_at=excluded.updated_at",
                    (
                        species_key,
                        profile["inat_taxon_id"],
                        profile["introduction"],
                        profile["inat_url"],
                        profile["wikipedia_url"],
                        profile["reference_image"],
                        profile["image_source_url"],
                        profile["image_creator"],
                        profile["image_license"],
                        now,
                        now,
                    ),
                )
        finally:
            conn.close()

    def _store_failure(self, species_key: str, category: str) -> None:
        now = self._now()
        updated_at = self._format_time(now)
        retry_after = self._format_time(now + RETRY_DELAYS[category])
        conn = db.connect(self.db_path)
        try:
            with conn:
                conn.execute(
                    "INSERT INTO species_profiles("
                    "species_key, retry_after, error_category, updated_at) VALUES(?, ?, ?, ?) "
                    "ON CONFLICT(species_key) DO UPDATE SET "
                    "retry_after=excluded.retry_after, error_category=excluded.error_category, "
                    "updated_at=excluded.updated_at",
                    (species_key, retry_after, category, updated_at),
                )
        finally:
            conn.close()

    @staticmethod
    def _failure_category(exc: BaseException) -> str:
        if isinstance(exc, ProviderFailure):
            return exc.category
        if isinstance(exc, (requests.Timeout, TimeoutError)):
            return "timeout"
        if isinstance(exc, requests.HTTPError):
            status = exc.response.status_code if exc.response is not None else None
            if status == 429:
                return "throttled"
            if status == 404:
                return "not_found"
            return "unavailable"
        if isinstance(exc, (ValueError, TypeError, UnicodeError)):
            return "malformed"
        return "unavailable"

    def _now(self) -> datetime:
        value = self._clock()
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc)

    @staticmethod
    def _parse_time(value: object) -> datetime | None:
        if not isinstance(value, str) or not value:
            return None
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(timezone.utc)

    @staticmethod
    def _format_time(value: datetime) -> str:
        return value.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    @staticmethod
    def _image_filename(species_key: str) -> str:
        digest = hashlib.sha256(species_key.encode("utf-8")).hexdigest()[:24]
        return f"{digest}-{uuid.uuid4().hex}.jpg"
