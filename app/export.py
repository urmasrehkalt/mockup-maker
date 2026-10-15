"""Backlog export: Markdown for reading and sharing, CSV for spreadsheets.

Both follow the backlog order and the MVP line, and use the project's content
language for their headings. CSV is UTF-8 with a byte-order mark so that
spreadsheet programs show Estonian letters correctly.
"""
from __future__ import annotations

import csv
import io
import re
import sqlite3

from fastapi import APIRouter, Depends
from fastapi.responses import Response

from . import backlog, db, mockups, projects

WORDS = {
    "et": {"exported": "Mockup Makerist eksporditud backlog", "language": "Keel", "stories": "Lugu",
           "mvp": "MVP joon: ülal olevad lood on esimeses versioonis", "status": "Staatus", "size": "Suurus",
           "role": "Roll", "criteria": "Vastuvõtukriteeriumid", "no_criteria": "Kriteeriumid puuduvad.",
           "questions": "Avatud küsimused", "notes": "Märkused", "mockups": "Mockup'id", "origin": "Päritolu",
           "origin_ai": "AI ettepanek", "origin_manual": "käsitsi", "ideas": "Avatud ideed", "in_mvp": "MVP", "yes": "jah", "no": "ei",
           "statuses": {"idea": "Idee", "needs_clarification": "Vajab täpsustamist", "reviewed": "Läbivaadatud",
                        "ready": "Valmis arenduseks"}},
    "en": {"exported": "Backlog exported from Mockup Maker", "language": "Language", "stories": "Stories",
           "mvp": "MVP line: the stories above it are in the first version", "status": "Status", "size": "Size",
           "role": "Role", "criteria": "Acceptance criteria", "no_criteria": "No criteria.",
           "questions": "Open questions", "notes": "Notes", "mockups": "Mockups", "origin": "Origin",
           "origin_ai": "AI proposal", "origin_manual": "manual", "ideas": "Open ideas", "in_mvp": "MVP", "yes": "yes", "no": "no",
           "statuses": {"idea": "Idea", "needs_clarification": "Needs clarification", "reviewed": "Reviewed",
                        "ready": "Ready for development"}},
}
CSV_COLUMNS = ["key", "title", "role", "role_phrase", "action", "benefit", "status", "size", "in_mvp",
               "criteria", "open_questions", "notes", "mockups", "origin"]


def _slug(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-") or "backlog"


def markdown(conn: sqlite3.Connection, project_id: int) -> str:
    project = projects.get(conn, project_id)
    w = WORDS[project.language]
    stories = backlog.stories(conn, project_id)
    titles = {m.id: f"{m.title} (v{m.version})" for m in mockups.mockups(conn, project_id)}
    lines = [f"# {project.name}", ""]
    if project.description:
        lines += [project.description, ""]
    lines += [f"_{w['exported']} · {w['language']}: {project.language.upper()}_", ""]
    for index, story in enumerate(stories):
        if project.mvp_count is not None and index == project.mvp_count:
            lines += ["---", "", f"**{w['mvp']}**", "", "---", ""]
        lines += [f"## {story.key}: {story.title}", ""]
        facts = [f"{w['role']}: {story.role_name}", f"{w['status']}: {w['statuses'][story.status]}"]
        if story.size:
            facts.append(f"{w['size']}: {story.size}")
        if story.in_mvp:
            facts.append(w["in_mvp"])
        lines += [" · ".join(facts), "", f"**{w['criteria']}**", ""]
        lines += [f"- [ ] {c.text}" for c in story.criteria] or [w["no_criteria"]]
        lines.append("")
        if story.open_questions:
            lines += [f"**{w['questions']}**", "", *[f"- {q}" for q in story.open_questions], ""]
        if story.notes:
            lines += [f"**{w['notes']}**", "", story.notes, ""]
        if story.mockup_ids:
            lines += [f"**{w['mockups']}:** " + ", ".join(titles.get(m, str(m)) for m in story.mockup_ids), ""]
    if project.mvp_count is not None and project.mvp_count >= len(stories):
        lines += ["---", "", f"**{w['mvp']}**", ""]
    ideas = projects.open_ideas(conn, project_id)
    if ideas:
        lines += [f"## {w['ideas']}", "", *[f"- {' '.join(idea.text.split())}" for idea in ideas], ""]
    return "\n".join(lines).rstrip() + "\n"


def csv_text(conn: sqlite3.Connection, project_id: int) -> str:
    project = projects.get(conn, project_id)
    w = WORDS[project.language]
    titles = {m.id: m.title for m in mockups.mockups(conn, project_id)}
    out = io.StringIO()
    writer = csv.writer(out)
    writer.writerow(CSV_COLUMNS)
    for story in backlog.stories(conn, project_id):
        writer.writerow([
            story.key, story.title, story.role_name, story.role_phrase, story.action, story.benefit,
            w["statuses"][story.status], story.size or "", w["yes"] if story.in_mvp else w["no"],
            "\n".join(c.text for c in story.criteria), "\n".join(story.open_questions), story.notes,
            ", ".join(titles.get(m, str(m)) for m in story.mockup_ids),
            w["origin_ai"] if story.origin == "ai" else w["origin_manual"],
        ])
    return out.getvalue()


router = APIRouter(prefix="/api/projects/{project_id}", tags=["export"])


def _download(content: str, filename: str, media_type: str) -> Response:
    return Response(content.encode("utf-8"), media_type=media_type,
                    headers={"Content-Disposition": f'attachment; filename="{filename}"'})


@router.get("/export.md")
def export_markdown(project_id: int, conn: sqlite3.Connection = Depends(db.get_db)):
    name = _slug(projects.get(conn, project_id).name)
    return _download(markdown(conn, project_id), f"{name}-backlog.md", "text/markdown; charset=utf-8")


@router.get("/export.csv")
def export_csv(project_id: int, conn: sqlite3.Connection = Depends(db.get_db)):
    name = _slug(projects.get(conn, project_id).name)
    return _download("﻿" + csv_text(conn, project_id), f"{name}-backlog.csv", "text/csv; charset=utf-8")
