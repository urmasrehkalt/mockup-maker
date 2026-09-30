"""The backlog: user stories with their Connextra parts stored separately.

An Estonian Connextra title needs the role in the essive case ("Klubi liikmena
soovin ..."), which cannot be derived from the role's name by rule. A story
therefore keeps both: `role_name` ties it to the project's roles, and
`role_phrase` is the role as the title says it. The title is composed from the
parts, never stored on its own, so it cannot drift from them.

Every change to the backlog first records a snapshot in `undo_log`, inside the
same transaction, so the last change can always be taken back. Manual
management never touches the AI.
"""
from __future__ import annotations

import json
import sqlite3
from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field

from . import db

Status = Literal["idea", "needs_clarification", "reviewed", "ready"]
Size = Literal["S", "M", "L"]
Origin = Literal["ai", "manual"]

UNDO_DEPTH = 20


class _Input(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class StoryParts(_Input):
    role_name: str = Field(min_length=1, max_length=60)
    role_phrase: str = Field(min_length=1, max_length=80)
    action: str = Field(min_length=1, max_length=300)
    benefit: str = Field(min_length=1, max_length=300)


class StoryIn(StoryParts):
    size: Size | None = None
    status: Status = "idea"
    criteria: list[str] = Field(default_factory=list, max_length=30)
    open_questions: list[str] = Field(default_factory=list, max_length=20)
    notes: str = Field(default="", max_length=2000)


class StoryPatch(_Input):
    role_name: str | None = Field(default=None, min_length=1, max_length=60)
    role_phrase: str | None = Field(default=None, min_length=1, max_length=80)
    action: str | None = Field(default=None, min_length=1, max_length=300)
    benefit: str | None = Field(default=None, min_length=1, max_length=300)
    size: Size | None = None
    clear_size: bool = False
    status: Status | None = None
    criteria: list[str] | None = Field(default=None, max_length=30)
    open_questions: list[str] | None = Field(default=None, max_length=20)
    notes: str | None = Field(default=None, max_length=2000)


class Order(_Input):
    ids: list[int]


class Criterion(BaseModel):
    id: int
    text: str
    origin: Origin


class Story(StoryParts):
    model_config = ConfigDict(extra="ignore")
    id: int
    number: int
    key: str
    title: str
    status: Status
    position: int
    size: Size | None
    origin: Origin
    criteria: list[Criterion]
    open_questions: list[str]
    notes: str
    created_at: str
    updated_at: str


class Undo(BaseModel):
    action: str
    params: dict[str, Any]


def title(parts: StoryParts) -> str:
    phrase = parts.role_phrase[:1].upper() + parts.role_phrase[1:]
    return f"{phrase} soovin {parts.action}, et {parts.benefit.rstrip('.')}."


def _clean(items: list[str], limit: int = 500) -> list[str]:
    """Trimmed, non-empty lines; each kept within `limit` characters."""
    out = [" ".join(item.split()) for item in items]
    too_long = [item for item in out if len(item) > limit]
    if too_long:
        raise HTTPException(422, f"Each line must be at most {limit} characters")
    return [item for item in out if item]


# --- reading -------------------------------------------------------------

def stories(conn: sqlite3.Connection, project_id: int) -> list[Story]:
    rows = conn.execute("SELECT * FROM stories WHERE project_id = ? ORDER BY position, id",
                        (project_id,)).fetchall()
    criteria: dict[int, list[Criterion]] = {}
    for row in conn.execute(
            "SELECT c.* FROM criteria c JOIN stories s ON s.id = c.story_id "
            "WHERE s.project_id = ? ORDER BY c.position, c.id", (project_id,)):
        criteria.setdefault(row["story_id"], []).append(
            Criterion(id=row["id"], text=row["text"], origin=row["origin"]))
    result = []
    for row in rows:
        data = dict(row)
        data["open_questions"] = json.loads(data["open_questions"])
        parts = StoryParts(**{k: data[k] for k in StoryParts.model_fields})
        result.append(Story(**data, key=f"US-{data['number']}", title=title(parts),
                            criteria=criteria.get(row["id"], [])))
    return result


def get_story(conn: sqlite3.Connection, project_id: int, story_id: int) -> Story:
    for story in stories(conn, project_id):
        if story.id == story_id:
            return story
    raise HTTPException(404, "Story not found")


def snapshot(conn: sqlite3.Connection, project_id: int) -> list[dict]:
    """The backlog as the AI sees it: current state, including manual edits."""
    return [{"key": s.key, "role_name": s.role_name, "title": s.title, "status": s.status,
             "size": s.size, "criteria": [c.text for c in s.criteria],
             "open_questions": s.open_questions}
            for s in stories(conn, project_id)]


# --- undo ----------------------------------------------------------------

def _dump(conn: sqlite3.Connection, project_id: int) -> str:
    story_rows = [dict(r) for r in conn.execute(
        "SELECT * FROM stories WHERE project_id = ?", (project_id,))]
    criteria_rows = [dict(r) for r in conn.execute(
        "SELECT c.* FROM criteria c JOIN stories s ON s.id = c.story_id WHERE s.project_id = ?",
        (project_id,))]
    return json.dumps({"stories": story_rows, "criteria": criteria_rows}, ensure_ascii=False)


def record_undo(conn: sqlite3.Connection, project_id: int, action: str,
                before: str | None = None, **params: Any) -> None:
    """Snapshot the backlog before a change. Call inside the change's transaction,
    before changing anything, or pass `before` taken from `_dump` at that point."""
    conn.execute("INSERT INTO undo_log (project_id, action, params, snapshot, created_at) "
                 "VALUES (?, ?, ?, ?, ?)",
                 (project_id, action, json.dumps(params, ensure_ascii=False),
                  before if before is not None else _dump(conn, project_id), db.now()))
    conn.execute("DELETE FROM undo_log WHERE project_id = ? AND id NOT IN (SELECT id FROM undo_log "
                 "WHERE project_id = ? ORDER BY id DESC LIMIT ?)", (project_id, project_id, UNDO_DEPTH))


def last_undo(conn: sqlite3.Connection, project_id: int) -> Undo | None:
    row = conn.execute("SELECT action, params FROM undo_log WHERE project_id = ? "
                       "ORDER BY id DESC LIMIT 1", (project_id,)).fetchone()
    return Undo(action=row["action"], params=json.loads(row["params"])) if row else None


def _upsert(conn: sqlite3.Connection, table: str, rows: list[dict]) -> None:
    for row in rows:
        columns = list(row)
        updates = ", ".join(f"{c} = excluded.{c}" for c in columns if c != "id")
        conn.execute(f"INSERT INTO {table} ({', '.join(columns)}) VALUES "
                     f"({', '.join('?' * len(columns))}) ON CONFLICT(id) DO UPDATE SET {updates}",
                     [row[c] for c in columns])


def _not_in(ids: list[int]) -> str:
    """`AND id NOT IN (...)`, or nothing for an empty list: `NOT IN (NULL)` is never true."""
    return f"AND id NOT IN ({', '.join('?' * len(ids))})" if ids else ""


def undo(conn: sqlite3.Connection, project_id: int) -> Undo:
    """Put the backlog back as it was before the last recorded change.

    Rows are updated in place rather than deleted and re-inserted, so anything
    that refers to a surviving story (mockups, criteria) keeps its link.
    """
    row = conn.execute("SELECT * FROM undo_log WHERE project_id = ? ORDER BY id DESC LIMIT 1",
                       (project_id,)).fetchone()
    if row is None:
        raise HTTPException(409, "Nothing to undo")
    before = json.loads(row["snapshot"])
    with conn:
        story_ids = [s["id"] for s in before["stories"]]
        criterion_ids = [c["id"] for c in before["criteria"]]
        conn.execute("DELETE FROM criteria WHERE story_id IN (SELECT id FROM stories WHERE "
                     f"project_id = ?) {_not_in(criterion_ids)}", (project_id, *criterion_ids))
        conn.execute(f"DELETE FROM stories WHERE project_id = ? {_not_in(story_ids)}",
                     (project_id, *story_ids))
        # Numbers and positions are unique; park them out of the way first.
        conn.execute("UPDATE stories SET number = -id WHERE project_id = ?", (project_id,))
        _upsert(conn, "stories", before["stories"])
        _upsert(conn, "criteria", before["criteria"])
        conn.execute("DELETE FROM undo_log WHERE id = ?", (row["id"],))
        db.touch_project(conn, project_id)
    return Undo(action=row["action"], params=json.loads(row["params"]))


# --- changing ------------------------------------------------------------

def _next_number(conn: sqlite3.Connection, project_id: int) -> int:
    conn.execute("UPDATE projects SET story_seq = story_seq + 1 WHERE id = ?", (project_id,))
    return conn.execute("SELECT story_seq FROM projects WHERE id = ?", (project_id,)).fetchone()[0]


def _set_criteria(conn: sqlite3.Connection, story_id: int, texts: list[str], origin: Origin) -> None:
    """Replace a story's criteria, keeping rows (and their origin) whose text is unchanged."""
    existing = {row["text"]: row for row in conn.execute(
        "SELECT * FROM criteria WHERE story_id = ?", (story_id,))}
    conn.execute("DELETE FROM criteria WHERE story_id = ?", (story_id,))
    for position, text in enumerate(texts):
        old = existing.get(text)
        conn.execute("INSERT INTO criteria (id, story_id, text, position, origin, created_at) "
                     "VALUES (?, ?, ?, ?, ?, ?)",
                     (old["id"] if old else None, story_id, text, position,
                      old["origin"] if old else origin, old["created_at"] if old else db.now()))


def add_stories(conn: sqlite3.Connection, project_id: int, new: list[StoryParts],
                origin: Origin) -> list[Story]:
    """Append stories to the end of the backlog. The caller owns the transaction."""
    position = conn.execute("SELECT COALESCE(MAX(position), -1) FROM stories WHERE project_id = ?",
                            (project_id,)).fetchone()[0]
    stamp = db.now()
    ids = []
    for parts in new:
        position += 1
        full = parts if isinstance(parts, StoryIn) else StoryIn(**parts.model_dump())
        cur = conn.execute(
            "INSERT INTO stories (project_id, number, role_name, role_phrase, action, benefit, "
            "status, position, size, origin, open_questions, notes, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (project_id, _next_number(conn, project_id), full.role_name, full.role_phrase,
             full.action, full.benefit, full.status, position, full.size, origin,
             json.dumps(_clean(full.open_questions), ensure_ascii=False), full.notes, stamp, stamp))
        _set_criteria(conn, cur.lastrowid, _clean(full.criteria), origin)
        ids.append(cur.lastrowid)
    db.touch_project(conn, project_id)
    return [s for s in stories(conn, project_id) if s.id in ids]


def create_story(conn: sqlite3.Connection, project_id: int, data: StoryIn) -> Story:
    with conn:
        before = _dump(conn, project_id)
        story = add_stories(conn, project_id, [data], origin="manual")[0]
        record_undo(conn, project_id, "story_added", before=before, key=story.key)
    return story


def update_story(conn: sqlite3.Connection, project_id: int, story_id: int,
                 patch: StoryPatch) -> Story:
    story = get_story(conn, project_id, story_id)
    fields = patch.model_dump(exclude_none=True, exclude={"criteria", "open_questions", "clear_size"})
    if patch.clear_size:
        fields["size"] = None
    if patch.open_questions is not None:
        fields["open_questions"] = json.dumps(_clean(patch.open_questions), ensure_ascii=False)
    with conn:
        record_undo(conn, project_id, "story_edited", key=story.key)
        if fields:
            fields["updated_at"] = db.now()
            assignments = ", ".join(f"{name} = ?" for name in fields)
            conn.execute(f"UPDATE stories SET {assignments} WHERE id = ?", (*fields.values(), story_id))
        if patch.criteria is not None:
            _set_criteria(conn, story_id, _clean(patch.criteria), "manual")
            conn.execute("UPDATE stories SET updated_at = ? WHERE id = ?", (db.now(), story_id))
        db.touch_project(conn, project_id)
    return get_story(conn, project_id, story_id)


def delete_story(conn: sqlite3.Connection, project_id: int, story_id: int) -> None:
    story = get_story(conn, project_id, story_id)
    with conn:
        record_undo(conn, project_id, "story_deleted", key=story.key)
        conn.execute("DELETE FROM stories WHERE id = ?", (story_id,))
        _compact(conn, project_id)
        db.touch_project(conn, project_id)


def reorder(conn: sqlite3.Connection, project_id: int, ids: list[int]) -> None:
    current = [s.id for s in stories(conn, project_id)]
    if sorted(ids) != sorted(current) or len(set(ids)) != len(ids):
        raise HTTPException(422, "The order must list every story of the project exactly once")
    if ids == current:
        return
    with conn:
        record_undo(conn, project_id, "stories_reordered")
        conn.executemany("UPDATE stories SET position = ? WHERE id = ?",
                         [(position, story_id) for position, story_id in enumerate(ids)])
        db.touch_project(conn, project_id)


def _compact(conn: sqlite3.Connection, project_id: int) -> None:
    ids = [row[0] for row in conn.execute(
        "SELECT id FROM stories WHERE project_id = ? ORDER BY position, id", (project_id,))]
    conn.executemany("UPDATE stories SET position = ? WHERE id = ?",
                     [(position, story_id) for position, story_id in enumerate(ids)])


# --- API -----------------------------------------------------------------

router = APIRouter(prefix="/api/projects/{project_id}", tags=["backlog"])


def _project(conn: sqlite3.Connection, project_id: int) -> None:
    if conn.execute("SELECT 1 FROM projects WHERE id = ?", (project_id,)).fetchone() is None:
        raise HTTPException(404, "Project not found")


@router.post("/stories", response_model=Story, status_code=201)
def post_story(project_id: int, data: StoryIn, conn: sqlite3.Connection = Depends(db.get_db)):
    _project(conn, project_id)
    return create_story(conn, project_id, data)


@router.patch("/stories/{story_id}", response_model=Story)
def patch_story(project_id: int, story_id: int, patch: StoryPatch,
                conn: sqlite3.Connection = Depends(db.get_db)):
    return update_story(conn, project_id, story_id, patch)


@router.delete("/stories/{story_id}", status_code=204)
def remove_story(project_id: int, story_id: int, conn: sqlite3.Connection = Depends(db.get_db)):
    delete_story(conn, project_id, story_id)


@router.put("/stories/order", status_code=204)
def put_order(project_id: int, order: Order, conn: sqlite3.Connection = Depends(db.get_db)):
    _project(conn, project_id)
    reorder(conn, project_id, order.ids)


@router.post("/undo", response_model=Undo)
def post_undo(project_id: int, conn: sqlite3.Connection = Depends(db.get_db)):
    _project(conn, project_id)
    return undo(conn, project_id)
