from html.parser import HTMLParser
import json
from pathlib import Path
import unittest

from PIL import Image


ROOT = Path(__file__).resolve().parents[1]
SITE = ROOT / "web/site"
BACKGROUND = (233, 237, 228)


def read(path: str) -> str:
    return (ROOT / path).read_text()


class LinkParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.links = []
        self.theme_color = None

    def handle_starttag(self, tag, attrs):
        attributes = dict(attrs)
        if tag == "link":
            self.links.append(attributes)
        elif tag == "meta" and attributes.get("name") == "theme-color":
            self.theme_color = attributes.get("content")


class PwaContractTests(unittest.TestCase):
    def test_manifest_has_canonical_identity_and_distinct_icons(self):
        manifest = json.loads(read("web/site/manifest.json"))
        self.assertEqual(manifest["name"], "Perch · Sara's Feeder")
        self.assertEqual(manifest["short_name"], "Perch")
        self.assertEqual(manifest["start_url"], "/")
        self.assertEqual(manifest["scope"], "/")
        self.assertEqual(manifest["display"], "standalone")
        self.assertEqual(manifest["background_color"], "#E9EDE4")
        self.assertEqual(manifest["theme_color"], "#E9EDE4")

        icons = {
            (icon["sizes"], icon.get("purpose", "any")): icon["src"]
            for icon in manifest["icons"]
        }
        self.assertEqual(icons[("192x192", "any")], "icons/icon-192.png")
        self.assertEqual(icons[("512x512", "any")], "icons/icon-512.png")
        self.assertEqual(
            icons[("512x512", "maskable")], "icons/icon-maskable-512.png"
        )
        self.assertNotEqual(
            icons[("512x512", "any")], icons[("512x512", "maskable")]
        )

    def test_icon_dimensions_content_and_maskable_safe_zone(self):
        expected = {
            "icon-192.png": (192, 192),
            "icon-512.png": (512, 512),
            "icon-maskable-512.png": (512, 512),
            "apple-touch-icon.png": (180, 180),
            "favicon-32.png": (32, 32),
        }
        for name, size in expected.items():
            with self.subTest(name=name), Image.open(SITE / "icons" / name) as image:
                self.assertEqual(image.size, size)
                colors = image.convert("RGB").getcolors(maxcolors=size[0] * size[1])
                self.assertIsNotNone(colors)
                colors = {color for _, color in colors}
                self.assertIn(BACKGROUND, colors)
                self.assertGreater(len(colors), 3)

        normal = (SITE / "icons/icon-512.png").read_bytes()
        maskable_path = SITE / "icons/icon-maskable-512.png"
        self.assertNotEqual(normal, maskable_path.read_bytes())

        with Image.open(maskable_path) as image:
            pixels = image.convert("RGB")
            safe_min = round(image.width * 0.17)
            safe_max = image.width - safe_min
            outside_safe_zone = (
                pixels.getpixel((x, y))
                for y in range(image.height)
                for x in range(image.width)
                if x < safe_min or x >= safe_max or y < safe_min or y >= safe_max
            )
            self.assertTrue(all(pixel == BACKGROUND for pixel in outside_safe_zone))

        with Image.open(SITE / "favicon.ico") as favicon:
            self.assertEqual(favicon.format, "ICO")
            self.assertEqual(favicon.size, (32, 32))

    def test_html_links_all_pwa_identity_assets(self):
        parser = LinkParser()
        parser.feed(read("web/site/index.html"))
        links = {(link.get("rel"), link.get("type")): link.get("href") for link in parser.links}
        self.assertEqual(links[("manifest", None)], "manifest.json")
        self.assertEqual(links[("apple-touch-icon", None)], "icons/apple-touch-icon.png")
        self.assertEqual(links[("icon", "image/png")], "icons/favicon-32.png")
        self.assertEqual(links[("icon", "image/x-icon")], "favicon.ico")
        self.assertEqual(parser.theme_color, "#E9EDE4")

    def test_service_worker_uses_v2_and_bypasses_dynamic_paths(self):
        source = read("web/site/sw.js")
        self.assertIn('const CACHE = "perch-shell-v2"', source)
        for path in ("/api/", "/images/", "/thumbs/", "/enrichment/"):
            self.assertIn(f'url.pathname.includes("{path}")', source)
        for asset in (
            "icons/icon-maskable-512.png",
            "icons/favicon-32.png",
            "favicon.ico",
        ):
            self.assertIn(f'"{asset}"', source)


if __name__ == "__main__":
    unittest.main()
