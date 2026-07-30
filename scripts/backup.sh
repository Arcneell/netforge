#!/bin/bash
# Daily backup of the Netforge database.
# Run via cron (02:30 recommended). Requires docker compose to be up.
set -euo pipefail

# The dump contains the full inventory (and, transitively, session/audit
# data) — without this, files created below inherit the host's default
# permissions, which on most distros is world-readable. 077 means only the
# owner (whoever cron runs this as) can read the dump and its directory.
umask 077

BACKUP_DIR="${BACKUP_DIR:-/mnt/veeam/netforge}"
RETENTION_DAYS="${RETENTION_DAYS:-30}"
COMPOSE_FILE="${COMPOSE_FILE:-/opt/netforge/docker-compose.yml}"

mkdir -p "$BACKUP_DIR"
STAMP=$(date +%Y%m%d-%H%M%S)
OUT="$BACKUP_DIR/netforge-$STAMP.dump"
TMP="$OUT.partial"

# Always remove the partial file on any failure so a truncated dump is never
# left behind nor rotated as if it were a valid backup.
cleanup() { rm -f "$TMP"; }
trap cleanup EXIT

# Dump to a .partial file first; only publish it once verified.
docker compose -f "$COMPOSE_FILE" exec -T postgres \
  pg_dump -U "${POSTGRES_USER:-netforge}" -Fc "${POSTGRES_DB:-netforge}" > "$TMP"

# Integrity check. A valid custom-format (-Fc) archive can be listed by
# pg_restore; this catches truncated dumps, an auth error that wrote an empty
# file, or `docker compose exec` plumbing that leaked stderr into the file.
if [ ! -s "$TMP" ]; then
  echo "backup FAILED: dump is empty" >&2
  exit 1
fi
if ! docker compose -f "$COMPOSE_FILE" exec -T postgres \
     pg_restore --list < "$TMP" >/dev/null 2>&1; then
  echo "backup FAILED: dump did not pass pg_restore --list integrity check" >&2
  exit 1
fi

# Atomically publish the verified dump, then drop the cleanup trap.
mv "$TMP" "$OUT"
trap - EXIT

# Rotation — only reached after a verified-good backup, so a failed run can
# never delete old good dumps.
find "$BACKUP_DIR" -name 'netforge-*.dump' -mtime "+$RETENTION_DAYS" -delete

echo "backup OK: $OUT ($(du -h "$OUT" | cut -f1))"
