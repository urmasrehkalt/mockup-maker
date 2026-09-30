"""Mockups: wireframe views as a validated component tree, rendered by the app.

The AI never returns HTML. It returns a tree of components from a fixed
library; the server checks every node, and the browser draws it from text
nodes only, so nothing in a mockup can run code.

Every component uses one node shape. That keeps the structured-output schema
small enough for the model to follow reliably; the per-type rules (a table's
rows match its columns, only containers have children, ids are unique) are
checked here and fed back to the model on a retry.
"""
from __future__ import annotations

import json
import re
import sqlite3
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field, model_validator

from . import backlog, db
from .mockup_templates import TEMPLATES

ComponentType = Literal[
    "header", "nav", "heading", "text", "image", "card", "grid", "price_card", "list", "table",
    "form", "input", "button", "footer", "section", "note", "notice", "steps",
]
InputKind = Literal["text", "email", "password", "number", "date", "select", "checkbox", "textarea"]
Variant = Literal["primary", "secondary", "link", "info", "success", "warning", "error"] | InputKind

CONTAINERS = {"header", "card", "grid", "price_card", "form", "footer", "section"}
NEEDS_TEXT = {"heading", "text", "image", "button", "input", "price_card", "note", "notice"}
NEEDS_ITEMS = {"nav", "list", "table", "steps"}
GRID_CHILDREN = {"card", "price_card", "image"}
BUTTON_VARIANTS = {"primary", "secondary", "link"}
NOTICE_VARIANTS = {"info", "success", "warning", "error"}
INPUT_KINDS = set(InputKind.__args__)
ID_PATTERN = re.compile(r"^[a-z0-9][a-z0-9-]{0,39}$")
MAX_DEPTH = 6
MAX_NODES = 150


class Component(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    id: str = Field(min_length=1, max_length=40)
    type: ComponentType
    text: str | None = Field(default=None, max_length=300)
    secondary: str | None = Field(default=None, max_length=300)
    items: list[str] | None = Field(default=None, max_length=12)
    rows: list[list[str]] | None = Field(default=None, max_length=12)
    level: int | None = Field(default=None, ge=1, le=3)
    variant: Variant | None = None
    required: bool | None = None
    columns: int | None = Field(default=None, ge=1, le=4)
    children: list[Component] | None = Field(default=None, max_length=20)


class Tree(BaseModel):
    """A whole view: a title and its top-level components, top to bottom."""
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    title: str = Field(min_length=1, max_length=120)
    components: list[Component] = Field(min_length=1, max_length=30)

    @model_validator(mode="after")
    def _rules(self):
        problems = check_tree(self)
        if problems:
            raise ValueError("; ".join(problems[:10]))
        return self


def check_tree(tree: Tree) -> list[str]:
    """Per-type rules the schema cannot express. Returns readable problems."""
    problems: list[str] = []
    seen: set[str] = set()
    count = 0

    def visit(node: Component, depth: int, parent: str | None) -> None:
        nonlocal count
        count += 1
        where = f"component {node.id!r} ({node.type})"
        if not ID_PATTERN.match(node.id):
            problems.append(f"{where}: id must be lowercase letters, digits and hyphens")
        if node.id in seen:
            problems.append(f"{where}: id is used twice; ids must be unique")
        seen.add(node.id)
        if depth > MAX_DEPTH:
            problems.append(f"{where}: nested deeper than {MAX_DEPTH} levels")
        if node.children and node.type not in CONTAINERS:
            problems.append(f"{where}: only {sorted(CONTAINERS)} may have children")
        if node.type in NEEDS_TEXT and not node.text:
            problems.append(f"{where}: needs text")
        if node.type in NEEDS_ITEMS and not node.items:
            problems.append(f"{where}: needs items")
        if node.type == "grid" and not node.children:
            problems.append(f"{where}: needs children")
        if node.type == "form" and not node.children:
            problems.append(f"{where}: needs children (inputs and a button)")
        if parent == "grid" and node.type not in GRID_CHILDREN:
            problems.append(f"{where}: a grid may only hold {sorted(GRID_CHILDREN)}")
        if node.type == "input" and node.variant not in INPUT_KINDS:
            problems.append(f"{where}: variant must be one of {sorted(INPUT_KINDS)}")
        if node.type == "button" and node.variant not in (None, *BUTTON_VARIANTS):
            problems.append(f"{where}: variant must be one of {sorted(BUTTON_VARIANTS)}")
        if node.type == "notice" and node.variant not in (None, *NOTICE_VARIANTS):
            problems.append(f"{where}: variant must be one of {sorted(NOTICE_VARIANTS)}")
        if node.type == "table" and node.items:
            for i, row in enumerate(node.rows or []):
                if len(row) != len(node.items):
                    problems.append(f"{where}: row {i + 1} has {len(row)} cells for "
                                    f"{len(node.items)} columns")
        for child in node.children or []:
            visit(child, depth + 1, node.type)

    for component in tree.components:
        visit(component, 1, None)
    if count > MAX_NODES:
        problems.append(f"the mockup has {count} components; the maximum is {MAX_NODES}")
    return problems


def component_ids(tree: Tree) -> set[str]:
    ids: set[str] = set()

    def visit(node: Component) -> None:
        ids.add(node.id)
        for child in node.children or []:
            visit(child)
    for component in tree.components:
        visit(component)
    return ids


# --- annotations ---------------------------------------------------------

Point = tuple[float, float]


class Annotation(BaseModel):
    """A freehand mark on top of a mockup, in pixels of a 1024-wide view.

    Points are relative to the top-left corner of the `anchor` component (the one
    under the first point when it was drawn), so the mark stays with that component
    in both renderers (browser and PNG), whose layouts differ slightly. Without an
    anchor, or when the anchor is gone, points are relative to the whole view.
    """
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    id: str = Field(min_length=1, max_length=40)
    tool: Literal["rect", "arrow", "pen", "note"]
    anchor: str | None = Field(default=None, max_length=40)
    points: list[Point] = Field(min_length=1, max_length=500)
    text: str | None = Field(default=None, max_length=200)
    color: Literal["red", "blue", "green"] = "red"

    @model_validator(mode="after")
    def _shape(self):
        needed = {"rect": (2, 2), "arrow": (2, 2), "pen": (2, 500), "note": (1, 1)}[self.tool]
        if not needed[0] <= len(self.points) <= needed[1]:
            raise ValueError(f"a {self.tool} needs {needed[0]}" + ("" if needed[0] == needed[1] else f" to {needed[1]}") + " points")
        if self.tool == "note" and not self.text:
            raise ValueError("a note needs text")
        if any(not (-2000 <= c <= 20000) for point in self.points for c in point):
            raise ValueError("annotation points are out of range")
        return self


class AnnotationsIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    annotations: list[Annotation] = Field(max_length=200)

    @model_validator(mode="after")
    def _unique(self):
        ids = [a.id for a in self.annotations]
        if len(set(ids)) != len(ids):
            raise ValueError("annotation ids must be unique")
        return self


# --- models for the API --------------------------------------------------

class MockupIn(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    title: str | None = Field(default=None, max_length=120)
    template: str | None = None
    tree: Tree | None = None
    story_id: int | None = None

    @model_validator(mode="after")
    def _one_source(self):
        if (self.template is None) == (self.tree is None):
            raise ValueError("give either a template or a tree")
        return self


class Mockup(BaseModel):
    id: int
    title: str
    version: int
    tree: Tree
    annotations: list[Annotation] = []
    story_ids: list[int]
    updated_at: str


class TreeIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    tree: Tree


class Version(BaseModel):
    number: int
    note: str
    created_at: str
    tree: Tree
    annotations: list[Annotation] = []


class Template(BaseModel):
    key: str
    name: str
    tree: Tree


# --- storage -------------------------------------------------------------

def templates() -> list[Template]:
    return [Template(key=key, name=name, tree=Tree(**tree)) for key, (name, tree) in TEMPLATES.items()]


def mockups(conn: sqlite3.Connection, project_id: int) -> list[Mockup]:
    rows = conn.execute(
        "SELECT m.id, m.title, m.updated_at, v.number, v.tree, v.annotations FROM mockups m "
        "JOIN mockup_versions v ON v.mockup_id = m.id AND v.number = "
        "(SELECT MAX(number) FROM mockup_versions WHERE mockup_id = m.id) "
        "WHERE m.project_id = ? ORDER BY m.id", (project_id,)).fetchall()
    links: dict[int, list[int]] = {}
    for row in conn.execute("SELECT l.mockup_id, l.story_id FROM story_mockups l "
                            "JOIN mockups m ON m.id = l.mockup_id WHERE m.project_id = ? "
                            "ORDER BY l.story_id", (project_id,)):
        links.setdefault(row["mockup_id"], []).append(row["story_id"])
    return [Mockup(id=r["id"], title=r["title"], version=r["number"],
                   tree=Tree.model_validate_json(r["tree"]), annotations=_annotations(r["annotations"]),
                   story_ids=links.get(r["id"], []), updated_at=r["updated_at"]) for r in rows]


def _annotations(raw: str) -> list[Annotation]:
    return [Annotation(**a) for a in json.loads(raw or "[]")]


def get_mockup(conn: sqlite3.Connection, project_id: int, mockup_id: int) -> Mockup:
    for mockup in mockups(conn, project_id):
        if mockup.id == mockup_id:
            return mockup
    raise HTTPException(404, "Mockup not found")


def create(conn: sqlite3.Connection, project_id: int, tree: Tree, note: str,
           story_id: int | None = None) -> Mockup:
    """Store a new mockup as version 1, optionally linked to a story. Caller owns the transaction."""
    stamp = db.now()
    cur = conn.execute("INSERT INTO mockups (project_id, title, created_at, updated_at) "
                       "VALUES (?, ?, ?, ?)", (project_id, tree.title, stamp, stamp))
    add_version(conn, cur.lastrowid, tree, note)
    if story_id is not None:
        conn.execute("INSERT INTO story_mockups (story_id, mockup_id) VALUES (?, ?)",
                     (story_id, cur.lastrowid))
    db.touch_project(conn, project_id)
    return get_mockup(conn, project_id, cur.lastrowid)


def add_version(conn: sqlite3.Connection, mockup_id: int, tree: Tree, note: str,
                annotations: list[Annotation] | None = None) -> int:
    """Store a new version. Annotations default to the previous version's: a new
    layout from the AI or the editor should not throw away the user's notes."""
    latest = conn.execute("SELECT number, annotations FROM mockup_versions WHERE mockup_id = ? "
                          "ORDER BY number DESC LIMIT 1", (mockup_id,)).fetchone()
    number = (latest["number"] if latest else 0) + 1
    if annotations is None:
        marks = latest["annotations"] if latest else "[]"
    else:
        marks = json.dumps([a.model_dump() for a in annotations], ensure_ascii=False)
    stamp = db.now()
    conn.execute("INSERT INTO mockup_versions (mockup_id, number, tree, note, created_at, annotations) "
                 "VALUES (?, ?, ?, ?, ?, ?)", (mockup_id, number, tree.model_dump_json(), note, stamp, marks))
    conn.execute("UPDATE mockups SET title = ?, updated_at = ? WHERE id = ?",
                 (tree.title, stamp, mockup_id))
    return number


def update_for_story(conn: sqlite3.Connection, project_id: int, story_id: int, mockup_id: int | None,
                     tree: Tree, note: str) -> tuple[int, int]:
    """Give a story a new version of its mockup without touching any other story.

    If the mockup is also linked to other stories, the story gets its own copy
    (a new mockup) instead, so a refinement of one story never changes another's
    view. Returns (mockup id, version number). Caller owns the transaction.
    """
    if mockup_id is None:
        created = create(conn, project_id, tree, note=note, story_id=story_id)
        return created.id, created.version
    shared = conn.execute("SELECT COUNT(*) FROM story_mockups WHERE mockup_id = ? AND story_id != ?",
                          (mockup_id, story_id)).fetchone()[0]
    if shared:
        conn.execute("DELETE FROM story_mockups WHERE story_id = ? AND mockup_id = ?", (story_id, mockup_id))
        created = create(conn, project_id, tree, note=note, story_id=story_id)
        return created.id, created.version
    version = add_version(conn, mockup_id, tree, note)
    db.touch_project(conn, project_id)
    return mockup_id, version


def versions(conn: sqlite3.Connection, project_id: int, mockup_id: int) -> list[Version]:
    get_mockup(conn, project_id, mockup_id)
    rows = conn.execute("SELECT number, note, created_at, tree, annotations FROM mockup_versions "
                        "WHERE mockup_id = ? ORDER BY number", (mockup_id,)).fetchall()
    return [Version(number=r["number"], note=r["note"], created_at=r["created_at"],
                    tree=Tree.model_validate_json(r["tree"]), annotations=_annotations(r["annotations"]))
            for r in rows]


def restore(conn: sqlite3.Connection, project_id: int, mockup_id: int, number: int) -> Mockup:
    """Make an earlier version the newest one. History is never rewritten: the old
    version is copied forward as a new version, and the step can be undone."""
    old = next((v for v in versions(conn, project_id, mockup_id) if v.number == number), None)
    if old is None:
        raise HTTPException(404, "Version not found")
    mockup = get_mockup(conn, project_id, mockup_id)
    if number == mockup.version:
        raise HTTPException(409, "That version is already the newest")
    with conn:
        backlog.record_undo(conn, project_id, "mockup_restored", title=mockup.title, version=number)
        add_version(conn, mockup_id, old.tree, note=f"restore:{number}", annotations=old.annotations)
        db.touch_project(conn, project_id)
    return get_mockup(conn, project_id, mockup_id)


def save_edit(conn: sqlite3.Connection, project_id: int, mockup_id: int, tree: Tree) -> Mockup:
    """A hand-edited tree becomes the newest version (undoable like any other change)."""
    mockup = get_mockup(conn, project_id, mockup_id)
    if tree == mockup.tree:
        return mockup
    with conn:
        backlog.record_undo(conn, project_id, "mockup_edited", title=mockup.title)
        add_version(conn, mockup_id, tree, note="manual")
        db.touch_project(conn, project_id)
    return get_mockup(conn, project_id, mockup_id)


def annotate(conn: sqlite3.Connection, project_id: int, mockup_id: int, annotations: list[Annotation]) -> Mockup:
    """Save the annotation layer as a new version of the same view."""
    mockup = get_mockup(conn, project_id, mockup_id)
    if annotations == mockup.annotations:
        return mockup
    with conn:
        backlog.record_undo(conn, project_id, "mockup_annotated", title=mockup.title)
        add_version(conn, mockup_id, mockup.tree, note="annotations", annotations=annotations)
        db.touch_project(conn, project_id)
    return get_mockup(conn, project_id, mockup_id)


def link(conn: sqlite3.Connection, project_id: int, story_id: int, mockup_id: int) -> None:
    story = backlog.get_story(conn, project_id, story_id)
    get_mockup(conn, project_id, mockup_id)
    with conn:
        backlog.record_undo(conn, project_id, "mockup_linked", key=story.key)
        conn.execute("INSERT OR IGNORE INTO story_mockups (story_id, mockup_id) VALUES (?, ?)",
                     (story_id, mockup_id))
        db.touch_project(conn, project_id)


def unlink(conn: sqlite3.Connection, project_id: int, story_id: int, mockup_id: int) -> None:
    story = backlog.get_story(conn, project_id, story_id)
    with conn:
        backlog.record_undo(conn, project_id, "mockup_unlinked", key=story.key)
        conn.execute("DELETE FROM story_mockups WHERE story_id = ? AND mockup_id = ?",
                     (story_id, mockup_id))
        backlog.check_status(conn, project_id, story_id, None)
        db.touch_project(conn, project_id)


# --- API -----------------------------------------------------------------

router = APIRouter(tags=["mockups"])


@router.get("/api/mockup-templates", response_model=list[Template])
def list_templates():
    return templates()


@router.post("/api/projects/{project_id}/mockups", response_model=Mockup, status_code=201)
def post_mockup(project_id: int, data: MockupIn, conn: sqlite3.Connection = Depends(db.get_db)):
    if conn.execute("SELECT 1 FROM projects WHERE id = ?", (project_id,)).fetchone() is None:
        raise HTTPException(404, "Project not found")
    if data.template is not None:
        chosen = next((t for t in templates() if t.key == data.template), None)
        if chosen is None:
            raise HTTPException(422, f"Unknown template {data.template!r}")
        tree = chosen.tree
    else:
        tree = data.tree
    if data.title:
        tree = tree.model_copy(update={"title": data.title})
    story = backlog.get_story(conn, project_id, data.story_id) if data.story_id is not None else None
    with conn:
        if story:
            backlog.record_undo(conn, project_id, "mockup_linked", key=story.key)
        else:
            backlog.record_undo(conn, project_id, "mockup_created", title=tree.title)
        return create(conn, project_id, tree, note=f"template:{data.template}" if data.template else "manual",
                      story_id=story.id if story else None)


@router.get("/api/projects/{project_id}/mockups/{mockup_id}", response_model=Mockup)
def read_mockup(project_id: int, mockup_id: int, conn: sqlite3.Connection = Depends(db.get_db)):
    return get_mockup(conn, project_id, mockup_id)


@router.get("/api/projects/{project_id}/mockups/{mockup_id}/versions", response_model=list[Version])
def list_versions(project_id: int, mockup_id: int, conn: sqlite3.Connection = Depends(db.get_db)):
    return versions(conn, project_id, mockup_id)


@router.post("/api/projects/{project_id}/mockups/{mockup_id}/versions", response_model=Mockup)
def post_version(project_id: int, mockup_id: int, data: TreeIn,
                 conn: sqlite3.Connection = Depends(db.get_db)):
    return save_edit(conn, project_id, mockup_id, data.tree)


@router.put("/api/projects/{project_id}/mockups/{mockup_id}/annotations", response_model=Mockup)
def put_annotations(project_id: int, mockup_id: int, data: AnnotationsIn,
                    conn: sqlite3.Connection = Depends(db.get_db)):
    return annotate(conn, project_id, mockup_id, data.annotations)


@router.post("/api/projects/{project_id}/mockups/{mockup_id}/versions/{number}/restore",
             response_model=Mockup)
def post_restore(project_id: int, mockup_id: int, number: int,
                 conn: sqlite3.Connection = Depends(db.get_db)):
    return restore(conn, project_id, mockup_id, number)


@router.put("/api/projects/{project_id}/stories/{story_id}/mockups/{mockup_id}", status_code=204)
def put_link(project_id: int, story_id: int, mockup_id: int,
             conn: sqlite3.Connection = Depends(db.get_db)):
    link(conn, project_id, story_id, mockup_id)


@router.delete("/api/projects/{project_id}/stories/{story_id}/mockups/{mockup_id}", status_code=204)
def delete_link(project_id: int, story_id: int, mockup_id: int,
                conn: sqlite3.Connection = Depends(db.get_db)):
    unlink(conn, project_id, story_id, mockup_id)

