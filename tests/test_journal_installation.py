from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def read(relative_path: str) -> str:
    return (ROOT / relative_path).read_text(encoding="utf-8")


def compose_config() -> dict:
    if shutil.which("docker") is None:
        raise unittest.SkipTest("docker compose CLI is not installed")
    environment = os.environ.copy()
    environment.update(
        {
            "BLINK_USERNAME": "test@example.com",
            "BLINK_PASSWORD": "test-only",
            "BASIC_AUTH_HASH": "$2a$14$abcdefghijklmnopqrstuvABCDEFGHIJKLMNOPQRSTUV",
        }
    )
    result = subprocess.run(
        ["docker", "compose", "config", "--format", "json"],
        cwd=ROOT,
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        raise AssertionError(result.stderr)
    return json.loads(result.stdout)


class JournalInstallationContractTests(unittest.TestCase):
    def test_journal_is_internal_hardened_and_narrowly_mounted(self) -> None:
        config = compose_config()
        journal = config["services"]["journal"]
        self.assertNotIn("ports", journal)
        self.assertEqual(journal["user"], "1000:1000")
        self.assertTrue(journal["read_only"])
        self.assertEqual(journal["cap_drop"], ["ALL"])
        volumes = "\n".join(
            mount["source"] + ":" + mount["target"]
            for mount in journal["volumes"]
        )
        self.assertIn("data/db:/data/db", volumes)
        self.assertNotIn("/data/blink", volumes)
        self.assertNotIn("/data/clips", volumes)

        enrichment_mount = next(
            (
                mount
                for mount in journal["volumes"]
                if mount["target"] == "/data/web/enrichment"
            ),
            None,
        )
        self.assertIsNotNone(enrichment_mount)
        self.assertEqual(enrichment_mount["type"], "bind")
        self.assertEqual(
            Path(enrichment_mount["source"]).resolve(),
            (ROOT / "data" / "web" / "enrichment").resolve(),
        )
        self.assertFalse(enrichment_mount.get("read_only", False))
        self.assertFalse(
            any(mount["target"] == "/data/web" for mount in journal["volumes"])
        )

        web_mount = next(
            mount
            for mount in config["services"]["web"]["volumes"]
            if mount["target"] == "/data/web"
        )
        self.assertEqual(web_mount["type"], "bind")
        self.assertEqual(
            Path(web_mount["source"]).resolve(), (ROOT / "data" / "web").resolve()
        )
        self.assertTrue(web_mount["read_only"])

    def test_caddy_proxies_api_before_static_fallback(self) -> None:
        caddy = read("web/Caddyfile")
        self.assertLess(caddy.index("handle /api/*"), caddy.index("handle {"))
        self.assertIn("reverse_proxy journal:8000", caddy)

    def test_caddy_serves_authenticated_enrichment_images_from_data(self) -> None:
        caddy = read("web/Caddyfile")
        dynamic_matcher = "@dynamic path /thumbs/* /images/* /enrichment/* /data/*"
        self.assertIn(dynamic_matcher, caddy)
        self.assertIn("root * /data/web", caddy)
        self.assertLess(caddy.index("basic_auth"), caddy.index(dynamic_matcher))
        dynamic_handler = caddy[
            caddy.index("handle @dynamic {") : caddy.index(
                "\n\t}", caddy.index("handle @dynamic {")
            )
        ]
        self.assertIn('header Cache-Control "no-store"', dynamic_handler)

    def test_caddy_enforces_self_hosted_browser_network_policy(self) -> None:
        caddy = read("web/Caddyfile")
        match = re.search(r'header Content-Security-Policy "([^"]+)"', caddy)
        self.assertIsNotNone(match)
        directives = {
            parts[0]: parts[1:]
            for directive in match.group(1).split(";")
            if (parts := directive.strip().split())
        }
        self.assertEqual(directives["connect-src"], ["'self'"])
        self.assertEqual(directives["img-src"], ["'self'", "data:"])
        self.assertEqual(directives["default-src"], ["'self'"])
        self.assertEqual(directives["style-src"], ["'self'", "'unsafe-inline'"])
        self.assertNotIn("navigate-to", directives)
        self.assertLess(caddy.index("basic_auth"), match.start())

    def test_frontend_provider_hosts_are_anchor_validation_only(self) -> None:
        scripts = {
            path.relative_to(ROOT / "web" / "site").as_posix(): path.read_text(
                encoding="utf-8"
            )
            for path in (ROOT / "web" / "site").rglob("*.js")
        }
        species = scripts["views/species.js"]
        provider_hosts = (
            "www.inaturalist.org",
            "en.wikipedia.org",
            "inaturalist-open-data.s3.amazonaws.com",
            "static.inaturalist.org",
        )
        for hostname in provider_hosts:
            self.assertIn(hostname, species)
            for path, source in scripts.items():
                if path != "views/species.js":
                    self.assertNotIn(hostname, source)

        javascript = "\n".join(scripts.values())
        self.assertNotRegex(javascript, r"fetch\s*\(\s*['\"`]https?://")
        self.assertNotRegex(
            javascript,
            r"(?:\.src\s*=|setAttribute\(\s*['\"]src['\"])"
            r"[^;\n]*(?:inaturalist|wikipedia|amazonaws)",
        )
        self.assertIn('link.href = href', species)
        self.assertIn('photo.src = image.src', species)
        self.assertIn('^\\/enrichment\\/[0-9a-f]{24}-[0-9a-f]{32}\\.jpg$', species)
