#!/usr/bin/env bash
# Backs up the database and the photos. Run from the project folder on the server:
#   bash deploy/backup.sh
# Schedule it daily (see deploy/DEPLOY.md, step 9). Restoring is described there too.
set -euo pipefail
cd "$(dirname "$0")/.."

set -a
# shellcheck disable=SC1091
. ./.env
set +a

COMPOSE="docker compose -f docker-compose.prod.yml"
DIR="${BACKUP_DIR:-/var/backups/chakula}"
KEEP="${BACKUP_KEEP_DAYS:-14}"
STAMP="$(date +%Y-%m-%d_%H%M%S)"
mkdir -p "$DIR"
umask 077

# 1. The database (orders, payments, ledger, users). A consistent snapshot while the app runs.
$COMPOSE exec -T db pg_dump -U "${POSTGRES_USER:-hotel}" -d "${POSTGRES_DB:-hotel}" \
  --no-owner | gzip > "$DIR/db_$STAMP.sql.gz"

# 2. Menu photos and rider ID photos (these are not in the database).
for vol in media private_media; do
  docker run --rm -v "chakula_${vol}:/data:ro" -v "$DIR:/out" alpine \
    tar czf "/out/${vol}_$STAMP.tar.gz" -C /data .
done

# A backup that is empty or tiny means something went wrong: say so loudly.
if [ "$(stat -c %s "$DIR/db_$STAMP.sql.gz")" -lt 2000 ]; then
  echo "WARNING: the database backup looks empty: $DIR/db_$STAMP.sql.gz" >&2
  exit 1
fi

# 3. Optional copy to another place, so one broken server does not lose everything.
if [ -n "${BACKUP_REMOTE:-}" ] && command -v rclone >/dev/null 2>&1; then
  rclone copy "$DIR" "$BACKUP_REMOTE" --include "*_$STAMP.*"
fi

# 4. Delete local backups older than KEEP days.
find "$DIR" -type f \( -name 'db_*.sql.gz' -o -name '*_*.tar.gz' \) -mtime +"$KEEP" -delete

echo "Backup done: $DIR (*_$STAMP)"
