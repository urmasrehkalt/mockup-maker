"""One-way push of stories and mockups to the Agile Tracker (../urmas-agiilne-tracker).

The tracker is used through its existing API only: create a project, create or
update stories, upload a mockup image. It rejects unknown fields, so payloads
use exactly its field names. What was sent is remembered in `tracker_links`, so
a second push updates the same tracker story instead of creating another; a
tracker story that was deleted over there is created again.

On update the tracker story's status is left alone: once pushed, the developers
own it (they may already have moved it to Doing).
"""
from __future__ import annotations

import hashlib
import json
import sqlite3
import urllib.error
import urllib.request
import uuid
from typing import Any, Literal, Protocol

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import Response
from pydantic import BaseModel, ConfigDict, Field

from . import backlog, config, db, mockups, projects
from .mockup_png import render_png, site_address

MAX_IMAGE_BYTES = 5 * 1024 * 1024


class TrackerError(Exception):
    """The tracker could not be reached or refused a request."""


class Transport(Protocol):
    def request(self, method: str, path: str, body: dict | None = None,
                image: tuple[str, bytes] | None = None) -> tuple[int, Any]: ...


class HttpTransport:
    """Plain HTTP to the tracker. Multipart only for the one image upload."""

    def __init__(self, base_url: str, timeout: int):
        self.base_url = base_url
        self.timeout = timeout

    def request(self, method, path, body=None, image=None):
        headers, data = {"Accept": "application/json"}, None
        if body is not None:
            headers["Content-Type"] = "application/json"
            data = json.dumps(body).encode()
        elif image is not None:
            boundary = uuid.uuid4().hex
            filename, content = image
            data = (f"--{boundary}\r\nContent-Disposition: form-data; name=\"file\"; filename=\"{filename}\"\r\n"
                    f"Content-Type: image/png\r\n\r\n").encode() + content + f"\r\n--{boundary}--\r\n".encode()
            headers["Content-Type"] = f"multipart/form-data; boundary={boundary}"
        req = urllib.request.Request(self.base_url + path, data=data, method=method, headers=headers)
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as response:
                raw = response.read()
                return response.status, json.loads(raw) if raw else None
        except urllib.error.HTTPError as exc:
            raw = exc.read()
            try:
                return exc.code, json.loads(raw) if raw else None
            except ValueError:
                return exc.code, raw.decode("utf-8", "replace")[:300]
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            raise TrackerError(f"The tracker at {self.base_url} is not reachable: {exc}") from exc


def transport() -> Transport:
    url = config.tracker_url()
    if not url:
        raise HTTPException(503, {"code": "tracker_off", "message": "TRACKER_URL is not set on this server"})
    return HttpTransport(url, config.tracker_timeout())


class PushIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    story_ids: list[int] | None = Field(default=None, max_length=200)  # None: the whole backlog
    frame: bool = False  # draw the mockups inside a browser frame


class PushResult(BaseModel):
    key: str
    outcome: Literal["created", "updated", "skipped", "failed"]
    tracker_id: int | None = None
    mockup: Literal["uploaded", "unchanged", "none", "failed"] = "none"
    message: str = ""


class PushReport(BaseModel):
    tracker_project_id: int | None
    results: list[PushResult]


def _check(status: int, data: Any, what: str) -> Any:
    if 200 <= status < 300:
        return data
    detail = data.get("detail") if isinstance(data, dict) else data
    raise TrackerError(f"The tracker refused to {what} ({status}): {detail}")


def _ensure_project(conn: sqlite3.Connection, project: projects.Project, t: Transport) -> int:
    row = conn.execute("SELECT tracker_project_id FROM projects WHERE id = ?", (project.id,)).fetchone()
    if row["tracker_project_id"]:
        status, _ = t.request("GET", f"/api/projects/{row['tracker_project_id']}")
        if status == 200:
            return row["tracker_project_id"]
    status, data = t.request("POST", "/api/projects", {
        "name": project.name[:120], "description": project.description or (
            "Backlog sent from Mockup Maker" if project.language == "en" else "Mockup Maker'ist saadetud backlog")})
    created = _check(status, data, "create the project")
    with conn:
        conn.execute("UPDATE projects SET tracker_project_id = ? WHERE id = ?", (created["id"], project.id))
    return created["id"]


LABELS = {"et": {"role": "Roll", "size": "Suurus", "questions": "Avatud küsimused"},
          "en": {"role": "Role", "size": "Size", "questions": "Open questions"}}


def story_payload(story: backlog.Story, project_id: int, language: str = "et") -> dict[str, Any]:
    """The tracker's StoryCreate fields, nothing else (it forbids extras)."""
    # The tracker shows the description on one line, so the short facts share it.
    words = LABELS[language]
    facts = [f"{story.key} · Mockup Maker", f"{words['role']}: {story.role_name}"]
    if story.in_mvp:
        facts.append("MVP")
    if story.size:
        facts.append(f"{words['size']}: {story.size}")
    lines = [" · ".join(facts)]
    if story.notes:
        lines += ["", story.notes]
    if story.open_questions:
        lines += ["", f"{words['questions']}:", *[f"- {q}" for q in story.open_questions]]
    return {"title": story.title, "description": "\n".join(lines),
            "points": config.tracker_points().get(story.size or "", 0),
            "projectId": project_id, "acceptanceCriteria": [c.text for c in story.criteria]}


def mockup_image(tree: mockups.Tree, annotations: list[mockups.Annotation], project: projects.Project,
                 frame: bool = False) -> bytes:
    """The PNG of a view, inside a browser frame with the project's made-up address when asked."""
    address = site_address(project.name, tree.title, project.language) if frame else None
    return render_png(tree, annotations, address)


def _push_story(conn: sqlite3.Connection, project: projects.Project, story: backlog.Story, tracker_project: int,
                all_mockups: dict[int, mockups.Mockup], t: Transport, frame: bool = False) -> PushResult:
    if not story.criteria:
        return PushResult(key=story.key, outcome="skipped",
                          message="The tracker needs at least one acceptance criterion")
    payload = story_payload(story, tracker_project, project.language)
    link = conn.execute("SELECT * FROM tracker_links WHERE story_id = ?", (story.id,)).fetchone()
    outcome, tracker_id = "created", None
    if link:
        update = {k: payload[k] for k in ("title", "description", "points", "projectId", "acceptanceCriteria")}
        status, data = t.request("PUT", f"/api/stories/{link['tracker_story_id']}", update)
        if status != 404:
            tracker_id = _check(status, data, f"update {story.key}")["id"]
            outcome = "updated"
    if tracker_id is None:
        status, data = t.request("POST", "/api/stories", {**payload, "status": "todo"})
        tracker_id = _check(status, data, f"create {story.key}")["id"]
        link = None  # a new tracker story has no image yet

    result = PushResult(key=story.key, outcome=outcome, tracker_id=tracker_id)
    digest = link["mockup_hash"] if link else None
    linked = [all_mockups[m] for m in story.mockup_ids if m in all_mockups]
    if linked:
        image = mockup_image(linked[0].tree, linked[0].annotations, project, frame)
        new_digest = hashlib.sha256(image).hexdigest()
        if len(image) > MAX_IMAGE_BYTES:
            result.mockup, result.message = "failed", "The mockup image is larger than 5 MB"
        elif new_digest == digest:
            result.mockup = "unchanged"
        else:
            status, data = t.request("PUT", f"/api/stories/{tracker_id}/mockup",
                                     image=(f"{story.key}-{linked[0].id}.png", image))
            try:
                _check(status, data, f"upload the mockup of {story.key}")
                result.mockup, digest = "uploaded", new_digest
            except TrackerError as exc:
                result.mockup, result.message = "failed", str(exc)
    with conn:
        conn.execute("INSERT OR REPLACE INTO tracker_links (story_id, tracker_story_id, mockup_hash, pushed_at) "
                     "VALUES (?, ?, ?, ?)", (story.id, tracker_id, digest, db.now()))
    return result


def push(conn: sqlite3.Connection, project_id: int, story_ids: list[int] | None,
         t: Transport | None = None, frame: bool = False) -> PushReport:
    project = projects.get(conn, project_id)
    t = t or transport()
    stories = backlog.stories(conn, project_id)
    if story_ids is not None:
        unknown = set(story_ids) - {s.id for s in stories}
        if unknown:
            raise HTTPException(404, f"Stories not in this project: {sorted(unknown)}")
        stories = [s for s in stories if s.id in set(story_ids)]
    try:
        tracker_project = _ensure_project(conn, project, t)
    except TrackerError as exc:
        raise HTTPException(502, {"code": "tracker_unavailable", "message": str(exc)}) from exc
    all_mockups = {m.id: m for m in mockups.mockups(conn, project_id)}
    results = []
    for story in stories:
        try:
            results.append(_push_story(conn, project, story, tracker_project, all_mockups, t, frame))
        except TrackerError as exc:
            results.append(PushResult(key=story.key, outcome="failed", message=str(exc)))
    return PushReport(tracker_project_id=tracker_project, results=results)


# --- API -----------------------------------------------------------------

router = APIRouter(tags=["tracker"])


@router.get("/api/tracker")
def tracker_status() -> dict[str, Any]:
    return {"configured": config.tracker_url() is not None, "public_url": config.tracker_public_url()}


@router.post("/api/projects/{project_id}/tracker/push", response_model=PushReport)
def post_push(project_id: int, data: PushIn, conn: sqlite3.Connection = Depends(db.get_db)):
    return push(conn, project_id, data.story_ids, frame=data.frame)


@router.get("/api/projects/{project_id}/mockups/{mockup_id}/png")
def mockup_png(project_id: int, mockup_id: int, version: int | None = None, frame: bool = False,
               conn: sqlite3.Connection = Depends(db.get_db)):
    if version is None:
        mockup = mockups.get_mockup(conn, project_id, mockup_id)
        tree, number, marks = mockup.tree, mockup.version, mockup.annotations
    else:
        found = next((v for v in mockups.versions(conn, project_id, mockup_id) if v.number == version), None)
        if found is None:
            raise HTTPException(404, "Version not found")
        tree, number, marks = found.tree, found.number, found.annotations
    image = mockup_image(tree, marks, projects.get(conn, project_id), frame)
    return Response(image, media_type="image/png", headers={
        "Content-Disposition": f'inline; filename="mockup-{mockup_id}-v{number}.png"'})
