#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

MODEL_SHA256="350fcd8cf1df1560060d464595dfed8b174b05792788052896004848d9ad04f9"
LABELS_SHA256="a16108dfe3f8daff015b87a97ab6a17e717b9b1bccd719f6d8f747746d7b9277"
BUILD=false

if [[ "${1:-}" == "--build" ]]; then
  BUILD=true
elif [[ $# -gt 0 ]]; then
  echo "Usage: $0 [--build]" >&2
  exit 2
fi

fail() {
  echo "ERROR: $*" >&2
  exit 1
}

checksum() {
  if command -v sha256sum >/dev/null 2>&1; then
    sha256sum "$1" | awk '{print $1}'
  elif command -v shasum >/dev/null 2>&1; then
    shasum -a 256 "$1" | awk '{print $1}'
  else
    fail "sha256sum or shasum is required"
  fi
}

command -v docker >/dev/null 2>&1 || fail "Docker is not installed"
docker compose version >/dev/null 2>&1 || fail "Docker Compose is not installed"
[[ -f .env ]] || fail ".env is missing; copy .env.example to .env first"

if env_mode="$(stat -c '%a' .env 2>/dev/null)"; then
  :
else
  env_mode="$(stat -f '%Lp' .env 2>/dev/null)" || fail "could not inspect .env permissions"
fi
[[ "$env_mode" == "600" ]] || fail ".env permissions are $env_mode; run: chmod 600 .env"

if grep -Eq '^(BLINK_USERNAME=feeder-account@example\.com|BLINK_PASSWORD=change-me|BASIC_AUTH_HASH=.*REPLACE_WITH)' .env; then
  fail ".env still contains placeholder credentials"
fi

grep -Eq "^BASIC_AUTH_HASH='\\\$2[aby]\\\$" .env || \
  fail "BASIC_AUTH_HASH must be a single-quoted bcrypt hash, for example BASIC_AUTH_HASH='\$2a\$...'"

[[ -s classifier/model/current/model.tflite ]] || fail "classifier/model/current/model.tflite is missing; run ./scripts/download-model.sh"
[[ -s classifier/model/current/labels.txt ]] || fail "classifier/model/current/labels.txt is missing; run ./scripts/download-model.sh"
[[ "$(checksum classifier/model/current/model.tflite)" == "$MODEL_SHA256" ]] || fail "model.tflite checksum does not match"
[[ "$(checksum classifier/model/current/labels.txt)" == "$LABELS_SHA256" ]] || fail "labels.txt checksum does not match"

./scripts/prepare-data.sh

config_output="$(docker compose config 2>&1)" || {
  echo "$config_output" >&2
  fail "Docker Compose configuration is invalid"
}
if grep -qi 'variable is not set' <<<"$config_output"; then
  echo "$config_output" >&2
  fail "Docker Compose reported an unset variable"
fi

echo "Static installation checks passed."

if [[ "$BUILD" == true ]]; then
  docker info >/dev/null 2>&1 || fail "Docker daemon is not running"
  docker compose build
  echo "Container images built successfully."
  docker compose run --rm --no-deps puller python -c \
    'from pathlib import Path; paths=[Path("/data/blink/.perch-write-test"),Path("/data/clips/.perch-write-test"),Path("/data/db/.perch-write-test")]; [p.write_text("ok") for p in paths]; [p.unlink() for p in paths]'
  docker compose run --rm --no-deps classifier python -c \
    'from pathlib import Path; paths=[Path("/data/db/.perch-classifier-test"),Path("/data/web/.perch-classifier-test")]; [p.write_text("ok") for p in paths]; [p.unlink() for p in paths]'
  docker compose run --rm --no-deps classifier python smoke_model.py
  docker compose run --rm --no-deps web \
    caddy validate --config /etc/caddy/Caddyfile
  echo "Container privilege, data-directory, and model inference checks passed."
fi
