#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
TARGET_DIR="${1:-$ROOT/classifier/model}"

MODEL_URL="https://raw.githubusercontent.com/google-coral/test_data/master/mobilenet_v2_1.0_224_inat_bird_quant.tflite"
LABELS_URL="https://raw.githubusercontent.com/google-coral/test_data/master/inat_bird_labels.txt"
MODEL_SHA256="${PERCH_MODEL_SHA256:-350fcd8cf1df1560060d464595dfed8b174b05792788052896004848d9ad04f9}"
LABELS_SHA256="${PERCH_LABELS_SHA256:-a16108dfe3f8daff015b87a97ab6a17e717b9b1bccd719f6d8f747746d7b9277}"

if [[ -z "${PERCH_MODEL_SOURCE_DIR:-}" ]] && ! command -v curl >/dev/null 2>&1; then
  echo "curl is required to download the model files." >&2
  exit 1
fi

checksum() {
  if command -v sha256sum >/dev/null 2>&1; then
    sha256sum "$1" | awk '{print $1}'
  elif command -v shasum >/dev/null 2>&1; then
    shasum -a 256 "$1" | awk '{print $1}'
  else
    echo "sha256sum or shasum is required to verify downloads." >&2
    return 1
  fi
}

verify() {
  local file="$1"
  local expected="$2"
  local actual
  actual="$(checksum "$file")"
  if [[ "$actual" != "$expected" ]]; then
    echo "Checksum mismatch for $(basename "$file")" >&2
    echo "Expected: $expected" >&2
    echo "Actual:   $actual" >&2
    return 1
  fi
}

mkdir -p "$TARGET_DIR"
stage="$(mktemp -d "$TARGET_DIR/.download.XXXXXX")"
backup=""

cleanup() {
  local status=$?
  if [[ $status -ne 0 && -n "$backup" && -d "$backup" && ! -e "$TARGET_DIR/current" ]]; then
    if mv "$backup" "$TARGET_DIR/current"; then
      backup=""
      echo "Previous model bundle restored." >&2
    else
      echo "Could not restore the previous model bundle from $backup" >&2
    fi
  fi
  [[ -z "$stage" || ! -d "$stage" ]] || rm -rf "$stage"
  exit "$status"
}
trap cleanup EXIT

if [[ -n "${PERCH_MODEL_SOURCE_DIR:-}" ]]; then
  [[ -f "$PERCH_MODEL_SOURCE_DIR/model.tflite" ]] || {
    echo "Test source is missing model.tflite" >&2
    exit 1
  }
  [[ -f "$PERCH_MODEL_SOURCE_DIR/labels.txt" ]] || {
    echo "Test source is missing labels.txt" >&2
    exit 1
  }
  cp "$PERCH_MODEL_SOURCE_DIR/model.tflite" "$stage/model.tflite"
  cp "$PERCH_MODEL_SOURCE_DIR/labels.txt" "$stage/labels.txt"
else
  echo "Downloading the Perch bird model..."
  curl --fail --location --retry 3 --silent --show-error --output "$stage/model.tflite" "$MODEL_URL"
  curl --fail --location --retry 3 --silent --show-error --output "$stage/labels.txt" "$LABELS_URL"
fi

verify "$stage/model.tflite" "$MODEL_SHA256"
verify "$stage/labels.txt" "$LABELS_SHA256"
grep -Eq '[^[:space:]]' "$stage/labels.txt" || {
  echo "Downloaded labels.txt is empty." >&2
  exit 1
}

chmod 0644 "$stage/model.tflite" "$stage/labels.txt"

if [[ -e "$TARGET_DIR/current" ]]; then
  backup="$(mktemp -d "$TARGET_DIR/.backup.XXXXXX")"
  rmdir "$backup"
  mv "$TARGET_DIR/current" "$backup"
fi

if [[ "${PERCH_MODEL_INSTALL_FAIL_AFTER_BACKUP:-0}" == "1" ]]; then
  echo "Injected model promotion failure." >&2
  exit 1
fi

mv "$stage" "$TARGET_DIR/current"
stage=""
if [[ -n "$backup" ]]; then
  rm -rf "$backup"
  backup=""
fi
trap - EXIT

echo "Verified model bundle installed in $TARGET_DIR/current"
