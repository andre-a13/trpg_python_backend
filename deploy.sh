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

echo "==> Waiting for backend container health"
for attempt in $(seq 1 30); do
    api_container="$(docker compose ps -q api || true)"
    if [ -n "${api_container}" ] && [ "$(docker inspect -f '{{.State.Running}}' "${api_container}")" = "true" ]; then
        if docker compose exec -T api python - <<'PY' >/dev/null 2>&1
import urllib.request

urllib.request.urlopen("http://127.0.0.1:8000/health", timeout=2).read()
PY
        then
            echo "Backend container is healthy."
            break
        fi
    fi

    if [ "${attempt}" -eq 30 ]; then
        echo "ERROR: Backend container did not become healthy."
        docker compose ps
        docker compose logs --tail=120 api
        exit 1
    fi

    sleep 2
done

echo "==> Checking backend health"
health_url="${HEALTH_URL:-https://api.arnaud-a.dev/health}"
for attempt in $(seq 1 10); do
    if curl -fsS "${health_url}" >/dev/null; then
        echo "Backend health endpoint is reachable: ${health_url}"
        break
    fi

    if [ "${attempt}" -eq 10 ]; then
        echo "ERROR: Backend health endpoint failed: ${health_url}"
        docker compose ps
        docker compose logs --tail=120 api
        exit 1
    fi

    sleep 3
done

echo "==> Backend status"
docker compose ps
