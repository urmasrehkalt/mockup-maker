from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from . import backlog, config, conversation, db, mockups, projects, testability
from .ai import AIError

# How each AI failure reaches the client: disabled and unavailable are the
# server's state, a bad answer or a timeout is the upstream model's fault.
AI_ERROR_STATUS = {"ai_disabled": 503, "ai_unavailable": 503,
                   "ai_timeout": 504, "ai_invalid_answer": 502}

PUBLIC_DIR = config.ROOT_DIR / "public"


@asynccontextmanager
async def lifespan(_: FastAPI):
    config.environment()  # fail fast on an invalid ENVIRONMENT
    config.ai_provider()  # ...and on an invalid AI_PROVIDER
    db.init()
    yield


app = FastAPI(title="Mockup Maker", version="0.1.0", lifespan=lifespan)


@app.get("/api/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/api/ai/status")
def ai_status() -> dict[str, object]:
    provider = config.ai_provider()
    return {"provider": provider, "enabled": provider != "off"}


@app.exception_handler(AIError)
async def ai_error_handler(_: Request, exc: AIError) -> JSONResponse:
    return JSONResponse(status_code=AI_ERROR_STATUS.get(exc.code, 502),
                        content={"error": {"code": exc.code, "message": str(exc)}})


app.include_router(projects.router)
app.include_router(conversation.router)
app.include_router(backlog.router)
app.include_router(mockups.router)
app.include_router(testability.router)

app.mount("/", StaticFiles(directory=PUBLIC_DIR, html=True), name="public")
