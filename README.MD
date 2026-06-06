# 1) Create & activate venv
python -m venv .venv
source .venv/bin/activate

source .venv/Scripts/activate
uvicorn app.main:app --reload

# 2) Install deps
pip install fastapi uvicorn[standard] sqlalchemy aiosqlite pydantic-settings

# 2.5) Configure local env if you do not already have a .env file
[ -f .env ] || cp .env.example .env
# Edit .env if you need to override DATABASE_URL or CORS_ORIGINS

For production, `CORS_ORIGINS` must include every browser origin that calls the
API. Subdomains are separate origins, so `https://game.arnaud-a.dev` must be
listed explicitly when the frontend is deployed there.

## Account authentication

Character and team routes are private campaign data. Reads and writes require a
short-lived account access token. Set a server-side token secret in `.env`:

```env
AUTH_TOKEN_SECRET=replace-with-a-long-random-secret
ACCESS_TOKEN_EXPIRES_SECONDS=3600
REFRESH_TOKEN_EXPIRES_SECONDS=2592000
REFRESH_TOKEN_COOKIE_SECURE=true
```

For local HTTP development, set `REFRESH_TOKEN_COOKIE_SECURE=false`. Production
must keep it `true` so refresh tokens are stored in an `HttpOnly`, `Secure`,
`SameSite` cookie.

Create the first account. This endpoint is public only while no users exist and
`ALLOW_FIRST_USER_REGISTRATION=true`. Passwords must be at least 12 characters:

```bash
curl -X POST http://127.0.0.1:8000/auth/register \
  -H "Content-Type: application/json" \
  -d '{"username":"admin","password":"replace-with-a-long-password"}'
```

Login to get an access token. The refresh token is set as an `HttpOnly` cookie:

```bash
response=$(curl -s -c cookies.txt -X POST http://127.0.0.1:8000/auth/login \
  -H "Content-Type: application/json" \
  -d '{"username":"admin","password":"replace-with-a-long-password"}')

token=$(python -c 'import json,sys; print(json.load(sys.stdin)["access_token"])' <<< "$response")
```

Call a protected route:

```bash
curl -X POST http://127.0.0.1:8000/characters \
  -H "Authorization: Bearer $token" \
  -H "Content-Type: application/json" \
  -d '{"slug":"hero","name":"Hero","race":"Human","stats":{"corps":50,"mental":50,"social":50}}'
```

Refresh tokens rotate on use:

```bash
response=$(curl -s -b cookies.txt -c cookies.txt -X POST http://127.0.0.1:8000/auth/refresh)

token=$(python -c 'import json,sys; print(json.load(sys.stdin)["access_token"])' <<< "$response")
```

Never expose `AUTH_TOKEN_SECRET` in a public frontend bundle. If the secret is
missing from the environment, protected routes fail closed and do not allow
writes.

# 3) Run the API
uvicorn app.main:app --reload
# If uvicorn not found: python -m uvicorn app.main:app --reload

app/
  __init__.py
  main.py              # FastAPI app + lifespan + CORS
  db.py                # async SQLAlchemy engine, Session, Base
  migrations.py        # startup migration ledger for fresh/existing SQLite databases
  models.py            # Character and Team models, including the character/team N-N relation
  routers/
    __init__.py
    characters.py      # POST /characters, GET /characters, GET /characters/{slug}, PATCH /characters/{slug}
    teams.py           # POST/GET/PATCH /teams and POST/DELETE /teams/{uuid}/characters/{slug}
data.db                 # created on first run




## Docker SQLite persistence

In Docker, `DATABASE_URL` is set to `sqlite+aiosqlite:////app/data/data.db`.
`docker-compose.yml` bind-mounts `./data` to `/app/data`,
so the SQLite database survives container rebuilds and restarts.

To initialize the mounted database from your current local database:

```bash
mkdir -p data
cp -f data.db data/data.db
```

SQLite database files are intentionally ignored by Git. Do not commit live
campaign data. Use the automatic Scaleway snapshots below for backups, or stop
writes and use SQLite's backup command for a one-off local export.

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
