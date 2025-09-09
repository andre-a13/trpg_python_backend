from contextlib import asynccontextmanager
from fastapi import FastAPI
from .db import engine, Base
from .routers import characters
from fastapi.middleware.cors import CORSMiddleware

origins = [
    "http://localhost:5173",
    "http://127.0.0.1:5173",
    "https://arnaud-a.dev",           # add your prod domain when ready
]


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
    allow_origins=origins,
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

