from __future__ import annotations

import io
import json
import struct
import tempfile
import unittest
import zlib
from pathlib import Path
from unittest import mock

from PIL import Image

from journal.providers import (
    MAX_IMAGE_BYTES,
    PhotoMetadata,
    ProviderClient,
    RateGate,
)


MAX_JSON_BYTES = 1024 * 1024


INAT_MATCH = {
    "results": [
        {
            "id": 123,
            "name": "Cyanocitta cristata",
            "rank": "species",
            "iconic_taxon_name": "Aves",
            "wikipedia_url": "https://en.wikipedia.org/wiki/Blue_jay",
            "default_photo": {
                "medium_url": "https://inaturalist-open-data.s3.amazonaws.com/photos/1/medium.jpg",
                "attribution": "(c) Jane Birder, CC BY 4.0",
                "license_code": "cc-by",
            },
        }
    ]
}


_UNSET = object()


class FakeResponse:
    def __init__(self, *, json_data=_UNSET, chunks=None, status=200, headers=None):
        self._json_data = json_data
        if chunks is None and json_data is not _UNSET:
            chunks = [json.dumps(json_data).encode("utf-8")]
        self._chunks = chunks or []
        self.status_code = status
        self.headers = headers or {}

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")

    def json(self):
        raise AssertionError("provider JSON must be decoded from a bounded stream")

    def iter_content(self, chunk_size):
        if callable(self._chunks):
            return self._chunks(chunk_size)
        return iter(self._chunks)

    def close(self):
        pass


class FakeSession:
    def __init__(self, responses):
        self.headers = {}
        self.responses = list(responses)
        self.calls = []

    def get(self, url, **kwargs):
        self.calls.append((url, kwargs))
        if not self.responses:
            raise AssertionError("unexpected network request")
        return self.responses.pop(0)


def jpeg_bytes(size=(20, 10)):
    output = io.BytesIO()
    Image.new("RGB", size, "royalblue").save(output, format="JPEG")
    return output.getvalue()


def compressed_png_header(width, height):
    def chunk(kind, data):
        checksum = zlib.crc32(kind + data) & 0xFFFFFFFF
        return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", checksum)

    header = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", header)
        + chunk(b"IDAT", zlib.compress(b""))
        + chunk(b"IEND", b"")
    )


class RateGateTests(unittest.TestCase):
    def test_wait_keeps_calls_one_second_apart(self):
        now = [10.0]
        sleeps = []

        def sleep(seconds):
            sleeps.append(seconds)
            now[0] += seconds

        gate = RateGate(clock=lambda: now[0], sleep=sleep)
        gate.wait()
        now[0] += 0.25
        gate.wait()

        self.assertEqual(sleeps, [0.75])


class ProviderMatchTests(unittest.TestCase):
    def make_client(self, payload=INAT_MATCH):
        session = FakeSession([FakeResponse(json_data=payload)])
        return ProviderClient(session=session, clock=lambda: 0, sleep=lambda _: None), session

    def test_accepts_only_exact_species_rank_bird_and_retains_photo_metadata(self):
        client, _ = self.make_client()
        match = client.match_species("Cyanocitta cristata")

        self.assertEqual(match.taxon_id, 123)
        self.assertEqual(match.scientific_name, "Cyanocitta cristata")
        self.assertEqual(match.wikipedia_url, "https://en.wikipedia.org/wiki/Blue_jay")
        self.assertEqual(match.photo.creator, "Jane Birder")
        self.assertEqual(match.photo.license_code, "cc-by")

    def test_rejects_fuzzy_genus_and_non_bird_results(self):
        for result in (
            {**INAT_MATCH["results"][0], "name": "Cyanocitta stelleri"},
            {**INAT_MATCH["results"][0], "rank": "genus"},
            {**INAT_MATCH["results"][0], "iconic_taxon_name": "Mammalia"},
        ):
            with self.subTest(result=result):
                client, _ = self.make_client({"results": [result]})
                self.assertIsNone(client.match_species("Cyanocitta cristata"))

    def test_uses_explicit_fields_query_timeout_and_descriptive_user_agent(self):
        client, session = self.make_client()
        client.match_species("Cyanocitta cristata")

        url, kwargs = session.calls[0]
        self.assertEqual(url, "https://api.inaturalist.org/v2/taxa")
        self.assertEqual(kwargs["timeout"], (3, 10))
        self.assertEqual(kwargs["params"]["q"], "Cyanocitta cristata")
        self.assertEqual(kwargs["params"]["rank"], "species")
        self.assertEqual(
            set(kwargs["params"]["fields"].split(",")),
            {"id", "name", "rank", "iconic_taxon_name", "wikipedia_url", "default_photo"},
        )
        self.assertIn("Perch", session.headers["User-Agent"])
        self.assertNotIn("python-requests", session.headers["User-Agent"].lower())

    def test_rejects_photo_without_attribution_or_license(self):
        for missing in ("attribution", "license_code"):
            photo = dict(INAT_MATCH["results"][0]["default_photo"])
            photo.pop(missing)
            result = {**INAT_MATCH["results"][0], "default_photo": photo}
            client, _ = self.make_client({"results": [result]})

            self.assertIsNone(client.match_species("Cyanocitta cristata").photo)

    def test_rejects_json_declared_over_transport_limit_without_reading(self):
        def fail_if_read(_chunk_size):
            raise AssertionError("oversized response body was read")

        response = FakeResponse(
            chunks=fail_if_read,
            headers={"Content-Length": str(MAX_JSON_BYTES + 1)},
        )
        session = FakeSession([response])
        client = ProviderClient(session=session, clock=lambda: 0, sleep=lambda _: None)

        self.assertIsNone(client.match_species("Cyanocitta cristata"))
        self.assertTrue(session.calls[0][1]["stream"])

    def test_rejects_json_stream_that_crosses_transport_limit(self):
        response = FakeResponse(chunks=[b"{" + b"x" * MAX_JSON_BYTES])
        session = FakeSession([response])
        client = ProviderClient(session=session, clock=lambda: 0, sleep=lambda _: None)

        self.assertIsNone(client.match_species("Cyanocitta cristata"))

    def test_discards_unsafe_wikipedia_and_photo_urls_from_match(self):
        unsafe_urls = (
            "javascript:alert(1)",
            "http://en.wikipedia.org/wiki/Blue_jay",
            "https://example.com/wiki/Blue_jay",
            "https://user:secret@en.wikipedia.org/wiki/Blue_jay",
            "https://en.wikipedia.org:444/wiki/Blue_jay",
            "https://en.wikipedia.org/not-wiki/Blue_jay",
            "https://[broken/wiki/Blue_jay",
            "https://en.wikipedia.org/wiki/%ZZ",
        )
        for unsafe_url in unsafe_urls:
            with self.subTest(wikipedia_url=unsafe_url):
                result = {**INAT_MATCH["results"][0], "wikipedia_url": unsafe_url}
                client, _ = self.make_client({"results": [result]})
                self.assertIsNone(
                    client.match_species("Cyanocitta cristata").wikipedia_url
                )

        unsafe_photo_urls = (
            "javascript:alert(1)",
            "http://static.inaturalist.org/photos/1.jpg",
            "https://example.com/photos/1.jpg",
            "https://user:secret@static.inaturalist.org/photos/1.jpg",
            "https://static.inaturalist.org:444/photos/1.jpg",
            "https://[broken/photos/1.jpg",
            "https://static.inaturalist.org/photos/%ZZ",
        )
        for unsafe_url in unsafe_photo_urls:
            with self.subTest(photo_url=unsafe_url):
                photo = {
                    **INAT_MATCH["results"][0]["default_photo"],
                    "medium_url": unsafe_url,
                }
                result = {**INAT_MATCH["results"][0], "default_photo": photo}
                client, _ = self.make_client({"results": [result]})
                self.assertIsNone(client.match_species("Cyanocitta cristata").photo)


class SummaryTests(unittest.TestCase):
    def test_encodes_title_and_retains_only_plain_text_and_canonical_url(self):
        response = {
            "extract": "A blue jay is a passerine bird.",
            "extract_html": "<p>unsafe</p>",
            "content_urls": {"desktop": {"page": "https://en.wikipedia.org/wiki/Blue_jay"}},
        }
        session = FakeSession([FakeResponse(json_data=response)])
        client = ProviderClient(session=session, clock=lambda: 0, sleep=lambda _: None)

        summary = client.fetch_summary("https://en.wikipedia.org/wiki/Blue%20jay_(bird)")

        self.assertEqual(
            session.calls[0][0],
            "https://en.wikipedia.org/api/rest_v1/page/summary/Blue%20jay_%28bird%29",
        )
        self.assertEqual(session.calls[0][1]["timeout"], (3, 10))
        self.assertEqual(summary.extract, "A blue jay is a passerine bird.")
        self.assertEqual(summary.page_url, "https://en.wikipedia.org/wiki/Blue_jay")
        self.assertFalse(hasattr(summary, "extract_html"))

    def test_rejects_json_declared_over_transport_limit_without_reading(self):
        def fail_if_read(_chunk_size):
            raise AssertionError("oversized response body was read")

        response = FakeResponse(
            chunks=fail_if_read,
            headers={"Content-Length": str(MAX_JSON_BYTES + 1)},
        )
        session = FakeSession([response])
        client = ProviderClient(session=session, clock=lambda: 0, sleep=lambda _: None)

        self.assertIsNone(
            client.fetch_summary("https://en.wikipedia.org/wiki/Blue_jay")
        )
        self.assertTrue(session.calls[0][1]["stream"])

    def test_rejects_json_stream_that_crosses_transport_limit(self):
        response = FakeResponse(chunks=[b"{" + b"x" * MAX_JSON_BYTES])
        session = FakeSession([response])
        client = ProviderClient(session=session, clock=lambda: 0, sleep=lambda _: None)

        self.assertIsNone(
            client.fetch_summary("https://en.wikipedia.org/wiki/Blue_jay")
        )

    def test_rejects_unsafe_input_urls_without_requesting(self):
        unsafe_urls = (
            "javascript:alert(1)",
            "http://en.wikipedia.org/wiki/Blue_jay",
            "https://example.com/wiki/Blue_jay",
            "https://user:secret@en.wikipedia.org/wiki/Blue_jay",
            "https://en.wikipedia.org:444/wiki/Blue_jay",
            "https://en.wikipedia.org/not-wiki/Blue_jay",
            "https://[broken/wiki/Blue_jay",
            "https://en.wikipedia.org/wiki/%ZZ",
        )
        for unsafe_url in unsafe_urls:
            with self.subTest(url=unsafe_url):
                session = FakeSession([])
                client = ProviderClient(
                    session=session, clock=lambda: 0, sleep=lambda _: None
                )
                self.assertIsNone(client.fetch_summary(unsafe_url))
                self.assertEqual(session.calls, [])

    def test_rejects_unsafe_canonical_page_url(self):
        unsafe_urls = (
            "javascript:alert(1)",
            "http://en.wikipedia.org/wiki/Blue_jay",
            "https://example.com/wiki/Blue_jay",
            "https://user:secret@en.wikipedia.org/wiki/Blue_jay",
            "https://en.wikipedia.org:444/wiki/Blue_jay",
            "https://en.wikipedia.org/not-wiki/Blue_jay",
            "https://[broken/wiki/Blue_jay",
            "https://en.wikipedia.org/wiki/%ZZ",
        )
        for unsafe_url in unsafe_urls:
            with self.subTest(url=unsafe_url):
                payload = {
                    "extract": "A blue jay is a passerine bird.",
                    "content_urls": {"desktop": {"page": unsafe_url}},
                }
                session = FakeSession([FakeResponse(json_data=payload)])
                client = ProviderClient(
                    session=session, clock=lambda: 0, sleep=lambda _: None
                )
                self.assertIsNone(
                    client.fetch_summary("https://en.wikipedia.org/wiki/Blue_jay")
                )


class ImageDownloadTests(unittest.TestCase):
    PHOTO = PhotoMetadata(
        url="https://static.inaturalist.org/photos/1/medium.jpg",
        attribution="(c) Jane Birder, CC BY 4.0",
        creator="Jane Birder",
        license_code="cc-by",
    )

    def client(self, responses):
        session = FakeSession(responses)
        return ProviderClient(session=session, clock=lambda: 0, sleep=lambda _: None), session

    def test_rejects_disallowed_initial_host_without_requesting_it(self):
        client, session = self.client([])
        photo = PhotoMetadata(
            url="https://example.com/image.jpg",
            attribution=self.PHOTO.attribution,
            creator=self.PHOTO.creator,
            license_code=self.PHOTO.license_code,
        )
        with tempfile.TemporaryDirectory() as temporary:
            result = client.download_reference_image(photo, Path(temporary) / "bird.jpg")
        self.assertIsNone(result)
        self.assertEqual(session.calls, [])

    def test_rejects_redirect_to_disallowed_host(self):
        response = FakeResponse(status=302, headers={"Location": "https://example.com/image.jpg"})
        client, session = self.client([response])
        with tempfile.TemporaryDirectory() as temporary:
            result = client.download_reference_image(self.PHOTO, Path(temporary) / "bird.jpg")
        self.assertIsNone(result)
        self.assertEqual(len(session.calls), 1)
        self.assertFalse(session.calls[0][1]["allow_redirects"])
        self.assertTrue(session.calls[0][1]["stream"])

    def test_stops_before_exceeding_five_megabytes(self):
        chunks = [b"x" * MAX_IMAGE_BYTES, b"y"]
        client, _ = self.client([FakeResponse(chunks=chunks)])
        with tempfile.TemporaryDirectory() as temporary:
            destination = Path(temporary) / "bird.jpg"
            self.assertIsNone(client.download_reference_image(self.PHOTO, destination))
            self.assertFalse(destination.exists())
            self.assertFalse(destination.with_suffix(destination.suffix + ".tmp").exists())

    def test_rejects_malformed_image_and_does_not_publish(self):
        client, _ = self.client([FakeResponse(chunks=[b"not an image"])])
        with tempfile.TemporaryDirectory() as temporary:
            destination = Path(temporary) / "bird.jpg"
            self.assertIsNone(client.download_reference_image(self.PHOTO, destination))
            self.assertFalse(destination.exists())

    def test_resizes_to_960px_and_publishes_atomically(self):
        data = jpeg_bytes((1920, 1200))
        client, _ = self.client([FakeResponse(chunks=[data])])
        with tempfile.TemporaryDirectory() as temporary:
            destination = Path(temporary) / "nested" / "bird.jpg"
            result = client.download_reference_image(self.PHOTO, destination)

            self.assertEqual(result.path, destination)
            self.assertEqual(result.creator, "Jane Birder")
            self.assertEqual(result.license_code, "cc-by")
            self.assertTrue(destination.exists())
            self.assertFalse(destination.with_suffix(destination.suffix + ".tmp").exists())
            with Image.open(destination) as image:
                self.assertEqual(image.size, (960, 600))
                self.assertEqual(image.format, "JPEG")

    def test_rejects_oversized_decoded_dimensions_before_loading_pixels(self):
        data = compressed_png_header(15_000, 4_000)
        client, _ = self.client([FakeResponse(chunks=[data])])
        with tempfile.TemporaryDirectory() as temporary:
            destination = Path(temporary) / "bird.jpg"
            with mock.patch.object(
                Image.Image,
                "load",
                side_effect=AssertionError("oversized pixels must not be loaded"),
            ):
                self.assertIsNone(
                    client.download_reference_image(self.PHOTO, destination)
                )
            self.assertFalse(destination.exists())

    def test_treats_pillow_decompression_bomb_as_safe_rejection(self):
        data = compressed_png_header(100_000, 100_000)
        client, _ = self.client([FakeResponse(chunks=[data])])
        with tempfile.TemporaryDirectory() as temporary:
            destination = Path(temporary) / "bird.jpg"
            self.assertIsNone(client.download_reference_image(self.PHOTO, destination))
            self.assertFalse(destination.exists())


if __name__ == "__main__":
    unittest.main()
