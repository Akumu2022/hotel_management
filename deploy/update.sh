#!/usr/bin/env bash
# Put a new version live. Run from the project folder on the server:
#   bash deploy/update.sh
# Takes a backup first, rebuilds, restarts, then runs the launch check. The database is brought
# up to date automatically when the API starts. If it fails, see "Rolling back" in DEPLOY.md.
set -euo pipefail
cd "$(dirname "$0")/.."

COMPOSE="docker compose -f docker-compose.prod.yml"

echo "== Backup before the update"
bash deploy/backup.sh

echo "== Fetch the new version"
git pull --ff-only

echo "== Build and restart"
$COMPOSE up -d --build --remove-orphans

echo "== Wait for the API to be healthy"
for i in $(seq 1 40); do
  state="$($COMPOSE ps --format '{{.Service}} {{.Health}}' api | awk '{print $2}')"
  [ "$state" = "healthy" ] && break
  sleep 3
done
$COMPOSE ps

echo "== Launch check"
$COMPOSE exec -T api python -m app.cli check-production || true

echo "== Done. Open https://$(grep '^DOMAIN=' .env | cut -d= -f2) and look at the site."
