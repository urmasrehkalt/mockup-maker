import pytest

from app.ai import providers
from tests.test_conversation import Recorder


def test_built_in_templates(client):
    templates = client.get("/api/templates").json()
    built_in = [t for t in templates if t["built_in"]]
    assert len(built_in) >= 3
    assert all(t["name"] and t["idea"] for t in built_in)


def test_save_reuse_and_delete_an_own_template(client):
    saved = client.post("/api/templates", json={"name": "Raamatukogu", "description": "Laenutus",
                                                 "idea": "Raamatukogu tahab veebi raamatute broneerimiseks."})
    assert saved.status_code == 201
    key = saved.json()["key"]
    listed = {t["key"]: t for t in client.get("/api/templates").json()}
    assert listed[key]["built_in"] is False and listed[key]["idea"].startswith("Raamatukogu")
    assert client.delete(f"/api/templates/{key}").status_code == 204
    assert key not in {t["key"] for t in client.get("/api/templates").json()}
    assert client.delete(f"/api/templates/{key}").status_code == 404


def test_built_in_templates_cannot_be_deleted_and_input_is_checked(client):
    assert client.delete("/api/templates/sport").status_code == 409
    assert client.delete("/api/templates/nope").status_code == 404
    assert client.post("/api/templates", json={"name": "X", "idea": " "}).status_code == 422
    assert client.post("/api/templates", json={"name": "X", "idea": "y", "html": "<b>"}).status_code == 422


def test_the_idea_is_a_draft_until_the_first_message(client, monkeypatch):
    recorder = Recorder()
    monkeypatch.setattr(providers, "get", lambda name=None: recorder)
    idea = "Spordiklubi tahab veebi, kus saab treeningutega tutvuda ja liikmeks astuda."
    project = client.post("/api/projects", json={"name": "Spordiklubi", "idea": idea}).json()
    state = client.get(f"/api/projects/{project['id']}").json()
    assert state["project"]["draft_idea"] == idea and state["messages"] == []  # nothing sent yet
    edited = idea + " Liikmetasu makstakse veebis."
    client.post(f"/api/projects/{project['id']}/turn", json={"kind": "text", "text": edited})
    state = client.get(f"/api/projects/{project['id']}").json()
    assert state["project"]["draft_idea"] == ""
    assert recorder.payloads[0]["idea"] == edited  # what was sent, not the template's text
