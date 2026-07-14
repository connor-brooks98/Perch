from __future__ import annotations

import json
import os
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

    def test_caddy_proxies_api_before_static_fallback(self) -> None:
        caddy = read("web/Caddyfile")
        self.assertLess(caddy.index("handle /api/*"), caddy.index("handle {"))
        self.assertIn("reverse_proxy journal:8000", caddy)

    def test_caddy_serves_authenticated_enrichment_images_from_data(self) -> None:
        caddy = read("web/Caddyfile")
        self.assertIn("@dynamic path /thumbs/* /data/* /enrichment/*", caddy)
        self.assertIn("root * /data/web", caddy)
        self.assertLess(caddy.index("basic_auth"), caddy.index("@dynamic path"))
