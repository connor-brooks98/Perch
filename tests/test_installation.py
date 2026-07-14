from __future__ import annotations

import json
import re
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MODEL_SHA256 = "350fcd8cf1df1560060d464595dfed8b174b05792788052896004848d9ad04f9"
LABELS_SHA256 = "a16108dfe3f8daff015b87a97ab6a17e717b9b1bccd719f6d8f747746d7b9277"
TEST_BCRYPT = "$2a$14$abcdefghijklmnopqrstuvABCDEFGHIJKLMNOPQRSTUV"


def read(relative_path: str) -> str:
    return (ROOT / relative_path).read_text(encoding="utf-8")


class InstallationContractTests(unittest.TestCase):
    def test_primary_docs_have_no_broken_local_markdown_links(self) -> None:
        for relative_path in ("README.md", "Perch_Installation_Guide.md"):
            document = read(relative_path)
            for target in re.findall(r"\[[^]]+\]\(([^)]+)\)", document):
                if "://" in target or target.startswith("#"):
                    continue
                path_text = target.split("#", 1)[0]
                self.assertTrue(
                    (ROOT / path_text).exists(),
                    f"{relative_path} links to missing local path {target}",
                )

    def test_beginner_guide_is_linear_and_has_success_checkpoints(self) -> None:
        guide = read("Perch_Installation_Guide.md")
        self.assertIn("single authoritative", guide)
        self.assertIn("Primary and tested setup", guide)
        self.assertIn("Checkpoint:", guide)
        self.assertIn(
            "Container privilege, data-directory, and model inference checks passed.",
            guide,
        )
        self.assertNotIn("Option B", guide)
        self.assertNotIn("Option C", guide)

    def test_beginner_guide_explains_command_locations_and_placeholders(self) -> None:
        guide = read("Perch_Installation_Guide.md")
        self.assertIn("Run on your computer", guide)
        self.assertIn("Run on the Raspberry Pi", guide)
        self.assertIn("Do not type the angle brackets", guide)

    def test_readme_routes_first_time_installers_to_the_authoritative_guide(self) -> None:
        readme = read("README.md")
        guide = read("Perch_Installation_Guide.md")
        self.assertIn("# Perch", readme)
        self.assertIn("[first-time installation guide](Perch_Installation_Guide.md)", readme)
        self.assertIn("single authoritative", guide)

    def test_docs_state_the_supported_platform_boundary(self) -> None:
        documents = "\n".join([read("README.md"), read("Perch_Installation_Guide.md")])
        self.assertIn("primary and tested installation path", documents)
        self.assertIn("64-bit machines that run Linux Docker containers", documents)
        self.assertIn("advanced installation", documents)
        self.assertNotIn("runs unchanged on any", documents.lower())

    def test_arm64_inference_dependencies_exclude_numpy_2(self) -> None:
        requirements = read("classifier/requirements.txt")
        self.assertIn("tflite-runtime==2.14.0", requirements)
        self.assertRegex(requirements, r"numpy[^\n]*<2(?:\.0)?")
        self.assertRegex(requirements, r"tensorflow[^\n]*<2\.20")

    def test_network_dependencies_are_bounded_below_next_major(self) -> None:
        requirements = read("puller/requirements.txt")
        self.assertIn("blinkpy==0.23.0", requirements)
        self.assertRegex(requirements, r"aiohttp[^\n]*<4")
        self.assertRegex(requirements, r"requests[^\n]*<3")

    def test_container_images_use_versioned_tags(self) -> None:
        self.assertIn("FROM python:3.11.15-slim-bookworm", read("puller/Dockerfile"))
        self.assertIn("FROM python:3.11.15-slim-bookworm", read("classifier/Dockerfile"))
        self.assertIn("FROM caddy:2.11.4-alpine", read("web/Dockerfile"))
        self.assertIn("cloudflare/cloudflared:2026.6.0", read("docker-compose.cloudflare.yml"))

    def test_web_image_removes_unneeded_caddy_file_capability(self) -> None:
        self.assertIn("setcap -r /usr/bin/caddy", read("web/Dockerfile"))

    def test_python_images_disable_runtime_bytecode_writes(self) -> None:
        self.assertIn("PYTHONDONTWRITEBYTECODE=1", read("puller/Dockerfile"))
        self.assertIn("PYTHONDONTWRITEBYTECODE=1", read("classifier/Dockerfile"))

    def test_docker_build_context_excludes_secrets_and_runtime_data(self) -> None:
        ignored = {
            line.strip()
            for line in read(".dockerignore").splitlines()
            if line.strip() and not line.lstrip().startswith("#")
        }
        for required in {".env", ".git", "data", "classifier/model/*.tflite", "__pycache__"}:
            self.assertIn(required, ignored)

    def test_compose_uses_explicit_service_environments_and_narrow_mounts(self) -> None:
        compose = read("docker-compose.yml")
        self.assertNotIn("env_file:", compose)
        self.assertIn('"8080:8080"', compose)
        self.assertNotIn("127.0.0.1:8080:8080", compose)
        self.assertIn("./data/blink:/data/blink", compose)
        self.assertIn("./data/clips:/data/clips", compose)
        self.assertIn("./data/web:/data/web:ro", compose)
        self.assertNotIn("- ./data:/data", compose)

    def test_compose_preserves_bcrypt_and_isolates_secrets(self) -> None:
        if shutil.which("docker") is None:
            self.skipTest("docker compose CLI is not installed")

        with tempfile.TemporaryDirectory() as temporary:
            project = Path(temporary)
            shutil.copy2(ROOT / "docker-compose.yml", project / "docker-compose.yml")
            shutil.copy2(
                ROOT / "docker-compose.cloudflare.yml",
                project / "docker-compose.cloudflare.yml",
            )
            (project / ".env").write_text(
                "\n".join(
                    [
                        "BLINK_USERNAME=test@example.com",
                        "BLINK_PASSWORD=test-only",
                        "CAMERA_NAME=all",
                        f"BASIC_AUTH_HASH='{TEST_BCRYPT}'",
                        "BASIC_AUTH_USER=birdwatcher",
                        "CLOUDFLARE_TUNNEL_TOKEN=test-tunnel-token",
                        "",
                    ]
                ),
                encoding="utf-8",
            )

            result = subprocess.run(
                [
                    "docker",
                    "compose",
                    "-f",
                    "docker-compose.yml",
                    "-f",
                    "docker-compose.cloudflare.yml",
                    "config",
                    "--format",
                    "json",
                ],
                cwd=project,
                capture_output=True,
                text=True,
                check=False,
            )

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertNotIn("variable is not set", result.stderr.lower())
        config = json.loads(result.stdout)
        services = config["services"]

        # Compose's canonical config escapes literal dollars as `$$` so the
        # rendered file can be parsed again without a second interpolation.
        rendered_hash = services["web"]["environment"]["BASIC_AUTH_HASH"].replace("$$", "$")
        self.assertEqual(rendered_hash, TEST_BCRYPT)
        self.assertNotIn("BLINK_PASSWORD", services["web"]["environment"])
        self.assertNotIn("BLINK_PASSWORD", services["classifier"]["environment"])
        self.assertEqual(services["puller"]["environment"]["BLINK_PASSWORD"], "test-only")
        self.assertEqual(services["tunnel"]["environment"]["TUNNEL_TOKEN"], "test-tunnel-token")
        self.assertNotIn("test-tunnel-token", " ".join(services["tunnel"]["command"]))

        for name in ("puller", "classifier", "web"):
            service = services[name]
            self.assertEqual(service["user"], "1000:1000", name)
            self.assertTrue(service["read_only"], name)
            self.assertIn("ALL", service["cap_drop"], name)
            self.assertTrue(
                any(option.startswith("no-new-privileges") for option in service["security_opt"]),
                name,
            )
            self.assertLessEqual(service["pids_limit"], 256, name)

        tunnel = services["tunnel"]
        self.assertEqual(tunnel["user"], "65532:65532")
        self.assertTrue(tunnel["read_only"])
        self.assertIn("ALL", tunnel["cap_drop"])
        self.assertTrue(
            any(option.startswith("no-new-privileges") for option in tunnel["security_opt"])
        )

        self.assertEqual(set(services["puller"]["networks"]), {"puller-egress"})
        self.assertEqual(set(services["classifier"]["networks"]), {"classifier-egress"})
        self.assertEqual(set(services["web"]["networks"]), {"web-edge"})
        self.assertEqual(set(services["tunnel"]["networks"]), {"web-edge"})
        self.assertNotIn("default", config["networks"])

        self.assertEqual(services["classifier"]["environment"]["MAX_CLIP_ATTEMPTS"], "3")
        self.assertEqual(services["classifier"]["environment"]["CLIP_RETRY_DELAY"], "60")

        classifier_tmpfs = {
            mount.split(":", 1)[0] for mount in services["classifier"]["tmpfs"]
        }
        web_tmpfs = {mount.split(":", 1)[0] for mount in services["web"]["tmpfs"]}
        self.assertIn("/tmp", classifier_tmpfs)
        self.assertTrue({"/data", "/config"} <= web_tmpfs)

        web_port = services["web"]["ports"][0]
        self.assertNotEqual(web_port.get("host_ip"), "127.0.0.1")
        web_mount = next(
            mount for mount in services["web"]["volumes"] if mount["target"] == "/data/web"
        )
        self.assertTrue(web_mount["read_only"])

    def test_model_download_helper_pins_verified_artifacts(self) -> None:
        helper = read("scripts/download-model.sh")
        self.assertIn(MODEL_SHA256, helper)
        self.assertIn(LABELS_SHA256, helper)
        self.assertIn("mktemp", helper)
        self.assertIn("shasum -a 256", helper)

    def test_classifier_uses_the_transactional_current_model_bundle(self) -> None:
        compose = read("docker-compose.yml")
        watcher = read("classifier/watcher.py")
        preflight = read("scripts/verify-install.sh")
        for content in (compose, watcher):
            self.assertIn("/app/model/current/model.tflite", content)
            self.assertIn("/app/model/current/labels.txt", content)
        self.assertIn("classifier/model/current/model.tflite", preflight)
        self.assertIn("classifier/model/current/labels.txt", preflight)

    def test_build_preflight_runs_real_model_inference(self) -> None:
        helper = read("scripts/verify-install.sh")
        self.assertIn("python smoke_model.py", helper)

    def test_docs_define_stable_and_experimental_model_boundaries(self) -> None:
        documents = "\n".join(
            [read("README.md"), read("Perch_Installation_Guide.md"), read("classifier/model/README.md")]
        )
        self.assertIn("MobileNetV2 is Perch's stable runtime", documents)
        self.assertIn("ONNX", documents)
        self.assertIn("experimental", documents)
        self.assertIn("classifier/model/current/model.tflite", documents)
        self.assertIn("rerun `./scripts/download-model.sh`", documents)

    def test_preflight_enforces_private_env_permissions(self) -> None:
        helper = read("scripts/verify-install.sh")
        self.assertIn("stat -c '%a' .env", helper)
        self.assertIn("stat -f '%Lp' .env", helper)
        self.assertIn("chmod 600 .env", read("README.md"))
        self.assertIn("chmod 600 .env", read("Perch_Installation_Guide.md"))

    def test_preflight_checks_runtime_container_boundaries(self) -> None:
        helper = read("scripts/verify-install.sh")
        self.assertIn("docker compose run --rm --no-deps puller", helper)
        self.assertIn("docker compose run --rm --no-deps classifier", helper)
        self.assertIn("caddy validate --config /etc/caddy/Caddyfile", helper)

    def test_documents_explain_retry_and_manual_requeue(self) -> None:
        documents = "\n".join([read("README.md"), read("Perch_Installation_Guide.md")])
        self.assertIn("MAX_CLIP_ATTEMPTS", documents)
        self.assertIn("CLIP_RETRY_DELAY", documents)
        self.assertIn("status = 'error'", documents)
        self.assertIn("attempt_count = 0", documents)

    def test_documents_use_one_literal_bcrypt_rule_and_subscription_requirement(self) -> None:
        documents = "\n".join(
            [read(".env.example"), read("README.md"), read("Perch_Installation_Guide.md")]
        )
        self.assertIn("BASIC_AUTH_HASH='$2a$", documents)
        self.assertNotIn("double every `$`", documents)
        self.assertNotIn("replacing each one with `$$`", documents)
        self.assertIn("Blink subscription", documents)
        self.assertIn("scripts/download-model.sh", documents)

    def test_docs_recommend_private_tailscale_serve_for_remote_access(self) -> None:
        for relative_path in ("README.md", "Perch_Installation_Guide.md"):
            document = read(relative_path)
            self.assertIn("sudo tailscale serve --bg 8080", document, relative_path)
            self.assertIn("private to your tailnet", document, relative_path)
            self.assertIn("Funnel makes the dashboard public", document, relative_path)
            self.assertNotIn("tailscale funnel 8080", document, relative_path)

    def test_docs_hash_dashboard_password_at_a_hidden_interactive_prompt(self) -> None:
        documents = "\n".join([read("README.md"), read("Perch_Installation_Guide.md")])
        expected_command = (
            "docker run --rm -it caddy:2.11.4-alpine caddy hash-password"
        )
        self.assertEqual(documents.count(expected_command), 2)
        self.assertNotIn("hash-password --plaintext", documents)
        self.assertEqual(documents.count("hidden prompt"), 2)
        self.assertEqual(documents.count("do not double"), 2)

    def test_readme_recommends_a_dedicated_account_but_requires_subscription(self) -> None:
        readme = read("README.md")
        self.assertIn("dedicated Blink account is strongly recommended", readme)
        self.assertIn("active Blink subscription is required", readme)
        self.assertIn("session conflicts", readme)

    def test_docs_require_outbound_internet_but_not_remote_dashboard_access(self) -> None:
        documents = "\n".join([read("README.md"), read("Perch_Installation_Guide.md")])
        self.assertNotIn("internet access is optional", documents)
        self.assertEqual(documents.count("Remote dashboard access is optional"), 2)
        self.assertEqual(
            documents.count(
                "Pi needs outbound internet access for Blink and installation downloads"
            ),
            2,
        )


if __name__ == "__main__":
    unittest.main()
