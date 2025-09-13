# 1) Create & activate venv
python -m venv .venv
# Windows
.\.venv\Scripts\activate
# mac/linux
# source .venv/bin/activate

# 2) Install deps
pip install fastapi uvicorn[standard] sqlalchemy aiosqlite pydantic-settings

# 3) Run the API
uvicorn app.main:app --reload
# If uvicorn not found: python -m uvicorn app.main:app --reload

# 4) Run the ngrok tunnel
ngrok http 8000 --url https://gratifying-axel-mercantile.ngrok-free.app

app/
  __init__.py
  main.py              # FastAPI app + lifespan + CORS
  db.py                # async SQLAlchemy engine, Session, Base
  models.py            # Character model (slug, name, race, stats, skills*, inventory, gold)
  routers/
    __init__.py
    characters.py      # POST /characters, GET /characters, GET /characters/{slug}, PATCH /characters/{slug}
data.db                 # created on first run


