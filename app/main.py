import asyncio
import logging
from contextlib import asynccontextmanager
from fastapi import FastAPI
from .db import engine
from .db_snapshot import create_and_upload_database_snapshot
from .migrations import run_migrations
from .routers import auth, characters, portraits, teams
from fastapi.middleware.cors import CORSMiddleware
from .config import get_settings

settings = get_settings()
logger = logging.getLogger(__name__)

@asynccontextmanager
async def lifespan(app: FastAPI):
    await run_migrations(engine)
    try:
        yield
    finally:
        try:
            object_key = await asyncio.to_thread(create_and_upload_database_snapshot, settings)
            if object_key:
                logger.info("Uploaded database shutdown snapshot to %s", object_key)
        except Exception:
            logger.exception("Failed to upload database shutdown snapshot")
        # shutdown: cleanly close the engine
        await engine.dispose()

app = FastAPI(lifespan=lifespan)
app.include_router(auth.router, prefix="/auth", tags=["auth"])
app.include_router(characters.router, prefix="/characters", tags=["characters"])
app.include_router(portraits.router, prefix="/characters", tags=["character portraits"])
app.include_router(teams.router, prefix="/teams", tags=["teams"])
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type", "ngrok-skip-browser-warning"],
)

@app.get("/")
def read_root():
    return {"Hello": "World"}

@app.get("/health")
def health():
    return {"ok": True}

