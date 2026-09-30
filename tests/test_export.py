import csv
import io

import pytest

STORIES = [
    {"role_name": "Külastaja", "role_phrase": "Külastajana", "action": "näha pakette", "benefit": "valida sobiv",
     "size": "S", "criteria": ["Lehel on iga paketi nimi.", "Iga paketi juures on hind, eurodes."]},
    {"role_name": "Külastaja", "role_phrase": "Külastajana", "action": "registreeruda", "benefit": "saada liikmeks",
     "open_questions": ["Kas e-post on kohustuslik?"], "notes": 'Klient ütles: "kiiresti"'},
    {"role_name": "Administraator", "role_phrase": "Administraatorina", "action": "muuta hindu",
     "benefit": "hinnakiri oleks ajakohane"},
]


@pytest.fixture
def project(client):
    project = client.post("/api/projects", json={"name": "Spordiklubi Veeb!", "description": "Klubi veeb"}).json()
    ids = [client.post(f"/api/projects/{project['id']}/stories", json=s).json()["id"] for s in STORIES]
    client.put(f"/api/projects/{project['id']}/stories/order", json={"ids": ids, "mvp_count": 2})
    client.post(f"/api/projects/{project['id']}/mockups", json={"template": "pricing", "story_id": ids[0]})
    return project


def test_markdown_export_follows_the_backlog_and_the_mvp_line(client, project):
    response = client.get(f"/api/projects/{project['id']}/export.md")
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/markdown")
    assert 'filename="spordiklubi-veeb-backlog.md"' in response.headers["content-disposition"]
    text = response.text
    assert text.startswith("# Spordiklubi Veeb!\n")
    order = [text.index(f"## US-{n}:") for n in (1, 2, 3)]
    assert order == sorted(order)
    mvp = text.index("MVP joon")
    assert order[1] < mvp < order[2]  # the line sits between the second and third story
    assert "- [ ] Lehel on iga paketi nimi." in text
    assert "Kas e-post on kohustuslik?" in text
    assert "Hinnakiri (v1)" in text
    assert "Staatus: Idee" in text and "Suurus: S" in text


def test_csv_export_quotes_cells_and_joins_lists(client, project):
    response = client.get(f"/api/projects/{project['id']}/export.csv")
    assert response.headers["content-type"].startswith("text/csv")
    raw = response.content.decode("utf-8")
    assert raw.startswith("﻿")
    rows = list(csv.DictReader(io.StringIO(raw.lstrip("﻿"))))
    assert [r["key"] for r in rows] == ["US-1", "US-2", "US-3"]
    assert rows[0]["criteria"] == "Lehel on iga paketi nimi.\nIga paketi juures on hind, eurodes."
    assert rows[0]["in_mvp"] == "jah" and rows[2]["in_mvp"] == "ei"
    assert rows[1]["notes"] == 'Klient ütles: "kiiresti"'
    assert rows[0]["mockups"] == "Hinnakiri"
    assert rows[2]["role"] == "Administraator" and rows[2]["status"] == "Idee"


def test_exports_use_the_project_language(client):
    project = client.post("/api/projects", json={"name": "Club", "language": "en"}).json()
    client.post(f"/api/projects/{project['id']}/stories", json={
        "role_name": "Visitor", "role_phrase": "a visitor", "action": "see packages", "benefit": "I can choose"})
    text = client.get(f"/api/projects/{project['id']}/export.md").text
    assert "## US-1: As a visitor, I want to see packages, so that I can choose." in text
    assert "Status: Idea" in text and "No criteria." in text
    rows = list(csv.DictReader(io.StringIO(client.get(f"/api/projects/{project['id']}/export.csv").text.lstrip("﻿"))))
    assert rows[0]["status"] == "Idea" and rows[0]["origin"] == "manual"


def test_export_of_an_unknown_project_is_404(client):
    assert client.get("/api/projects/999/export.md").status_code == 404
    assert client.get("/api/projects/999/export.csv").status_code == 404
