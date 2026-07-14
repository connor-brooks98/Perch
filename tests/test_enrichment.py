from __future__ import annotations

import io
import tempfile
import unittest
from pathlib import Path

from PIL import Image

from journal.providers import (
    MAX_IMAGE_BYTES,
    PhotoMetadata,
    ProviderClient,
    RateGate,
)


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


class FakeResponse:
    def __init__(self, *, json_data=None, chunks=(), status=200, headers=None):
        self._json_data = json_data
        self._chunks = chunks
        self.status_code = status
        self.headers = headers or {}

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")

    def json(self):
        return self._json_data

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


if __name__ == "__main__":
    unittest.main()
