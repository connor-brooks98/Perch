from __future__ import annotations

import io
import json
import re
import time
import warnings
from dataclasses import dataclass
from pathlib import Path
from typing import Callable
from urllib.parse import quote, unquote, urljoin, urlparse

import requests
from PIL import Image, UnidentifiedImageError


INATURALIST_TAXA_URL = "https://api.inaturalist.org/v2/taxa"
WIKIMEDIA_SUMMARY_URL = "https://en.wikipedia.org/api/rest_v1/page/summary/"
REQUEST_TIMEOUT = (3, 10)
USER_AGENT = "Perch Family Journal/1.0 (local bird journal species enrichment)"
ALLOWED_IMAGE_HOSTS = {
    "inaturalist-open-data.s3.amazonaws.com",
    "static.inaturalist.org",
}
MAX_IMAGE_BYTES = 5 * 1024 * 1024
MAX_JSON_BYTES = 1024 * 1024
IMAGE_CHUNK_BYTES = 64 * 1024
MAX_REDIRECTS = 3
MAX_REFERENCE_WIDTH = 960
MAX_IMAGE_DIMENSION = 12_000
MAX_IMAGE_PIXELS = 40_000_000


@dataclass(frozen=True)
class PhotoMetadata:
    url: str
    attribution: str
    creator: str
    license_code: str


@dataclass(frozen=True)
class TaxonMatch:
    taxon_id: int
    scientific_name: str
    wikipedia_url: str | None
    photo: PhotoMetadata | None


@dataclass(frozen=True)
class PageSummary:
    extract: str
    page_url: str


@dataclass(frozen=True)
class ReferenceImage:
    path: Path
    creator: str
    license_code: str
    source_url: str


class RateGate:
    def __init__(
        self,
        *,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] = time.sleep,
        interval: float = 1.0,
    ) -> None:
        self._clock = clock
        self._sleep = sleep
        self._interval = interval
        self._last_request: float | None = None

    def wait(self) -> None:
        now = self._clock()
        if self._last_request is not None:
            remaining = self._interval - (now - self._last_request)
            if remaining > 0:
                self._sleep(remaining)
        self._last_request = self._clock()


class ProviderClient:
    def __init__(
        self,
        *,
        session: requests.Session | None = None,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self.session = session or requests.Session()
        self.session.headers.update({"User-Agent": USER_AGENT})
        self._rate_gate = RateGate(clock=clock, sleep=sleep)

    def match_species(self, scientific_name: str) -> TaxonMatch | None:
        fields = (
            "id,name,rank,iconic_taxon_name,wikipedia_url,default_photo"
        )
        try:
            payload = self._request_json(
                INATURALIST_TAXA_URL,
                params={"q": scientific_name, "rank": "species", "fields": fields},
            )
        except (requests.RequestException, RuntimeError, ValueError, TypeError):
            return None

        results = payload.get("results") if isinstance(payload, dict) else None
        if not isinstance(results, list):
            return None

        expected_name = scientific_name.casefold()
        for result in results:
            if not isinstance(result, dict):
                continue
            name = result.get("name")
            if (
                not isinstance(name, str)
                or name.casefold() != expected_name
                or result.get("rank") != "species"
                or result.get("iconic_taxon_name") != "Aves"
                or not isinstance(result.get("id"), int)
            ):
                continue
            wikipedia_url = result.get("wikipedia_url")
            if not self._allowed_wikipedia_page_url(wikipedia_url):
                wikipedia_url = None
            return TaxonMatch(
                taxon_id=result["id"],
                scientific_name=name,
                wikipedia_url=wikipedia_url,
                photo=self._validated_photo(result.get("default_photo")),
            )
        return None

    def fetch_summary(self, wikipedia_url: str) -> PageSummary | None:
        if not self._allowed_wikipedia_page_url(wikipedia_url):
            return None
        parsed = urlparse(wikipedia_url)
        prefix = "/wiki/"
        title = unquote(parsed.path[len(prefix) :])
        summary_url = WIKIMEDIA_SUMMARY_URL + quote(title, safe="")
        try:
            payload = self._request_json(summary_url)
        except (requests.RequestException, RuntimeError, ValueError, TypeError):
            return None
        if not isinstance(payload, dict):
            return None
        extract = payload.get("extract")
        content_urls = payload.get("content_urls")
        if not isinstance(extract, str) or not extract.strip():
            return None
        if not isinstance(content_urls, dict):
            return None
        desktop = content_urls.get("desktop")
        page_url = desktop.get("page") if isinstance(desktop, dict) else None
        if not self._allowed_wikipedia_page_url(page_url):
            return None
        return PageSummary(extract=extract, page_url=page_url)

    def download_reference_image(
        self, photo: PhotoMetadata, destination: str | Path
    ) -> ReferenceImage | None:
        if not self._photo_is_usable(photo) or not self._allowed_image_url(photo.url):
            return None

        response = None
        url = photo.url
        try:
            for redirect_count in range(MAX_REDIRECTS + 1):
                response = self._get(
                    url,
                    stream=True,
                    allow_redirects=False,
                )
                if response.status_code not in {301, 302, 303, 307, 308}:
                    response.raise_for_status()
                    break
                location = response.headers.get("Location")
                response.close()
                response = None
                if redirect_count == MAX_REDIRECTS or not location:
                    return None
                url = urljoin(url, location)
                if not self._allowed_image_url(url):
                    return None
            if response is None:
                return None

            content = io.BytesIO()
            total = 0
            for chunk in response.iter_content(chunk_size=IMAGE_CHUNK_BYTES):
                if not chunk:
                    continue
                total += len(chunk)
                if total > MAX_IMAGE_BYTES:
                    return None
                content.write(chunk)

            destination_path = Path(destination)
            temporary_path = destination_path.with_suffix(
                destination_path.suffix + ".tmp"
            )
            destination_path.parent.mkdir(parents=True, exist_ok=True)
            try:
                content.seek(0)
                with warnings.catch_warnings():
                    warnings.simplefilter("error", Image.DecompressionBombWarning)
                    with Image.open(content) as source:
                        width, height = source.size
                        if (
                            width < 1
                            or height < 1
                            or width > MAX_IMAGE_DIMENSION
                            or height > MAX_IMAGE_DIMENSION
                            or width * height > MAX_IMAGE_PIXELS
                        ):
                            return None
                        source.load()
                        image = source.convert("RGB")
                if image.width > MAX_REFERENCE_WIDTH:
                    height = max(
                        1, round(image.height * MAX_REFERENCE_WIDTH / image.width)
                    )
                    image = image.resize(
                        (MAX_REFERENCE_WIDTH, height), Image.Resampling.LANCZOS
                    )
                image.save(temporary_path, format="JPEG", quality=85)
                temporary_path.replace(destination_path)
            except (
                OSError,
                ValueError,
                UnidentifiedImageError,
                Image.DecompressionBombError,
                Image.DecompressionBombWarning,
            ):
                temporary_path.unlink(missing_ok=True)
                return None
            return ReferenceImage(
                path=destination_path,
                creator=photo.creator,
                license_code=photo.license_code,
                source_url=photo.url,
            )
        except (requests.RequestException, RuntimeError, ValueError, TypeError):
            return None
        finally:
            if response is not None:
                response.close()

    def _get(self, url: str, **kwargs):
        self._rate_gate.wait()
        kwargs.setdefault("timeout", REQUEST_TIMEOUT)
        return self.session.get(url, **kwargs)

    def _request_json(self, url: str, **kwargs) -> object | None:
        response = None
        try:
            response = self._get(url, stream=True, **kwargs)
            response.raise_for_status()
            declared_length = response.headers.get("Content-Length")
            if declared_length is not None:
                length = int(declared_length)
                if length < 0 or length > MAX_JSON_BYTES:
                    return None

            content = bytearray()
            for chunk in response.iter_content(chunk_size=IMAGE_CHUNK_BYTES):
                if not chunk:
                    continue
                if len(content) + len(chunk) > MAX_JSON_BYTES:
                    return None
                content.extend(chunk)
            return json.loads(content.decode("utf-8"))
        finally:
            if response is not None:
                response.close()

    @staticmethod
    def _validated_photo(value: object) -> PhotoMetadata | None:
        if not isinstance(value, dict):
            return None
        url = value.get("medium_url")
        attribution = value.get("attribution")
        license_code = value.get("license_code")
        if not all(
            isinstance(item, str) and item.strip()
            for item in (url, attribution, license_code)
        ):
            return None
        creator = re.split(r",\s*", attribution, maxsplit=1)[0]
        creator = re.sub(r"^\s*(?:\(c\)|©)\s*", "", creator, flags=re.I).strip()
        if not creator:
            return None
        if not ProviderClient._allowed_image_url(url):
            return None
        return PhotoMetadata(
            url=url,
            attribution=attribution,
            creator=creator,
            license_code=license_code,
        )

    @staticmethod
    def _photo_is_usable(photo: PhotoMetadata) -> bool:
        return all(
            isinstance(value, str) and value.strip()
            for value in (
                photo.url,
                photo.attribution,
                photo.creator,
                photo.license_code,
            )
        )

    @staticmethod
    def _allowed_image_url(url: str) -> bool:
        return ProviderClient._allowed_https_url(
            url, allowed_hosts=ALLOWED_IMAGE_HOSTS
        )

    @staticmethod
    def _allowed_wikipedia_page_url(url: object) -> bool:
        return ProviderClient._allowed_https_url(
            url,
            allowed_hosts={"en.wikipedia.org"},
            path_prefix="/wiki/",
        )

    @staticmethod
    def _allowed_https_url(
        url: object, *, allowed_hosts: set[str], path_prefix: str | None = None
    ) -> bool:
        if (
            not isinstance(url, str)
            or not url
            or any(ord(char) < 0x20 or ord(char) == 0x7F for char in url)
            or re.search(r"%(?![0-9A-Fa-f]{2})", url)
        ):
            return False
        try:
            parsed = urlparse(url)
            port = parsed.port
        except ValueError:
            return False
        return (
            parsed.scheme == "https"
            and parsed.hostname in allowed_hosts
            and parsed.username is None
            and parsed.password is None
            and port in (None, 443)
            and (
                path_prefix is None
                or (
                    parsed.path.startswith(path_prefix)
                    and len(parsed.path) > len(path_prefix)
                )
            )
        )
