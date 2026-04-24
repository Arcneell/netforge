#!/bin/bash
# Daily backup of the Netforge database.
# Run via cron (02:30 recommended). Requires docker compose to be up.
set -euo pipefail

BACKUP_DIR="${BACKUP_DIR:-/mnt/veeam/netforge}"
RETENTION_DAYS="${RETENTION_DAYS:-30}"
COMPOSE_FILE="${COMPOSE_FILE:-/opt/netforge/docker-compose.yml}"

mkdir -p "$BACKUP_DIR"
STAMP=$(date +%Y%m%d-%H%M%S)
OUT="$BACKUP_DIR/netforge-$STAMP.dump"

docker compose -f "$COMPOSE_FILE" exec -T postgres \
  pg_dump -U "${POSTGRES_USER:-netforge}" -Fc "${POSTGRES_DB:-netforge}" > "$OUT"

# Rotation
find "$BACKUP_DIR" -name 'netforge-*.dump' -mtime "+$RETENTION_DAYS" -delete

echo "backup OK: $OUT"
