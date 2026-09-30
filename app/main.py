from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from . import config, db

PUBLIC_DIR = config.ROOT_DIR / "public"


@asynccontextmanager
async def lifespan(_: FastAPI):
    config.environment()  # fail fast on an invalid ENVIRONMENT
    db.init()
    yield


app = FastAPI(title="Mockup Maker", version="0.1.0", lifespan=lifespan)


@app.get("/api/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


app.mount("/", StaticFiles(directory=PUBLIC_DIR, html=True), name="public")
