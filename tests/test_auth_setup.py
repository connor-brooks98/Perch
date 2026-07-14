from __future__ import annotations

import importlib.util
import io
import sys
import types
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]


class BlinkTwoFARequiredError(Exception):
    pass


class FakeSession:
    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, traceback):
        return False


class FakeAuth:
    def __init__(self, login_data, no_prompt=False, session=None):
        self.login_data = login_data
        self.no_prompt = no_prompt
        self.session = session


class FakeBlink:
    require_two_factor = False
    two_factor_result = True
    instances: list["FakeBlink"] = []

    def __init__(self, session=None):
        self.session = session
        self.auth = None
        self.cameras = {"Feeder": object()}
        self.codes: list[str] = []
        self.saved_paths: list[str] = []
        self.refresh_count = 0
        self.__class__.instances.append(self)

    async def start(self):
        if self.require_two_factor:
            raise BlinkTwoFARequiredError
        return True

    async def send_2fa_code(self, code: str):
        self.codes.append(code)
        return self.two_factor_result

    async def refresh(self):
        self.refresh_count += 1

    async def save(self, path: str):
        self.saved_paths.append(path)


def load_auth_setup():
    aiohttp = types.ModuleType("aiohttp")
    aiohttp.ClientSession = FakeSession

    blinkpy = types.ModuleType("blinkpy")
    blinkpy_auth = types.ModuleType("blinkpy.auth")
    blinkpy_auth.Auth = FakeAuth
    blinkpy_auth.BlinkTwoFARequiredError = BlinkTwoFARequiredError
    blinkpy_blinkpy = types.ModuleType("blinkpy.blinkpy")
    blinkpy_blinkpy.Blink = FakeBlink

    modules = {
        "aiohttp": aiohttp,
        "blinkpy": blinkpy,
        "blinkpy.auth": blinkpy_auth,
        "blinkpy.blinkpy": blinkpy_blinkpy,
    }
    spec = importlib.util.spec_from_file_location(
        "perch_auth_setup_test", ROOT / "puller" / "auth_setup.py"
    )
    module = importlib.util.module_from_spec(spec)
    with patch.dict(sys.modules, modules):
        spec.loader.exec_module(module)
    module.USERNAME = "bird@example.invalid"
    module.PASSWORD = "test-only"
    module.CREDS_PATH = "/tmp/perch-auth-test/creds.json"
    return module


class AuthSetupTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        FakeBlink.instances.clear()
        FakeBlink.require_two_factor = False
        FakeBlink.two_factor_result = True

    async def test_modern_two_factor_flow_prompts_and_saves_credentials(self) -> None:
        module = load_auth_setup()
        FakeBlink.require_two_factor = True

        with (
            patch.object(module.os, "makedirs"),
            patch("builtins.input", return_value="123456"),
            redirect_stdout(io.StringIO()),
            redirect_stderr(io.StringIO()),
        ):
            try:
                result = await module.main()
            except BlinkTwoFARequiredError:
                result = "uncaught two-factor requirement"

        blink = FakeBlink.instances[-1]
        self.assertEqual(result, 0)
        self.assertEqual(blink.codes, ["123456"])
        self.assertEqual(blink.saved_paths, [module.CREDS_PATH])

    async def test_rejected_two_factor_code_does_not_save_credentials(self) -> None:
        module = load_auth_setup()
        FakeBlink.require_two_factor = True
        FakeBlink.two_factor_result = False

        with (
            patch.object(module.os, "makedirs"),
            patch("builtins.input", return_value="000000"),
            redirect_stdout(io.StringIO()),
            redirect_stderr(io.StringIO()),
        ):
            try:
                result = await module.main()
            except BlinkTwoFARequiredError:
                result = "uncaught two-factor requirement"

        blink = FakeBlink.instances[-1]
        self.assertEqual(result, 1)
        self.assertEqual(blink.saved_paths, [])


if __name__ == "__main__":
    unittest.main()
