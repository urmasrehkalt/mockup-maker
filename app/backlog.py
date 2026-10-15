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
import re
import sqlite3
from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field

from . import db, testability

Status = Literal["idea", "needs_clarification", "reviewed", "ready"]
Size = Literal["S", "M", "L"]
Origin = Literal["ai", "manual"]

UNDO_DEPTH = 20
MIN_CRITERIA = 3
MissingCode = Literal["connextra", "criteria_count", "criteria_testable", "mockup", "open_questions"]


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
    needs_view: bool = True
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
    needs_view: bool | None = None
    criteria: list[str] | None = Field(default=None, max_length=30)
    open_questions: list[str] | None = Field(default=None, max_length=20)
    notes: str | None = Field(default=None, max_length=2000)


class Order(_Input):
    ids: list[int]
    mvp_count: int | None = Field(default=None, ge=0)  # stories above the MVP line
    keep_mvp: bool = True  # False together with mvp_count=None removes the line


class Wording(_Input):
    role_name: str | None = Field(default=None, min_length=1, max_length=60)
    role_phrase: str = Field(min_length=1, max_length=80)
    action: str = Field(min_length=1, max_length=300)
    benefit: str = Field(min_length=1, max_length=300)


class SplitPart(Wording):
    criterion_ids: list[int] = Field(default_factory=list, max_length=30)
    new_criteria: list[str] = Field(default_factory=list, max_length=15)


class SplitIn(_Input):
    parts: list[SplitPart] = Field(min_length=2, max_length=5)
    link_mockups: bool = True
    dry_run: bool = False


class MergeIn(_Input):
    keep_id: int
    remove_id: int
    wording: Wording | None = None
    criteria: list[str] | None = Field(default=None, max_length=30)  # the final list, if edited
    dry_run: bool = False


class MergeResult(BaseModel):
    story: "Story"
    removed_key: str
    dropped_duplicates: list[str]


class Criterion(BaseModel):
    id: int
    text: str
    origin: Origin
    component_id: str | None = None
    issues: list[testability.Issue] = []


class Missing(BaseModel):
    """One unmet Definition of Ready condition."""
    code: MissingCode
    count: int | None = None


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
    mockup_ids: list[int]
    needs_view: bool
    in_mvp: bool = False
    tracker_id: int | None = None
    readiness: list[Missing] = []
    open_questions: list[str]
    notes: str
    created_at: str
    updated_at: str


MergeResult.model_rebuild()


class Undo(BaseModel):
    action: str
    params: dict[str, Any]


def title(parts: StoryParts, language: str = "et") -> str:
    """The Connextra sentence in the project's language.

    Estonian: "<Rollina> soovin <tegevus>, et <kasu>." (role_phrase in the essive).
    English: "As <a role>, I want to <action>, so that <benefit>." (role_phrase with its article).
    """
    benefit = parts.benefit.rstrip(".")
    if language == "en":
        phrase = re.sub(r"^as\s+", "", parts.role_phrase, flags=re.IGNORECASE)
        action = re.sub(r"^to\s+", "", parts.action, flags=re.IGNORECASE)
        return f"As {phrase}, I want to {action}, so that {benefit}."
    phrase = parts.role_phrase[:1].upper() + parts.role_phrase[1:]
    return f"{phrase} soovin {parts.action}, et {benefit}."


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
    project = conn.execute("SELECT mvp_count, language FROM projects WHERE id = ?", (project_id,)).fetchone()
    mvp_count = project["mvp_count"] if project else None
    language = project["language"] if project else "et"
    criteria: dict[int, list[Criterion]] = {}
    for row in conn.execute(
            "SELECT c.* FROM criteria c JOIN stories s ON s.id = c.story_id "
            "WHERE s.project_id = ? ORDER BY c.position, c.id", (project_id,)):
        criteria.setdefault(row["story_id"], []).append(
            Criterion(id=row["id"], text=row["text"], origin=row["origin"],
                      component_id=row["component_id"], issues=testability.check(row["text"])))
    links: dict[int, list[int]] = {}
    for row in conn.execute(
            "SELECT l.story_id, l.mockup_id FROM story_mockups l JOIN stories s ON s.id = l.story_id "
            "WHERE s.project_id = ? ORDER BY l.mockup_id", (project_id,)):
        links.setdefault(row["story_id"], []).append(row["mockup_id"])
    tracked = {row["story_id"]: row["tracker_story_id"] for row in conn.execute(
        "SELECT t.story_id, t.tracker_story_id FROM tracker_links t JOIN stories s ON s.id = t.story_id "
        "WHERE s.project_id = ?", (project_id,))}
    result = []
    for index, row in enumerate(rows):
        data = dict(row)
        data["in_mvp"] = mvp_count is not None and index < mvp_count
        data["tracker_id"] = tracked.get(row["id"])
        data["open_questions"] = json.loads(data["open_questions"])
        data["needs_view"] = bool(data["needs_view"])
        parts = StoryParts(**{k: data[k] for k in StoryParts.model_fields})
        story = Story(**data, key=f"US-{data['number']}", title=title(parts, language),
                      criteria=criteria.get(row["id"], []), mockup_ids=links.get(row["id"], []))
        story.readiness = readiness(story)
        result.append(story)
    return result


# --- Definition of Ready ---------------------------------------------------

ACTION_OPENERS = ("soovin ", "tahan ", "i want ", "want to ", "i would like ")
BENEFIT_OPENERS = ("et ", "selleks et ", "so that ", "in order to ")


def connextra_ok(parts: StoryParts) -> bool:
    """The parts form "<role> soovin <action>, et <benefit>." without doubled or missing pieces
    (the usual slips when a whole sentence is typed into one field)."""
    action, benefit = parts.action.lower(), parts.benefit.lower()
    return (len(parts.role_phrase) >= 2 and len(action) >= 3 and len(benefit) >= 3
            and "soovin" not in parts.role_phrase.lower() and "i want" not in parts.role_phrase.lower()
            and not action.startswith(ACTION_OPENERS) and not benefit.startswith(BENEFIT_OPENERS)
            and ", et " not in action and "so that" not in action)


def readiness(story: Story) -> list[Missing]:
    """What keeps the story from "Ready for development"; empty when it is ready."""
    missing: list[Missing] = []
    if not connextra_ok(story):
        missing.append(Missing(code="connextra"))
    if len(story.criteria) < MIN_CRITERIA:
        missing.append(Missing(code="criteria_count", count=len(story.criteria)))
    untestable = sum(1 for c in story.criteria if c.issues)
    if untestable:
        missing.append(Missing(code="criteria_testable", count=untestable))
    if story.needs_view and not story.mockup_ids:
        missing.append(Missing(code="mockup"))
    if story.open_questions:
        missing.append(Missing(code="open_questions", count=len(story.open_questions)))
    return missing


def check_status(conn: sqlite3.Connection, project_id: int, story_id: int,
                 requested: Status | None) -> None:
    """Enforce the Definition of Ready after a change, inside its transaction.

    Asking for "ready" when something is missing fails (and rolls the change back)
    with the list of what is missing. "Needs clarification" needs an open question.
    A story that was ready and no longer is drops back: to "needs clarification"
    when it has open questions, otherwise to "reviewed".
    """
    story = get_story(conn, project_id, story_id)
    if requested == "ready" and story.readiness:
        raise HTTPException(422, {"code": "not_ready", "message": "The story is not ready for development",
                                  "missing": [m.model_dump() for m in story.readiness]})
    if requested == "needs_clarification" and not story.open_questions:
        raise HTTPException(422, {"code": "needs_question",
                                  "message": "Add the open question that needs clarifying"})
    if requested is None and story.status == "ready" and story.readiness:
        fallback = "needs_clarification" if story.open_questions else "reviewed"
        conn.execute("UPDATE stories SET status = ? WHERE id = ?", (fallback, story_id))



def get_story(conn: sqlite3.Connection, project_id: int, story_id: int) -> Story:
    for story in stories(conn, project_id):
        if story.id == story_id:
            return story
    raise HTTPException(404, "Story not found")


def snapshot(conn: sqlite3.Connection, project_id: int) -> list[dict]:
    """The backlog as the AI sees it: current state, including manual edits."""
    return [{"key": s.key, "role_name": s.role_name, "title": s.title, "status": s.status,
             "size": s.size, "criteria": [c.text for c in s.criteria],
             "has_mockup": bool(s.mockup_ids), "needs_view": s.needs_view,
             "missing_for_ready": [m.code for m in s.readiness], "in_mvp": s.in_mvp,
             "open_questions": s.open_questions}
            for s in stories(conn, project_id)]


# --- undo ----------------------------------------------------------------

def _dump(conn: sqlite3.Connection, project_id: int) -> str:
    story_rows = [dict(r) for r in conn.execute(
        "SELECT * FROM stories WHERE project_id = ?", (project_id,))]
    criteria_rows = [dict(r) for r in conn.execute(
        "SELECT c.* FROM criteria c JOIN stories s ON s.id = c.story_id WHERE s.project_id = ?",
        (project_id,))]
    link_rows = [dict(r) for r in conn.execute(
        "SELECT l.* FROM story_mockups l JOIN stories s ON s.id = l.story_id WHERE s.project_id = ?",
        (project_id,))]
    versions = {str(r["mockup_id"]): r["latest"] for r in conn.execute(
        "SELECT v.mockup_id, MAX(v.number) AS latest FROM mockup_versions v JOIN mockups m "
        "ON m.id = v.mockup_id WHERE m.project_id = ? GROUP BY v.mockup_id", (project_id,))}
    newest_mockup = conn.execute("SELECT COALESCE(MAX(id), 0) FROM mockups WHERE project_id = ?",
                                 (project_id,)).fetchone()[0]
    mvp_count = conn.execute("SELECT mvp_count FROM projects WHERE id = ?", (project_id,)).fetchone()[0]
    tracker_rows = [dict(r) for r in conn.execute(
        "SELECT t.* FROM tracker_links t JOIN stories s ON s.id = t.story_id WHERE s.project_id = ?",
        (project_id,))]
    return json.dumps({"stories": story_rows, "criteria": criteria_rows, "links": link_rows,
                       "mockup_versions": versions, "newest_mockup": newest_mockup,
                       "mvp_count": mvp_count, "tracker_links": tracker_rows}, ensure_ascii=False)


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
        conn.execute("DELETE FROM story_mockups WHERE story_id IN "
                     "(SELECT id FROM stories WHERE project_id = ?)", (project_id,))
        _restore_mockups(conn, project_id, before)
        for tracked in before.get("tracker_links", []):
            conn.execute("INSERT OR REPLACE INTO tracker_links (story_id, tracker_story_id, mockup_hash, "
                         "pushed_at) VALUES (?, ?, ?, ?)", (tracked["story_id"], tracked["tracker_story_id"],
                                                           tracked["mockup_hash"], tracked["pushed_at"]))
        if "mvp_count" in before:
            conn.execute("UPDATE projects SET mvp_count = ? WHERE id = ?", (before["mvp_count"], project_id))
        conn.executemany("INSERT OR IGNORE INTO story_mockups (story_id, mockup_id) "
                         "SELECT ?, id FROM mockups WHERE id = ?",
                         [(link["story_id"], link["mockup_id"]) for link in before.get("links", [])])
        conn.execute("DELETE FROM undo_log WHERE id = ?", (row["id"],))
        db.touch_project(conn, project_id)
    return Undo(action=row["action"], params=json.loads(row["params"]))


# --- changing ------------------------------------------------------------

def _restore_mockups(conn: sqlite3.Connection, project_id: int, before: dict) -> None:
    """Drop mockups and mockup versions created after the snapshot was taken."""
    if "newest_mockup" not in before:
        return  # a snapshot from before mockups were covered
    conn.execute("DELETE FROM mockups WHERE project_id = ? AND id > ?", (project_id, before["newest_mockup"]))
    for mockup_id, latest in before["mockup_versions"].items():
        conn.execute("DELETE FROM mockup_versions WHERE mockup_id = ? AND number > ?", (int(mockup_id), latest))
        conn.execute("UPDATE mockup_messages SET undone = 1 WHERE mockup_id = ? AND version > ?",
                     (int(mockup_id), latest))
        title = conn.execute("SELECT tree FROM mockup_versions WHERE mockup_id = ? AND number = ?",
                             (int(mockup_id), latest)).fetchone()
        if title:
            conn.execute("UPDATE mockups SET title = ? WHERE id = ?",
                         (json.loads(title["tree"])["title"], int(mockup_id)))


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
        conn.execute("INSERT INTO criteria (id, story_id, text, position, origin, created_at, "
                     "component_id) VALUES (?, ?, ?, ?, ?, ?, ?)",
                     (old["id"] if old else None, story_id, text, position,
                      old["origin"] if old else origin, old["created_at"] if old else db.now(),
                      old["component_id"] if old else None))


def replace_criteria(conn: sqlite3.Connection, story_id: int,
                     items: list[tuple[str, Origin, str | None]]) -> None:
    """Make (text, origin, component_id) the story's criteria. A criterion whose text is
    unchanged keeps its row, origin and date; the rest are new rows."""
    existing = {row["text"]: row for row in conn.execute(
        "SELECT * FROM criteria WHERE story_id = ?", (story_id,))}
    conn.execute("DELETE FROM criteria WHERE story_id = ?", (story_id,))
    for position, (text, origin, component_id) in enumerate(items):
        old = existing.get(text)
        conn.execute("INSERT INTO criteria (id, story_id, text, position, origin, created_at, "
                     "component_id) VALUES (?, ?, ?, ?, ?, ?, ?)",
                     (old["id"] if old else None, story_id, text, position,
                      old["origin"] if old else origin, old["created_at"] if old else db.now(),
                      component_id))
    conn.execute("UPDATE stories SET updated_at = ? WHERE id = ?", (db.now(), story_id))


def append_criteria(conn: sqlite3.Connection, story_id: int,
                    new: list[tuple[str, Origin, str | None]]) -> None:
    """Add (text, origin, component_id) criteria after the story's existing ones."""
    position = conn.execute("SELECT COALESCE(MAX(position), -1) FROM criteria WHERE story_id = ?",
                            (story_id,)).fetchone()[0]
    stamp = db.now()
    for text, origin, component_id in new:
        position += 1
        conn.execute("INSERT INTO criteria (story_id, text, position, origin, created_at, component_id) "
                     "VALUES (?, ?, ?, ?, ?, ?)", (story_id, text, position, origin, stamp, component_id))
    conn.execute("UPDATE stories SET updated_at = ? WHERE id = ?", (stamp, story_id))


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
            "status, position, size, origin, open_questions, notes, created_at, updated_at, needs_view) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (project_id, _next_number(conn, project_id), full.role_name, full.role_phrase,
             full.action, full.benefit, full.status, position, full.size, origin,
             json.dumps(_clean(full.open_questions), ensure_ascii=False), full.notes, stamp, stamp,
             int(full.needs_view)))
        _set_criteria(conn, cur.lastrowid, _clean(full.criteria), origin)
        ids.append(cur.lastrowid)
    db.touch_project(conn, project_id)
    return [s for s in stories(conn, project_id) if s.id in ids]


def create_story(conn: sqlite3.Connection, project_id: int, data: StoryIn) -> Story:
    with conn:
        before = _dump(conn, project_id)
        story = add_stories(conn, project_id, [data], origin="manual")[0]
        check_status(conn, project_id, story.id, data.status if data.status != "idea" else None)
        record_undo(conn, project_id, "story_added", before=before, key=story.key)
    return get_story(conn, project_id, story.id)


def update_story(conn: sqlite3.Connection, project_id: int, story_id: int,
                 patch: StoryPatch) -> Story:
    story = get_story(conn, project_id, story_id)
    fields = patch.model_dump(exclude_none=True, exclude={"criteria", "open_questions", "clear_size"})
    if patch.clear_size:
        fields["size"] = None
    if "needs_view" in fields:
        fields["needs_view"] = int(fields["needs_view"])
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
        check_status(conn, project_id, story_id, patch.status)
        db.touch_project(conn, project_id)
    return get_story(conn, project_id, story_id)


def delete_story(conn: sqlite3.Connection, project_id: int, story_id: int) -> None:
    story = get_story(conn, project_id, story_id)
    with conn:
        record_undo(conn, project_id, "story_deleted", key=story.key)
        _remove(conn, project_id, story)
        db.touch_project(conn, project_id)


def _remove(conn: sqlite3.Connection, project_id: int, story: Story) -> None:
    """Delete a story; a story above the MVP line takes the line up with it."""
    if story.in_mvp:
        conn.execute("UPDATE projects SET mvp_count = mvp_count - 1 WHERE id = ?", (project_id,))
    conn.execute("DELETE FROM stories WHERE id = ?", (story.id,))
    _compact(conn, project_id)


def reorder(conn: sqlite3.Connection, project_id: int, order: Order) -> None:
    ids = order.ids
    current = [s.id for s in stories(conn, project_id)]
    if sorted(ids) != sorted(current) or len(set(ids)) != len(ids):
        raise HTTPException(422, "The order must list every story of the project exactly once")
    if order.mvp_count is not None and order.mvp_count > len(ids):
        raise HTTPException(422, "The MVP line cannot be below the last story")
    old_line = conn.execute("SELECT mvp_count FROM projects WHERE id = ?", (project_id,)).fetchone()[0]
    new_line = order.mvp_count if (order.mvp_count is not None or not order.keep_mvp) else old_line
    if ids == current and new_line == old_line:
        return
    with conn:
        record_undo(conn, project_id, "mvp_moved" if ids == current else "stories_reordered")
        conn.executemany("UPDATE stories SET position = ? WHERE id = ?",
                         [(position, story_id) for position, story_id in enumerate(ids)])
        conn.execute("UPDATE projects SET mvp_count = ? WHERE id = ?", (new_line, project_id))
        db.touch_project(conn, project_id)


# --- grooming: split and merge -------------------------------------------

class _DryRun(Exception):
    """Carries a preview out of a transaction, which then rolls back."""

    def __init__(self, result):
        super().__init__("dry run")
        self.result = result


def split(conn: sqlite3.Connection, project_id: int, story_id: int, data: SplitIn,
          origin: Origin = "manual") -> list[Story]:
    """Split a story into parts. Part 1 stays the original story (id, number, links);
    the others are inserted right after it. Each original criterion moves to the part
    that lists it; criteria no part lists are dropped."""
    story = get_story(conn, project_id, story_id)
    own = {c.id for c in story.criteria}
    listed = [cid for part in data.parts for cid in part.criterion_ids]
    if len(set(listed)) != len(listed) or not set(listed) <= own:
        raise HTTPException(422, "Each of the story's criteria can go to one part at most")
    try:
        with conn:
            record_undo(conn, project_id, "story_split", key=story.key, parts=len(data.parts))
            first, rest = data.parts[0], data.parts[1:]
            conn.execute("UPDATE stories SET role_name = ?, role_phrase = ?, action = ?, benefit = ?, "
                         "updated_at = ? WHERE id = ?",
                         (first.role_name or story.role_name, first.role_phrase, first.action,
                          first.benefit, db.now(), story.id))
            conn.execute("UPDATE stories SET position = position + ? WHERE project_id = ? AND position > ?",
                         (len(rest), project_id, story.position))
            if story.in_mvp:
                conn.execute("UPDATE projects SET mvp_count = mvp_count + ? WHERE id = ?",
                             (len(rest), project_id))
            ids = [story.id]
            for offset, part in enumerate(rest, start=1):
                stamp = db.now()
                cur = conn.execute(
                    "INSERT INTO stories (project_id, number, role_name, role_phrase, action, benefit, "
                    "status, position, size, origin, open_questions, notes, created_at, updated_at, "
                    "needs_view) VALUES (?, ?, ?, ?, ?, ?, 'idea', ?, NULL, ?, '[]', '', ?, ?, ?)",
                    (project_id, _next_number(conn, project_id), part.role_name or story.role_name,
                     part.role_phrase, part.action, part.benefit, story.position + offset, origin,
                     stamp, stamp, int(story.needs_view)))
                ids.append(cur.lastrowid)
                if data.link_mockups:
                    conn.executemany("INSERT INTO story_mockups (story_id, mockup_id) VALUES (?, ?)",
                                     [(cur.lastrowid, m) for m in story.mockup_ids])
            dropped = own - set(listed)
            conn.executemany("DELETE FROM criteria WHERE id = ?", [(cid,) for cid in dropped])
            for part, new_id in zip(data.parts, ids):
                for position, cid in enumerate(part.criterion_ids):
                    conn.execute("UPDATE criteria SET story_id = ?, position = ? WHERE id = ?",
                                 (new_id, position, cid))
                append_criteria(conn, new_id, [(t, origin, None) for t in _clean(part.new_criteria)])
            for new_id in ids:
                check_status(conn, project_id, new_id, None)
            db.touch_project(conn, project_id)
            result = [s for s in stories(conn, project_id) if s.id in ids]
            if data.dry_run:
                raise _DryRun(result)
    except _DryRun as preview:
        return preview.result
    return result


def _same(text: str) -> str:
    """Criteria that differ only in case, spacing or punctuation are the same criterion."""
    return " ".join(re.sub(r"[^\w\s]", " ", text.casefold()).split())


def merge(conn: sqlite3.Connection, project_id: int, data: MergeIn) -> MergeResult:
    """Merge `remove` into `keep`: criteria, open questions and mockups are united
    without duplicates; `remove` is deleted. Links and the chosen story move to `keep`."""
    if data.keep_id == data.remove_id:
        raise HTTPException(422, "Choose two different stories")
    keep = get_story(conn, project_id, data.keep_id)
    remove = get_story(conn, project_id, data.remove_id)
    seen: set[str] = set()
    merged: list[tuple[str, Origin, str | None]] = []
    dropped: list[str] = []
    for criterion in [*keep.criteria, *remove.criteria]:
        if _same(criterion.text) in seen:
            dropped.append(criterion.text)
            continue
        seen.add(_same(criterion.text))
        merged.append((criterion.text, criterion.origin, criterion.component_id))
    if data.criteria is not None:
        by_text = {text: (text, origin, component) for text, origin, component in merged}
        merged = [by_text.get(t, (t, "manual", None)) for t in _clean(data.criteria)]
    questions = list(dict.fromkeys([*keep.open_questions, *remove.open_questions]))
    try:
        with conn:
            record_undo(conn, project_id, "stories_merged", key=keep.key, removed=remove.key)
            if data.wording:
                w = data.wording
                conn.execute("UPDATE stories SET role_name = ?, role_phrase = ?, action = ?, benefit = ? "
                             "WHERE id = ?", (w.role_name or keep.role_name, w.role_phrase, w.action,
                                              w.benefit, keep.id))
            conn.execute("UPDATE stories SET open_questions = ?, updated_at = ? WHERE id = ?",
                         (json.dumps(questions, ensure_ascii=False), db.now(), keep.id))
            replace_criteria(conn, keep.id, merged)
            conn.execute("INSERT OR IGNORE INTO story_mockups (story_id, mockup_id) "
                         "SELECT ?, mockup_id FROM story_mockups WHERE story_id = ?", (keep.id, remove.id))
            conn.execute("UPDATE projects SET current_story_id = ? WHERE id = ? AND current_story_id = ?",
                         (keep.id, project_id, remove.id))
            _remove(conn, project_id, remove)
            check_status(conn, project_id, keep.id, None)
            db.touch_project(conn, project_id)
            result = MergeResult(story=get_story(conn, project_id, keep.id), removed_key=remove.key,
                                 dropped_duplicates=dropped if data.criteria is None else [])
            if data.dry_run:
                raise _DryRun(result)
    except _DryRun as preview:
        return preview.result
    return result


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
    reorder(conn, project_id, order)


@router.post("/stories/{story_id}/split", response_model=list[Story])
def post_split(project_id: int, story_id: int, data: SplitIn,
               conn: sqlite3.Connection = Depends(db.get_db)):
    return split(conn, project_id, story_id, data)


@router.post("/stories/merge", response_model=MergeResult)
def post_merge(project_id: int, data: MergeIn, conn: sqlite3.Connection = Depends(db.get_db)):
    _project(conn, project_id)
    return merge(conn, project_id, data)


@router.post("/undo", response_model=Undo)
def post_undo(project_id: int, conn: sqlite3.Connection = Depends(db.get_db)):
    _project(conn, project_id)
    return undo(conn, project_id)
