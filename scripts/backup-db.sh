#!/usr/bin/env bash
# Nightly SQLite backup (Phase 7). Uses the online .backup API so it's safe
# while the classifier is writing. Add to the Pi's crontab, e.g.:
#   0 3 * * *  /home/connor/bird-feeder/scripts/backup-db.sh
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
DB="$ROOT/data/db/feeder.sqlite"
DEST="$ROOT/data/backups"
mkdir -p "$DEST"

stamp="$(date +%Y%m%d-%H%M%S)"
sqlite3 "$DB" ".backup '$DEST/feeder-$stamp.sqlite'"

# keep the last 14 backups
ls -1t "$DEST"/feeder-*.sqlite | tail -n +15 | xargs -r rm --
echo "backed up -> $DEST/feeder-$stamp.sqlite"
