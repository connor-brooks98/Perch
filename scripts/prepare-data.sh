#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

directories=(data/blink data/clips data/db data/web data/web/images data/web/thumbs data/web/enrichment)
mkdir -p "${directories[@]}"

for directory in "${directories[@]}"; do
  if [[ ! -w "$directory" ]]; then
    echo "ERROR: $directory is not writable by the current user." >&2
    echo "Repair existing Docker-created directories with:" >&2
    echo "  sudo chown -R \"\$(id -u):\$(id -g)\" data" >&2
    exit 1
  fi
done

# Blink credentials and the SQLite database contain private account data.
chmod 700 data/blink data/db

echo "Writable Perch data directories are ready."
