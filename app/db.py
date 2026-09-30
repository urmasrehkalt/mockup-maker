"""SQLite storage: connections and schema migrations.

Migrations are applied in order and tracked with PRAGMA user_version, so an
existing database is upgraded in place and never recreated.
"""
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from . import config

# Each entry is one migration; append only, never edit a released one.
MIGRATIONS: list[str] = [
    # 1: projects and their conversation
    """
    CREATE TABLE projects (
        id          INTEGER PRIMARY KEY AUTOINCREMENT,
        name        TEXT NOT NULL,
        description TEXT NOT NULL DEFAULT '',
        step        TEXT NOT NULL DEFAULT 'idea',
        created_at  TEXT NOT NULL,
        updated_at  TEXT NOT NULL
    );
    CREATE TABLE messages (
        id          INTEGER PRIMARY KEY AUTOINCREMENT,
        project_id  INTEGER NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
        role        TEXT NOT NULL CHECK (role IN ('user', 'assistant')),
        content     TEXT NOT NULL,
        created_at  TEXT NOT NULL
    );
    CREATE INDEX messages_by_project ON messages(project_id, id);
    """,
    # 2: state the guided conversation builds up, kept outside the chat history
    """
    CREATE TABLE roles (
        id          INTEGER PRIMARY KEY AUTOINCREMENT,
        project_id  INTEGER NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
        name        TEXT NOT NULL,
        description TEXT NOT NULL DEFAULT '',
        position    INTEGER NOT NULL
    );
    CREATE TABLE clarifications (
        id          INTEGER PRIMARY KEY AUTOINCREMENT,
        project_id  INTEGER NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
        message_id  INTEGER REFERENCES messages(id) ON DELETE SET NULL,
        question    TEXT NOT NULL,
        answer      TEXT,
        created_at  TEXT NOT NULL
    );
    """,
]


def connect(path: Path | None = None) -> sqlite3.Connection:
    path = path or config.database_path()
    # A request's connection is used by one request at a time, but FastAPI may
    # hand it between worker threads, so the same-thread check is switched off.
    conn = sqlite3.connect(path, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def get_db():
    """FastAPI dependency: one connection per request."""
    conn = connect()
    try:
        yield conn
    finally:
        conn.close()


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


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
