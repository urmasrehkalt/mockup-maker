"""Ideas: what the client thought of along the way, kept until it becomes something.

An idea is stored the moment the AI offers to classify a free-text thought, so
nothing the client says is lost even if the card is ignored. It stays `open` (and
listed beside the backlog) until the user turns it into a new view or a refinement,
or dismisses it. Storing an idea never touches the backlog, a story or a mockup:
that happens only through the new view or the refinement the user chooses, and those
have their own confirmation cards.
"""
from __future__ import annotations

import sqlite3
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field

from . import db, projects

Conversion = Literal["new_view", "refinement"]


class IdeaIn(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    text: str = Field(min_length=1, max_length=1000)


class DecisionIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    decision: Literal["park", "dismiss"]


def create(conn: sqlite3.Connection, project_id: int, text: str, message_id: int | None = None) -> int:
    """Store an open idea. Caller owns the transaction."""
    cur = conn.execute("INSERT INTO ideas (project_id, text, message_id, created_at) VALUES (?, ?, ?, ?)",
                       (project_id, text, message_id, db.now()))
    return cur.lastrowid


def attach_card(conn: sqlite3.Connection, idea_id: int, message_id: int) -> None:
    conn.execute("UPDATE ideas SET message_id = ? WHERE id = ?", (message_id, idea_id))


def get(conn: sqlite3.Connection, project_id: int, idea_id: int) -> sqlite3.Row:
    row = conn.execute("SELECT * FROM ideas WHERE id = ? AND project_id = ?", (idea_id, project_id)).fetchone()
    if row is None:
        raise HTTPException(404, "Idea not found")
    return row


def _open(conn: sqlite3.Connection, project_id: int, idea_id: int) -> sqlite3.Row:
    row = get(conn, project_id, idea_id)
    if row["status"] != "open":
        raise HTTPException(409, {"code": "idea_closed", "message": "That idea was already dealt with."})
    return row


def _decide_card(conn: sqlite3.Connection, project_id: int, row: sqlite3.Row, choice: str) -> None:
    """Show on the idea's card what became of it."""
    if row["message_id"] is None:
        return
    try:
        message = projects.get_message(conn, project_id, row["message_id"])
    except HTTPException:
        return
    card = message.content.get("idea")
    if card and "decided" not in card:
        card["decided"] = {"choice": choice}
        projects.update_message(conn, message.id, message.content)


def convert(conn: sqlite3.Connection, project_id: int, idea_id: int, to: Conversion) -> str:
    """The user chose to make it a view or a refinement: the idea is done, return its text.
    Caller owns the transaction."""
    row = _open(conn, project_id, idea_id)
    conn.execute("UPDATE ideas SET status = 'converted', converted_to = ?, resolved_at = ? WHERE id = ?",
                 (to, db.now(), idea_id))
    _decide_card(conn, project_id, row, "new_view" if to == "new_view" else "refine")
    return row["text"]


def decide(conn: sqlite3.Connection, project_id: int, idea_id: int, decision: str) -> None:
    """Park (leave it listed, close its card) or dismiss (drop it)."""
    row = _open(conn, project_id, idea_id)
    with conn:
        if decision == "dismiss":
            conn.execute("UPDATE ideas SET status = 'dismissed', resolved_at = ? WHERE id = ?",
                         (db.now(), idea_id))
        _decide_card(conn, project_id, row, "dismiss" if decision == "dismiss" else "park")
        db.touch_project(conn, project_id)


def texts(conn: sqlite3.Connection, project_id: int) -> list[str]:
    return [idea.text for idea in projects.open_ideas(conn, project_id)]


# --- API -----------------------------------------------------------------

router = APIRouter(prefix="/api/projects/{project_id}/ideas", tags=["ideas"])


@router.post("", response_model=projects.ProjectState, status_code=201)
def post_idea(project_id: int, data: IdeaIn, conn: sqlite3.Connection = Depends(db.get_db)):
    """Add a thought by hand, without the AI."""
    projects.get(conn, project_id)
    with conn:
        create(conn, project_id, data.text)
        db.touch_project(conn, project_id)
    return projects.state(conn, project_id)


@router.put("/{idea_id}/decision", response_model=projects.ProjectState)
def put_decision(project_id: int, idea_id: int, data: DecisionIn, conn: sqlite3.Connection = Depends(db.get_db)):
    decide(conn, project_id, idea_id, data.decision)
    return projects.state(conn, project_id)
