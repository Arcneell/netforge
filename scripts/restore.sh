#!/bin/bash
# Restore a Netforge dump.
# Usage: ./restore.sh /path/to/netforge-YYYYMMDD-HHMMSS.dump
#
# Before overwriting anything this script (1) verifies the dump is a readable
# archive and (2) snapshots the CURRENT database, so a bad restore stays
# recoverable. Set SKIP_SAFETY_BACKUP=1 to skip the snapshot (e.g. restoring
# onto a known-empty DB).
set -euo pipefail

if [ $# -lt 1 ]; then
  echo "Usage: $0 <dump-file>" >&2
  exit 1
fi

DUMP="$1"
COMPOSE_FILE="${COMPOSE_FILE:-/opt/netforge/docker-compose.yml}"
SAFETY_DIR="${SAFETY_DIR:-${BACKUP_DIR:-/mnt/veeam/netforge}}"

if [ ! -f "$DUMP" ]; then
  echo "dump file not found: $DUMP" >&2
  exit 1
fi

# Validate the dump BEFORE touching the database. Restoring from a truncated
# or garbage file with --clean would drop the existing schema and then fail
# half-way, leaving the DB worse than before.
if ! docker compose -f "$COMPOSE_FILE" exec -T postgres \
     pg_restore --list < "$DUMP" >/dev/null 2>&1; then
  echo "ERROR: '$DUMP' is not a valid pg_restore archive (failed --list)." >&2
  exit 1
fi

echo "WARNING: this will OVERWRITE the netforge database. Ctrl+C to abort."
read -r -p "Type 'yes' to continue: " confirm
if [ "$confirm" != "yes" ]; then
  echo "aborted"
  exit 1
fi

# Safety net: snapshot the current DB before overwriting it. Abort if the
# snapshot can't be taken, rather than risk an unrecoverable restore.
if [ "${SKIP_SAFETY_BACKUP:-0}" != "1" ]; then
  mkdir -p "$SAFETY_DIR"
  SAFETY="$SAFETY_DIR/netforge-pre-restore-$(date +%Y%m%d-%H%M%S).dump"
  echo "Snapshotting current database to $SAFETY ..."
  if docker compose -f "$COMPOSE_FILE" exec -T postgres \
       pg_dump -U "${POSTGRES_USER:-netforge}" -Fc "${POSTGRES_DB:-netforge}" > "$SAFETY" \
     && [ -s "$SAFETY" ]; then
    echo "pre-restore snapshot saved: $SAFETY"
  else
    rm -f "$SAFETY"
    echo "ERROR: pre-restore snapshot failed — aborting before any destructive change." >&2
    exit 1
  fi
fi

docker compose -f "$COMPOSE_FILE" exec -T postgres \
  pg_restore -U "${POSTGRES_USER:-netforge}" -d "${POSTGRES_DB:-netforge}" \
  --clean --if-exists < "$DUMP"

echo "restore OK from $DUMP"
