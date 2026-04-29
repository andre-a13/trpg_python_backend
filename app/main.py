from contextlib import asynccontextmanager
from fastapi import FastAPI
from .db import engine, Base
from .routers import characters
from fastapi.middleware.cors import CORSMiddleware
from .config import get_settings

settings = get_settings()

@asynccontextmanager
async def lifespan(app: FastAPI):
    # startup: create tables (idempotent)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    try:
        yield
    finally:
        # shutdown: cleanly close the engine
        await engine.dispose()

app = FastAPI(lifespan=lifespan)
app.include_router(characters.router, prefix="/characters", tags=["characters"])
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.get("/")
def read_root():
    return {"Hello": "World"}

@app.get("/health")
def health():
    return {"ok": True}

