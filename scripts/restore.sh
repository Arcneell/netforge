#!/bin/bash
# Restore a Netforge dump.
# Usage: ./restore.sh /path/to/netforge-YYYYMMDD-HHMMSS.dump
set -euo pipefail

if [ $# -lt 1 ]; then
  echo "Usage: $0 <dump-file>" >&2
  exit 1
fi

DUMP="$1"
COMPOSE_FILE="${COMPOSE_FILE:-/opt/netforge/docker-compose.yml}"

if [ ! -f "$DUMP" ]; then
  echo "dump file not found: $DUMP" >&2
  exit 1
fi

echo "WARNING: this will OVERWRITE the netforge database. Ctrl+C to abort."
read -r -p "Type 'yes' to continue: " confirm
if [ "$confirm" != "yes" ]; then
  echo "aborted"
  exit 1
fi

docker compose -f "$COMPOSE_FILE" exec -T postgres \
  pg_restore -U "${POSTGRES_USER:-netforge}" -d "${POSTGRES_DB:-netforge}" \
  --clean --if-exists < "$DUMP"

echo "restore OK from $DUMP"
