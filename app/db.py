"""SQLite storage: connections and schema migrations.

Migrations are applied in order and tracked with PRAGMA user_version, so an
existing database is upgraded in place and never recreated.
"""
import sqlite3
from pathlib import Path

from . import config

# Each entry is one migration; append only, never edit a released one.
MIGRATIONS: list[str] = []


def connect(path: Path | None = None) -> sqlite3.Connection:
    path = path or config.database_path()
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init(path: Path | None = None) -> None:
    path = path or config.database_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = connect(path)
    try:
        conn.execute("PRAGMA journal_mode = WAL")
        version = conn.execute("PRAGMA user_version").fetchone()[0]
        for number, script in enumerate(MIGRATIONS[version:], start=version + 1):
            with conn:
                conn.executescript(script)
                conn.execute(f"PRAGMA user_version = {number}")
    finally:
        conn.close()


def schema_version(path: Path | None = None) -> int:
    conn = connect(path)
    try:
        return conn.execute("PRAGMA user_version").fetchone()[0]
    finally:
        conn.close()
