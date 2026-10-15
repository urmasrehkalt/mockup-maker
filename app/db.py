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
    # 3: the backlog
    """
    CREATE TABLE stories (
        id             INTEGER PRIMARY KEY AUTOINCREMENT,
        project_id     INTEGER NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
        number         INTEGER NOT NULL,
        role_name      TEXT NOT NULL,
        role_phrase    TEXT NOT NULL,
        action         TEXT NOT NULL,
        benefit        TEXT NOT NULL,
        status         TEXT NOT NULL DEFAULT 'idea'
                       CHECK (status IN ('idea', 'needs_clarification', 'reviewed', 'ready')),
        position       INTEGER NOT NULL,
        size           TEXT CHECK (size IN ('S', 'M', 'L')),
        origin         TEXT NOT NULL CHECK (origin IN ('ai', 'manual')),
        open_questions TEXT NOT NULL DEFAULT '[]',
        notes          TEXT NOT NULL DEFAULT '',
        created_at     TEXT NOT NULL,
        updated_at     TEXT NOT NULL,
        UNIQUE (project_id, number)
    );
    CREATE INDEX stories_by_project ON stories(project_id, position);
    """,
    # 4: acceptance criteria, undo history, story numbers that are never reused
    """
    CREATE TABLE criteria (
        id          INTEGER PRIMARY KEY AUTOINCREMENT,
        story_id    INTEGER NOT NULL REFERENCES stories(id) ON DELETE CASCADE,
        text        TEXT NOT NULL,
        position    INTEGER NOT NULL,
        origin      TEXT NOT NULL CHECK (origin IN ('ai', 'manual')),
        created_at  TEXT NOT NULL
    );
    CREATE INDEX criteria_by_story ON criteria(story_id, position);
    CREATE TABLE undo_log (
        id          INTEGER PRIMARY KEY AUTOINCREMENT,
        project_id  INTEGER NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
        action      TEXT NOT NULL,
        params      TEXT NOT NULL DEFAULT '{}',
        snapshot    TEXT NOT NULL,
        created_at  TEXT NOT NULL
    );
    ALTER TABLE projects ADD COLUMN story_seq INTEGER NOT NULL DEFAULT 0;
    UPDATE projects SET story_seq =
        (SELECT COALESCE(MAX(number), 0) FROM stories WHERE stories.project_id = projects.id);
    """,
    # 5: the story the process is working on (chosen in the priorities step)
    """
    ALTER TABLE projects ADD COLUMN current_story_id INTEGER
        REFERENCES stories(id) ON DELETE SET NULL;
    """,
    # 6: mockups, their versions, and which stories they belong to
    """
    CREATE TABLE mockups (
        id          INTEGER PRIMARY KEY AUTOINCREMENT,
        project_id  INTEGER NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
        title       TEXT NOT NULL,
        created_at  TEXT NOT NULL,
        updated_at  TEXT NOT NULL
    );
    CREATE TABLE mockup_versions (
        id          INTEGER PRIMARY KEY AUTOINCREMENT,
        mockup_id   INTEGER NOT NULL REFERENCES mockups(id) ON DELETE CASCADE,
        number      INTEGER NOT NULL,
        tree        TEXT NOT NULL,
        note        TEXT NOT NULL DEFAULT '',
        created_at  TEXT NOT NULL,
        UNIQUE (mockup_id, number)
    );
    CREATE TABLE story_mockups (
        story_id    INTEGER NOT NULL REFERENCES stories(id) ON DELETE CASCADE,
        mockup_id   INTEGER NOT NULL REFERENCES mockups(id) ON DELETE CASCADE,
        PRIMARY KEY (story_id, mockup_id)
    );
    """,
    # 7: which mockup element a criterion is about
    """
    ALTER TABLE criteria ADD COLUMN component_id TEXT;
    """,
    # 8: whether a story is about a view (and so needs a mockup to be ready)
    """
    ALTER TABLE stories ADD COLUMN needs_view INTEGER NOT NULL DEFAULT 1;
    """,
    # 9: the MVP line, as the number of stories above it (NULL: no line)
    """
    ALTER TABLE projects ADD COLUMN mvp_count INTEGER;
    """,
    # 10: what was sent to the Agile Tracker, so a second push updates instead of duplicating
    """
    ALTER TABLE projects ADD COLUMN tracker_project_id INTEGER;
    CREATE TABLE tracker_links (
        story_id          INTEGER PRIMARY KEY REFERENCES stories(id) ON DELETE CASCADE,
        tracker_story_id  INTEGER NOT NULL,
        mockup_hash       TEXT,
        pushed_at         TEXT NOT NULL
    );
    """,
    # 11: freehand annotations drawn on top of a mockup version
    """
    ALTER TABLE mockup_versions ADD COLUMN annotations TEXT NOT NULL DEFAULT '[]';
    """,
    # 12: project templates saved by the user, and a project's not-yet-sent first idea
    """
    CREATE TABLE prompt_templates (
        id          INTEGER PRIMARY KEY AUTOINCREMENT,
        name        TEXT NOT NULL,
        description TEXT NOT NULL DEFAULT '',
        idea        TEXT NOT NULL,
        created_at  TEXT NOT NULL
    );
    ALTER TABLE projects ADD COLUMN draft_idea TEXT NOT NULL DEFAULT '';
    """,
    # 13: the language a project's content is written in (the AI writes in it too)
    """
    ALTER TABLE projects ADD COLUMN language TEXT NOT NULL DEFAULT 'et' CHECK (language IN ('et', 'en'));
    """,
    # 14: the AI chat beside a mockup; `version` is the version an assistant answer created
    """
    CREATE TABLE mockup_messages (
        id          INTEGER PRIMARY KEY AUTOINCREMENT,
        mockup_id   INTEGER NOT NULL REFERENCES mockups(id) ON DELETE CASCADE,
        role        TEXT NOT NULL CHECK (role IN ('user', 'assistant')),
        text        TEXT NOT NULL,
        version     INTEGER,
        story_keys  TEXT NOT NULL DEFAULT '[]',
        undone      INTEGER NOT NULL DEFAULT 0,
        created_at  TEXT NOT NULL
    );
    """,
    # 15: conversation inputs waiting for their turn (done ones are deleted; messages keep the history)
    """
    CREATE TABLE turns (
        id             INTEGER PRIMARY KEY AUTOINCREMENT,
        project_id     INTEGER NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
        input          TEXT NOT NULL,
        status         TEXT NOT NULL DEFAULT 'queued' CHECK (status IN ('queued', 'running', 'failed')),
        error_code     TEXT,
        error_message  TEXT,
        created_at     TEXT NOT NULL
    );
    """,
    # 16: ideas the client had along the way, kept until they become a view or a refinement
    """
    CREATE TABLE ideas (
        id            INTEGER PRIMARY KEY AUTOINCREMENT,
        project_id    INTEGER NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
        text          TEXT NOT NULL,
        status        TEXT NOT NULL DEFAULT 'open' CHECK (status IN ('open', 'converted', 'dismissed')),
        converted_to  TEXT CHECK (converted_to IN ('new_view', 'refinement')),
        message_id    INTEGER,
        created_at    TEXT NOT NULL,
        resolved_at   TEXT
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


def touch_project(conn: sqlite3.Connection, project_id: int) -> None:
    """Mark a project as changed, so the project list shows it first."""
    conn.execute("UPDATE projects SET updated_at = ? WHERE id = ?", (now(), project_id))


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
