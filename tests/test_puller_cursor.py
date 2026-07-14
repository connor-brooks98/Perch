from __future__ import annotations

import importlib.util
import sys
import types
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]


def load_puller():
    aiohttp = types.ModuleType("aiohttp")
    aiohttp.ClientSession = object

    blinkpy = types.ModuleType("blinkpy")
    blinkpy_auth = types.ModuleType("blinkpy.auth")
    blinkpy_auth.Auth = object
    blinkpy_blinkpy = types.ModuleType("blinkpy.blinkpy")
    blinkpy_blinkpy.Blink = object
    blinkpy_helpers = types.ModuleType("blinkpy.helpers")
    blinkpy_util = types.ModuleType("blinkpy.helpers.util")
    blinkpy_util.json_load = object

    modules = {
        "aiohttp": aiohttp,
        "blinkpy": blinkpy,
        "blinkpy.auth": blinkpy_auth,
        "blinkpy.blinkpy": blinkpy_blinkpy,
        "blinkpy.helpers": blinkpy_helpers,
        "blinkpy.helpers.util": blinkpy_util,
    }
    spec = importlib.util.spec_from_file_location(
        "perch_puller_cursor_test", ROOT / "puller" / "puller.py"
    )
    module = importlib.util.module_from_spec(spec)
    with patch.dict(sys.modules, modules):
        spec.loader.exec_module(module)
    return module


class PullerCursorTests(unittest.TestCase):
    def test_formats_cursor_with_explicit_utc_timezone(self) -> None:
        puller = load_puller()

        cursor = puller.format_blink_since(
            datetime(2026, 7, 14, 12, 49, tzinfo=timezone.utc)
        )

        self.assertEqual(cursor, "2026-07-14T12:49:00+0000")

    def test_normalizes_legacy_naive_cursor_as_utc(self) -> None:
        puller = load_puller()

        cursor = puller.normalize_blink_since("2026/07/14 12:49")

        self.assertEqual(cursor, "2026-07-14T12:49:00+0000")

    def test_rejects_naive_datetime_before_formatting(self) -> None:
        puller = load_puller()

        with self.assertRaisesRegex(ValueError, "timezone-aware"):
            puller.format_blink_since(datetime(2026, 7, 14, 12, 49))


if __name__ == "__main__":
    unittest.main()
