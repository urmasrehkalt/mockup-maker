"""Environment configuration.

Values come from the process environment; a local `.env` file fills in anything
not already set. An unset ENVIRONMENT means development, never production.
"""
import os
from pathlib import Path

from dotenv import load_dotenv

ROOT_DIR = Path(__file__).resolve().parent.parent

load_dotenv(ROOT_DIR / ".env", override=False)

ENVIRONMENTS = ("development", "test", "production")


def environment() -> str:
    value = os.environ.get("ENVIRONMENT", "development").strip().lower()
    if value not in ENVIRONMENTS:
        raise ValueError(f"ENVIRONMENT must be one of {ENVIRONMENTS}, got {value!r}")
    return value


def is_production() -> bool:
    return environment() == "production"


def database_path() -> Path:
    value = os.environ.get("DATABASE_PATH", "").strip()
    path = Path(value) if value else ROOT_DIR / "data" / "mockup-maker.db"
    return path if path.is_absolute() else ROOT_DIR / path


AI_PROVIDERS = ("codex", "mock", "off")
DEFAULT_AI_MODEL = "gpt-6-astra"
DEFAULT_AI_TIMEOUT = 180


def ai_provider() -> str:
    """`codex`, `mock` or `off`. Defaults to `mock`, so a fresh checkout and the
    test suite never reach for the network or a Codex login."""
    value = os.environ.get("AI_PROVIDER", "mock").strip().lower()
    if value not in AI_PROVIDERS:
        raise ValueError(f"AI_PROVIDER must be one of {AI_PROVIDERS}, got {value!r}")
    return value


def ai_model() -> str:
    return os.environ.get("AI_MODEL", "").strip() or DEFAULT_AI_MODEL


def ai_reasoning() -> str:
    """Codex `model_reasoning_effort`. `low` keeps a guided conversation responsive."""
    value = os.environ.get("AI_REASONING", "low").strip().lower()
    return value if value in ("low", "medium", "high") else "low"


def ai_timeout() -> int:
    raw = os.environ.get("AI_TIMEOUT", "").strip()
    return int(raw) if raw.isdigit() and int(raw) > 0 else DEFAULT_AI_TIMEOUT


def codex_binary() -> str | None:
    import shutil

    named = os.environ.get("CODEX_BIN", "").strip()
    if named:
        return named if Path(named).exists() else None
    return shutil.which("codex")


def codex_home() -> str | None:
    """Codex reads its ChatGPT login from here; `--ignore-user-config` still honours it."""
    return os.environ.get("CODEX_HOME", "").strip() or None


def tracker_url() -> str | None:
    """The Agile Tracker's API base, reached by the server (e.g. http://127.0.0.1:8000).
    Unset: the push is not offered."""
    return os.environ.get("TRACKER_URL", "").strip().rstrip("/") or None


def tracker_public_url() -> str | None:
    """Where people open the tracker in a browser, for links; optional."""
    return os.environ.get("TRACKER_PUBLIC_URL", "").strip().rstrip("/") or None


def tracker_points() -> dict[str, int]:
    """Story size to tracker points, from e.g. TRACKER_POINTS="S=2,M=5,L=8"."""
    points = {"S": 2, "M": 5, "L": 8}
    for pair in os.environ.get("TRACKER_POINTS", "").split(","):
        size, _, value = pair.partition("=")
        if size.strip().upper() in points and value.strip().isdigit():
            points[size.strip().upper()] = int(value)
    return points


def tracker_timeout() -> int:
    raw = os.environ.get("TRACKER_TIMEOUT", "").strip()
    return int(raw) if raw.isdigit() and int(raw) > 0 else 10
