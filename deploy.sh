#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "${BASH_SOURCE[0]}")"

if [ ! -f ".env" ]; then
    echo "ERROR: trpg-backend/.env is missing."
    exit 1
fi

if ! docker network inspect web >/dev/null 2>&1; then
    echo "ERROR: Docker network 'web' does not exist. Deploy vps-gateway-project first."
    exit 1
fi

timestamp="$(date -u +%Y%m%dT%H%M%SZ)"

echo "==> Creating local SQLite backup"
mkdir -p data/backups
if [ -f "data/data.db" ]; then
    cp data/data.db "data/backups/data-${timestamp}.db"
    echo "Saved local backup: data/backups/data-${timestamp}.db"
else
    echo "No data/data.db found; skipping local backup."
fi

api_container="$(docker compose ps -q api || true)"
if [ -n "${api_container}" ] && [ "$(docker inspect -f '{{.State.Running}}' "${api_container}")" = "true" ]; then
    echo "==> Uploading pre-deploy SQLite snapshot to S3"
    docker compose exec -T api python - <<'PY'
from app.config import get_settings
from app.db_snapshot import create_and_upload_database_snapshot

object_key = create_and_upload_database_snapshot(get_settings())
if not object_key:
    raise SystemExit("S3 snapshot did not run; check DB_SNAPSHOT_ON_SHUTDOWN")

print(f"Uploaded database snapshot: {object_key}")
PY
else
    echo "No running api container found; skipping pre-deploy S3 snapshot."
fi

echo "==> Validating backend Docker Compose config"
docker compose config >/dev/null

echo "==> Deploying backend"
docker compose up -d --build

echo "==> Checking backend health"
curl -fsS "${HEALTH_URL:-https://api.arnaud-a.dev/health}" >/dev/null

echo "==> Backend status"
docker compose ps
