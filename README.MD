# 1) Create & activate venv
python -m venv .venv
# Windows
source .venv/Scripts/activate
.\.venv\Scripts\activate
# mac/linux
# source .venv/bin/activate

# 2) Install deps
pip install fastapi uvicorn[standard] sqlalchemy aiosqlite pydantic-settings

# 2.5) Configure local env if you do not already have a .env file
if (!(Test-Path .env)) { Copy-Item .env.example .env }
# Edit .env if you need to override DATABASE_URL or CORS_ORIGINS

# 3) Run the API
uvicorn app.main:app --reload
# If uvicorn not found: python -m uvicorn app.main:app --reload

app/
  __init__.py
  main.py              # FastAPI app + lifespan + CORS
  db.py                # async SQLAlchemy engine, Session, Base
  models.py            # Character and Team models, including the character/team N-N relation
  routers/
    __init__.py
    characters.py      # POST /characters, GET /characters, GET /characters/{slug}, PATCH /characters/{slug}
    teams.py           # POST/GET/PATCH /teams and POST/DELETE /teams/{uuid}/characters/{slug}
data.db                 # created on first run


source .venv/Scripts/activate
uvicorn app.main:app --reload

## Docker SQLite persistence

In Docker, `DATABASE_URL` is set to `sqlite+aiosqlite:////app/data/data.db`.
`docker-compose.yml` bind-mounts `./data` to `/app/data`,
so the SQLite database survives container rebuilds and restarts.

To initialize the mounted database from your current local database:

```powershell
New-Item -ItemType Directory -Force data
Copy-Item -Force data.db data\data.db
```

For Git snapshots, stop writes first or use SQLite's backup command, then commit
the copied `.db` file. Do not rely on committing a live database while the API is
writing to it.

## Automatic shutdown database snapshots

When the API shuts down cleanly, it creates a SQLite backup and uploads it to
Scaleway Object Storage. With the default `.env.example` values, snapshots are
stored in bucket `trpg-files` under keys like:

```text
save/data-20260520T183000Z.db
```

Required settings:

```env
SCW_ACCESS_KEY=...
SCW_SECRET_KEY=...
SCW_OBJECT_STORAGE_BUCKET=trpg-files
SCW_OBJECT_STORAGE_REGION=fr-par
SCW_OBJECT_STORAGE_ENDPOINT=https://s3.fr-par.scw.cloud
DB_SNAPSHOT_ON_SHUTDOWN=true
DB_SNAPSHOT_PREFIX=save
```

Docker Compose gives the API a `60s` stop grace period so the upload can finish
when you run `docker compose down` or `docker compose stop api`.

## VPS gateway

The public Caddy container lives in `../vps-gateway-project`.

This stack only runs the TRPG API and joins the shared Docker network named
`web`, so the gateway can route `api.arnaud-a.dev` to `trpg-api:8000`.
