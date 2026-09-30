"""The backlog: user stories with their Connextra parts stored separately.

An Estonian Connextra title needs the role in the essive case ("Klubi liikmena
soovin ..."), which cannot be derived from the role's name by rule. A story
therefore keeps both: `role_name` ties it to the project's roles, and
`role_phrase` is the role as the title says it. The title is composed from the
parts, never stored on its own, so it cannot drift from them.
"""
from __future__ import annotations

import json
import sqlite3
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from . import db

Status = Literal["idea", "needs_clarification", "reviewed", "ready"]
Size = Literal["S", "M", "L"]
Origin = Literal["ai", "manual"]


class StoryParts(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    role_name: str = Field(min_length=1, max_length=60)
    role_phrase: str = Field(min_length=1, max_length=80)
    action: str = Field(min_length=1, max_length=300)
    benefit: str = Field(min_length=1, max_length=300)


class Story(StoryParts):
    id: int
    number: int
    key: str
    title: str
    status: Status
    position: int
    size: Size | None
    origin: Origin
    open_questions: list[str]
    notes: str
    created_at: str
    updated_at: str


def title(parts: StoryParts) -> str:
    phrase = parts.role_phrase[:1].upper() + parts.role_phrase[1:]
    return f"{phrase} soovin {parts.action}, et {parts.benefit.rstrip('.')}."


def _story(row: sqlite3.Row) -> Story:
    data = dict(row)
    data["open_questions"] = json.loads(data["open_questions"])
    data.pop("project_id")
    parts = StoryParts(**{k: data[k] for k in StoryParts.model_fields})
    return Story(**data, key=f"US-{data['number']}", title=title(parts))


def stories(conn: sqlite3.Connection, project_id: int) -> list[Story]:
    rows = conn.execute("SELECT * FROM stories WHERE project_id = ? ORDER BY position, id",
                        (project_id,)).fetchall()
    return [_story(row) for row in rows]


def add_stories(conn: sqlite3.Connection, project_id: int, new: list[StoryParts],
                origin: Origin) -> list[Story]:
    """Append stories to the end of the backlog. The caller owns the transaction."""
    number, position = conn.execute(
        "SELECT COALESCE(MAX(number), 0), COALESCE(MAX(position), -1) FROM stories "
        "WHERE project_id = ?", (project_id,)).fetchone()
    stamp = db.now()
    ids = []
    for parts in new:
        number += 1
        position += 1
        cur = conn.execute(
            "INSERT INTO stories (project_id, number, role_name, role_phrase, action, benefit, "
            "position, origin, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (project_id, number, parts.role_name, parts.role_phrase, parts.action, parts.benefit,
             position, origin, stamp, stamp))
        ids.append(cur.lastrowid)
    db.touch_project(conn, project_id)
    placeholders = ", ".join("?" * len(ids))
    rows = conn.execute(f"SELECT * FROM stories WHERE id IN ({placeholders}) ORDER BY position",
                        ids).fetchall() if ids else []
    return [_story(row) for row in rows]


def snapshot(conn: sqlite3.Connection, project_id: int) -> list[dict]:
    """The backlog as the AI sees it: current state, including manual edits."""
    return [{"key": s.key, "role_name": s.role_name, "title": s.title, "status": s.status,
             "size": s.size, "open_questions": s.open_questions}
            for s in stories(conn, project_id)]
