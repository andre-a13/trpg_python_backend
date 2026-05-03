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
