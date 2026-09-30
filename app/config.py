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
