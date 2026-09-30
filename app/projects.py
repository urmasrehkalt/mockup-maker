"""Projects: create, list, open and resume.

A project carries the guided process's current step, so reopening it can offer
the right next move. The resume suggestion is worked out here from the saved
step and history rather than by a model call: it is instant, and it still works
when the AI is off. It returns action ids; the frontend owns the wording.
"""
from __future__ import annotations

import json
import sqlite3
from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field

from . import backlog, db, mockups

Step = Literal["idea", "roles", "stories", "priorities", "criteria", "refinements", "grooming"]
Language = Literal["et", "en"]
STEPS: tuple[str, ...] = Step.__args__

# What to offer on reopen, by step: at most four actions, the likely one first.
RESUME_ACTIONS: dict[str, list[str]] = {
    "idea": ["continue_conversation"],
    "roles": ["continue_roles", "go_stories"],
    "stories": ["continue_stories", "view_backlog"],
    "priorities": ["choose_priority", "view_backlog"],
    "criteria": ["continue_criteria", "next_story", "view_backlog"],
    "refinements": ["enter_refinement", "next_story", "view_backlog"],
    "grooming": ["review_backlog", "view_backlog", "end_meeting"],
}


class _Stripped(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class ProjectIn(_Stripped):
    name: str = Field(min_length=1, max_length=120)
    description: str = Field(default="", max_length=1000)
    idea: str = Field(default="", max_length=4000)  # the client's idea, pre-filled for the first message
    language: Language = "et"  # the content's language; the AI writes in it


class ProjectPatch(_Stripped):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    description: str | None = Field(default=None, max_length=1000)
    step: Step | None = None
    current_story_id: int | None = None  # the story to start with
    language: Language | None = None  # applies to new content; existing stories keep their words


class Project(BaseModel):
    id: int
    name: str
    description: str
    step: Step
    current_story_id: int | None = None
    mvp_count: int | None = None
    draft_idea: str = ""
    language: Language = "et"
    created_at: str
    updated_at: str


class Message(BaseModel):
    id: int
    role: Literal["user", "assistant"]
    content: dict[str, Any]
    created_at: str


class Resume(BaseModel):
    step: Step
    kind: Literal["start", "continue"]
    actions: list[str]


class Role(_Stripped):
    name: str = Field(min_length=1, max_length=60)
    description: str = Field(default="", max_length=300)


class Clarification(BaseModel):
    question: str
    answer: str | None  # None: the user skipped it


class ProjectState(BaseModel):
    project: Project
    roles: list[Role]
    stories: list[backlog.Story]
    mockups: list[mockups.Mockup]
    undo: backlog.Undo | None
    messages: list[Message]
    resume: Resume


# --- storage -------------------------------------------------------------

def create(conn: sqlite3.Connection, data: ProjectIn) -> Project:
    stamp = db.now()
    with conn:
        cur = conn.execute(
            "INSERT INTO projects (name, description, draft_idea, language, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?)", (data.name, data.description, data.idea, data.language, stamp, stamp))
    return get(conn, cur.lastrowid)


def get(conn: sqlite3.Connection, project_id: int) -> Project:
    row = conn.execute("SELECT * FROM projects WHERE id = ?", (project_id,)).fetchone()
    if row is None:
        raise HTTPException(404, "Project not found")
    return Project(**dict(row))


def list_all(conn: sqlite3.Connection) -> list[Project]:
    rows = conn.execute("SELECT * FROM projects ORDER BY updated_at DESC, id DESC").fetchall()
    return [Project(**dict(row)) for row in rows]


def update(conn: sqlite3.Connection, project_id: int, patch: ProjectPatch) -> Project:
    get(conn, project_id)
    fields = patch.model_dump(exclude_none=True)
    if "current_story_id" in fields:
        backlog.get_story(conn, project_id, fields["current_story_id"])  # must be this project's
    if fields:
        fields["updated_at"] = db.now()
        assignments = ", ".join(f"{name} = ?" for name in fields)
        with conn:
            conn.execute(f"UPDATE projects SET {assignments} WHERE id = ?",
                         (*fields.values(), project_id))
    return get(conn, project_id)


touch = db.touch_project


def add_message(conn: sqlite3.Connection, project_id: int, role: str,
                content: dict[str, Any]) -> Message:
    stamp = db.now()
    with conn:
        cur = conn.execute(
            "INSERT INTO messages (project_id, role, content, created_at) VALUES (?, ?, ?, ?)",
            (project_id, role, json.dumps(content, ensure_ascii=False), stamp))
        touch(conn, project_id)
    return Message(id=cur.lastrowid, role=role, content=content, created_at=stamp)


def update_message(conn: sqlite3.Connection, message_id: int, content: dict[str, Any]) -> None:
    conn.execute("UPDATE messages SET content = ? WHERE id = ?",
                 (json.dumps(content, ensure_ascii=False), message_id))


def get_message(conn: sqlite3.Connection, project_id: int, message_id: int) -> Message:
    row = conn.execute("SELECT * FROM messages WHERE id = ? AND project_id = ?",
                       (message_id, project_id)).fetchone()
    if row is None:
        raise HTTPException(404, "Message not found")
    return Message(id=row["id"], role=row["role"], content=json.loads(row["content"]),
                   created_at=row["created_at"])


def messages(conn: sqlite3.Connection, project_id: int) -> list[Message]:
    rows = conn.execute("SELECT * FROM messages WHERE project_id = ? ORDER BY id",
                        (project_id,)).fetchall()
    return [Message(id=row["id"], role=row["role"], content=json.loads(row["content"]),
                    created_at=row["created_at"]) for row in rows]


def roles(conn: sqlite3.Connection, project_id: int) -> list[Role]:
    rows = conn.execute("SELECT name, description FROM roles WHERE project_id = ? ORDER BY position",
                        (project_id,)).fetchall()
    return [Role(**dict(row)) for row in rows]


def replace_roles(conn: sqlite3.Connection, project_id: int, new_roles: list[Role]) -> None:
    """Store the user's confirmed roles, dropping duplicate names (case-insensitive)."""
    seen: set[str] = set()
    unique = [r for r in new_roles if not (r.name.casefold() in seen or seen.add(r.name.casefold()))]
    conn.execute("DELETE FROM roles WHERE project_id = ?", (project_id,))
    conn.executemany(
        "INSERT INTO roles (project_id, name, description, position) VALUES (?, ?, ?, ?)",
        [(project_id, r.name, r.description, i) for i, r in enumerate(unique)])
    touch(conn, project_id)


def clarifications(conn: sqlite3.Connection, project_id: int) -> list[Clarification]:
    rows = conn.execute("SELECT question, answer FROM clarifications WHERE project_id = ? ORDER BY id",
                        (project_id,)).fetchall()
    return [Clarification(**dict(row)) for row in rows]


def add_clarification(conn: sqlite3.Connection, project_id: int, message_id: int | None,
                      question: str, answer: str | None) -> None:
    conn.execute(
        "INSERT INTO clarifications (project_id, message_id, question, answer, created_at) "
        "VALUES (?, ?, ?, ?, ?)", (project_id, message_id, question, answer, db.now()))


def resume(project: Project, history: list[Message]) -> Resume:
    if project.step == "idea" and not history:
        return Resume(step="idea", kind="start", actions=[])
    return Resume(step=project.step, kind="continue", actions=RESUME_ACTIONS[project.step])


def state(conn: sqlite3.Connection, project_id: int) -> ProjectState:
    project = get(conn, project_id)
    history = messages(conn, project_id)
    return ProjectState(project=project, roles=roles(conn, project_id),
                        stories=backlog.stories(conn, project_id),
                        mockups=mockups.mockups(conn, project_id),
                        undo=backlog.last_undo(conn, project_id), messages=history,
                        resume=resume(project, history))


# --- API -----------------------------------------------------------------

router = APIRouter(prefix="/api/projects", tags=["projects"])


@router.get("", response_model=list[Project])
def list_projects(conn: sqlite3.Connection = Depends(db.get_db)):
    return list_all(conn)


@router.post("", response_model=Project, status_code=201)
def create_project(data: ProjectIn, conn: sqlite3.Connection = Depends(db.get_db)):
    return create(conn, data)


@router.get("/{project_id}", response_model=ProjectState)
def open_project(project_id: int, conn: sqlite3.Connection = Depends(db.get_db)):
    return state(conn, project_id)


@router.patch("/{project_id}", response_model=Project)
def patch_project(project_id: int, patch: ProjectPatch,
                  conn: sqlite3.Connection = Depends(db.get_db)):
    return update(conn, project_id, patch)
