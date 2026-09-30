"""Project templates: a name, a short description and the client's first idea.

Built-in templates live here; the user can save their own (table
`prompt_templates`). A template only pre-fills the new-project form: every
field stays editable, and the idea is sent only when the user sends it.
"""
from __future__ import annotations

import sqlite3

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field

from . import db

BUILT_IN = [
    ("sport", "Spordiklubi veeb", "Treeningute tutvustus ja liikmeks astumine",
     "Spordiklubi tahab veebi, kus saab treeningutega tutvuda ja liikmeks astuda."),
    ("shop", "E-pood", "Tootekataloog, ostukorv ja tellimine",
     "Väike kauplus tahab e-poodi, kus kliendid saavad tooteid sirvida, ostukorvi lisada ja tellimuse "
     "veebis tasuda."),
    ("booking", "Broneerimine", "Aegade broneerimine teenusele",
     "Ilusalong tahab veebi, kus kliendid saavad valida teenuse ja meistri ning broneerida endale sobiva aja."),
    ("members", "Ühingu liikmeveeb", "Liikmete andmed, üritused ja liikmemaks",
     "MTÜ tahab liikmetele veebi, kus näeb üritusi, saab end neile kirja panna ja liikmemaksu tasuda."),
]


class TemplateIn(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    name: str = Field(min_length=1, max_length=120)
    description: str = Field(default="", max_length=1000)
    idea: str = Field(min_length=1, max_length=4000)


class Template(BaseModel):
    key: str        # "sport" for a built-in one, "u12" for a saved one
    name: str
    description: str
    idea: str
    built_in: bool


def all_templates(conn: sqlite3.Connection) -> list[Template]:
    own = conn.execute("SELECT * FROM prompt_templates ORDER BY name COLLATE NOCASE, id").fetchall()
    return ([Template(key=key, name=name, description=desc, idea=idea, built_in=True)
             for key, name, desc, idea in BUILT_IN]
            + [Template(key=f"u{r['id']}", name=r["name"], description=r["description"], idea=r["idea"],
                        built_in=False) for r in own])


router = APIRouter(prefix="/api/templates", tags=["templates"])


@router.get("", response_model=list[Template])
def list_templates(conn: sqlite3.Connection = Depends(db.get_db)):
    return all_templates(conn)


@router.post("", response_model=Template, status_code=201)
def save_template(data: TemplateIn, conn: sqlite3.Connection = Depends(db.get_db)):
    with conn:
        cur = conn.execute("INSERT INTO prompt_templates (name, description, idea, created_at) VALUES (?, ?, ?, ?)",
                           (data.name, data.description, data.idea, db.now()))
    return Template(key=f"u{cur.lastrowid}", built_in=False, **data.model_dump())


@router.delete("/{key}", status_code=204)
def delete_template(key: str, conn: sqlite3.Connection = Depends(db.get_db)):
    if not (key.startswith("u") and key[1:].isdigit()):
        raise HTTPException(409 if any(key == k for k, *_ in BUILT_IN) else 404,
                            "Built-in templates cannot be deleted" if any(key == k for k, *_ in BUILT_IN)
                            else "Template not found")
    with conn:
        cur = conn.execute("DELETE FROM prompt_templates WHERE id = ?", (int(key[1:]),))
    if not cur.rowcount:
        raise HTTPException(404, "Template not found")
