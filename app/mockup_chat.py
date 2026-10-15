"""AI chat beside a mockup: an instruction changes the mockup and keeps the stories in sync.

The chat is its own AI task, not a conversation turn. The model gets the mockup's
current tree, the stories it is linked to with their criteria, and the user's
instruction, and returns the full new tree plus the full criteria list of every
story whose criteria must follow the change. The user issued the instruction, so
the change is applied at once; it is one undoable step (backlog undo), made in a
single transaction: new mockup version, criteria, readiness check, chat messages.

A request carries the version it was made on. If the mockup moved on meanwhile
(a hand edit, another instruction), nothing is applied.
"""
from __future__ import annotations

import json
import sqlite3
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field

from . import backlog, db, mockups, testability
from .ai import AIError, Task, run_task
from .conversation import ProposedCriterion
from .projects import get as get_project

ATTEMPTS = 3
UNDO_ACTION = "mockup_ai_edited"


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class StoryCriteria(_Strict):
    story_key: str = Field(min_length=1, max_length=20)
    criteria: list[ProposedCriterion] = Field(min_length=1, max_length=15)  # the story's FULL list


class MockupEdit(_Strict):
    summary: str = Field(min_length=1, max_length=500)
    mockup: mockups.Tree
    criteria: list[StoryCriteria] = Field(max_length=10)


INSTRUCTIONS = """\
You change ONE wireframe mockup on the instruction of a project manager who is in a meeting with a
client. INPUT.mockup.tree is the mockup as it is now; INPUT.instruction is what to change;
INPUT.stories are the stories the mockup belongs to, with their acceptance criteria.

- Return `mockup`: the FULL tree after the change, starting from INPUT.mockup.tree. Keep the ids of
  everything that stays, give new components short unique ids in lowercase with hyphens, and do
  not change what the instruction does not mention. Only header, card, grid, price_card, form,
  footer, section and row have children; set every unused field to null. A grid may only hold card,
  price_card and image children (equal cards), so to place content side by side (for example a photo
  to the right of buttons) use a row with 2 to 4 children of any type, such as a section of buttons
  and an image.
- Return `criteria`: for every story in INPUT.stories whose criteria must follow the change (a
  criterion about a component you removed, renamed or replaced, or a new thing the story should
  check), an entry with story_key and the story's FULL criteria list after the change. Keep the
  unchanged criteria word for word. Each criterion is ONE simple condition that can be checked with
  yes or no, with no evaluative words (user-friendly, fast, simple, convenient, intuitive, clear, or
  their Estonian equivalents) and never two conditions joined with "and"/"ja"/"ning"; its
  component_id is the id of the component in your new tree that shows it, or null when the view
  cannot show it. A criterion must never point at a component that is not in the new tree. Leave
  out stories that need no change; `criteria` may be empty.
- If the instruction asks for nothing the mockup can do, or the mockup already is as asked, return
  the tree unchanged and say so in `summary`.
- `summary`: one or two sentences saying what you changed. Write it, every component text and every
  criterion in the language given by INPUT.language (et = Estonian, en = English)."""


# --- payload and checks --------------------------------------------------

def build_payload(language: str, mockup: mockups.Mockup, stories: list[backlog.Story],
                  instruction: str) -> dict[str, Any]:
    return {
        "language": language,
        "instruction": instruction,
        "mockup": {"title": mockup.title, "tree": mockup.tree.model_dump()},
        "stories": [{"key": s.key, "title": s.title,
                     "criteria": [{"text": c.text, "component_id": c.component_id} for c in s.criteria]}
                    for s in stories],
    }


def effective_criteria(edit: MockupEdit, stories: list[backlog.Story]) -> dict[str, list[tuple[str, str | None]]]:
    """Each story's criteria after the edit: its own answer entry, else what it has now."""
    given = {entry.story_key: [(c.text, c.component_id) for c in entry.criteria] for entry in edit.criteria}
    return {s.key: given.get(s.key, [(c.text, c.component_id) for c in s.criteria]) for s in stories}


def check_edit(edit: MockupEdit, stories: list[backlog.Story], before: mockups.Tree) -> str | None:
    """Soft rules on top of the shape. An unchanged tree changes nothing, so nothing is checked."""
    if edit.mockup == before:
        return None
    keys = [entry.story_key for entry in edit.criteria]
    strangers = sorted(set(keys) - {s.key for s in stories})
    if strangers:
        return f"criteria may only name stories from INPUT.stories; not {strangers}."
    if len(set(keys)) != len(keys):
        return "criteria names a story more than once; give each story one entry with its FULL list."
    ids, removed = mockups.component_ids(edit.mockup), mockups.component_ids(before)
    for key, criteria in effective_criteria(edit, stories).items():
        # A criterion that already pointed nowhere before this edit is not this edit's doing.
        dangling = sorted({cid for _, cid in criteria if cid and cid not in ids
                           and (cid in removed or key in keys)})
        if dangling:
            return (f"The criteria of {key} refer to components that are not in the new mockup: "
                    f"{dangling}. List {key} in `criteria` with a full list whose component_id values "
                    f"are ids from the new tree (or null).")
    untestable = []
    for entry in edit.criteria:
        for criterion in entry.criteria:
            if issues := testability.check(criterion.text):
                untestable.append(testability.describe(criterion.text, issues))
    if untestable:
        return ("Some criteria cannot be answered with yes or no: " + " | ".join(untestable)
                + ". Rewrite each as one simple, checkable condition.")
    return None


# --- the mock answer -----------------------------------------------------

def mock_edit(payload: dict[str, Any]) -> dict[str, Any]:
    """Add a note under the first heading, and one criterion per story that checks it."""
    tree = payload["mockup"]["tree"]
    components = [dict(c) for c in tree["components"]]
    taken = mockups.component_ids(mockups.Tree(**tree))
    number = 1
    while f"ai-note-{number}" in taken:
        number += 1
    note_id = f"ai-note-{number}"
    at = next((i + 1 for i, c in enumerate(components) if c["type"] == "heading"), len(components))
    components.insert(at, {"id": note_id, "type": "note", "text": payload["instruction"][:80]})
    criteria = [{"story_key": s["key"],
                 "criteria": [*s["criteria"], {"text": "Vaates on AI lisatud märge.", "component_id": note_id}]}
                for s in payload["stories"]]
    return {"summary": "Lisasin vaatesse märkuse ja seotud lugudele ühe kriteeriumi.",
            "mockup": {"title": tree["title"], "components": components}, "criteria": criteria}


EDIT = Task(name="mockup_edit", instructions=INSTRUCTIONS, response=MockupEdit, mock=mock_edit)


# --- messages ------------------------------------------------------------

class ChatMessage(BaseModel):
    id: int
    role: str
    text: str
    version: int | None = None
    story_keys: list[str] = []
    undone: bool = False
    created_at: str


class Chat(BaseModel):
    messages: list[ChatMessage]
    can_undo: bool


class ChatResult(Chat):
    mockup: mockups.Mockup


class ChatIn(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    instruction: str = Field(min_length=1, max_length=1000)
    base_version: int = Field(ge=1)


def messages(conn: sqlite3.Connection, mockup_id: int) -> list[ChatMessage]:
    return [ChatMessage(id=r["id"], role=r["role"], text=r["text"], version=r["version"],
                        story_keys=json.loads(r["story_keys"]), undone=bool(r["undone"]),
                        created_at=r["created_at"])
            for r in conn.execute("SELECT * FROM mockup_messages WHERE mockup_id = ? ORDER BY id", (mockup_id,))]


def can_undo(conn: sqlite3.Connection, project_id: int, mockup_id: int) -> bool:
    last = backlog.last_undo(conn, project_id)
    return bool(last and last.action == UNDO_ACTION and last.params.get("mockup_id") == mockup_id)


def chat(conn: sqlite3.Connection, project_id: int, mockup_id: int) -> Chat:
    mockups.get_mockup(conn, project_id, mockup_id)
    return Chat(messages=messages(conn, mockup_id), can_undo=can_undo(conn, project_id, mockup_id))


def _stale() -> HTTPException:
    return HTTPException(409, {"code": "stale_version",
                               "message": "The mockup changed meanwhile. Reopen it and give the instruction again."})


def _linked(conn: sqlite3.Connection, project_id: int, mockup: mockups.Mockup) -> list[backlog.Story]:
    return [s for s in backlog.stories(conn, project_id) if mockup.id in s.mockup_ids]


async def instruct(conn: sqlite3.Connection, project_id: int, mockup_id: int,
                   data: ChatIn) -> ChatResult:
    mockup = mockups.get_mockup(conn, project_id, mockup_id)
    if mockup.version != data.base_version:
        raise _stale()
    stories = _linked(conn, project_id, mockup)
    payload = build_payload(get_project(conn, project_id).language, mockup, stories, data.instruction)
    edit = await run_task(EDIT, payload, check=lambda answer: check_edit(answer, stories, mockup.tree), attempts=ATTEMPTS)
    problem = check_edit(edit, stories, mockup.tree)  # a soft problem the model kept after its last attempt
    if problem:
        raise AIError("ai_invalid_answer", f"The AI answer for 'mockup_edit' was not usable: {problem}")

    with conn:
        current = mockups.get_mockup(conn, project_id, mockup_id)
        if current.version != data.base_version:
            raise _stale()
        stamp = db.now()
        conn.execute("INSERT INTO mockup_messages (mockup_id, role, text, created_at) VALUES (?, 'user', ?, ?)",
                     (mockup_id, data.instruction, stamp))
        changed = edit.mockup != mockup.tree
        version, touched = None, []
        if changed:
            backlog.record_undo(conn, project_id, UNDO_ACTION, mockup_id=mockup_id, title=mockup.title)
            version = mockups.add_version(conn, mockup_id, edit.mockup, note="ai")
            by_key = {s.key: s for s in stories}
            for entry in edit.criteria:
                story = by_key[entry.story_key]
                backlog.replace_criteria(conn, story.id, [(c.text, "ai", c.component_id) for c in entry.criteria])
                touched.append(story.key)
            for story in stories:
                backlog.check_status(conn, project_id, story.id, None)
            db.touch_project(conn, project_id)
        conn.execute("INSERT INTO mockup_messages (mockup_id, role, text, version, story_keys, created_at) "
                     "VALUES (?, 'assistant', ?, ?, ?, ?)",
                     (mockup_id, edit.summary, version, json.dumps(touched), db.now()))
    state = chat(conn, project_id, mockup_id)
    return ChatResult(messages=state.messages, can_undo=state.can_undo,
                      mockup=mockups.get_mockup(conn, project_id, mockup_id))


# --- API -----------------------------------------------------------------

router = APIRouter(prefix="/api/projects/{project_id}/mockups/{mockup_id}/chat", tags=["mockup chat"])


@router.get("", response_model=Chat)
def read_chat(project_id: int, mockup_id: int, conn: sqlite3.Connection = Depends(db.get_db)):
    return chat(conn, project_id, mockup_id)


@router.post("", response_model=ChatResult)
async def post_chat(project_id: int, mockup_id: int, data: ChatIn,
                    conn: sqlite3.Connection = Depends(db.get_db)):
    return await instruct(conn, project_id, mockup_id, data)
