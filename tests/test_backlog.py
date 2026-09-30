import pytest

from app import db
from app.ai import providers
from tests.test_conversation import Recorder, last_assistant, turn

STORY = {"role_name": "Külastaja", "role_phrase": "Külastajana",
         "action": "näha liikmepakette ja hindu", "benefit": "valida endale sobiv pakett"}


@pytest.fixture
def project(client):
    return client.post("/api/projects", json={"name": "Spordiklubi"}).json()


def url(project, path=""):
    return f"/api/projects/{project['id']}{path}"


def add(client, project, **extra):
    response = client.post(url(project, "/stories"), json={**STORY, **extra})
    assert response.status_code == 201, response.text
    return response.json()


def state(client, project):
    return client.get(url(project)).json()


def test_manual_story_has_all_fields(client, project):
    story = add(client, project, size="M", criteria=["Iga paketi juures on hind eurodes.", "  "],
                open_questions=["Kas hinnad sisaldavad käibemaksu?"], notes="Klient saadab hinnakirja.")
    assert story["key"] == "US-1"
    assert story["origin"] == "manual"
    assert story["status"] == "idea"
    assert story["size"] == "M"
    assert story["position"] == 0
    assert [c["text"] for c in story["criteria"]] == ["Iga paketi juures on hind eurodes."]
    assert story["criteria"][0]["origin"] == "manual"
    assert story["open_questions"] == ["Kas hinnad sisaldavad käibemaksu?"]
    assert story["title"] == ("Külastajana soovin näha liikmepakette ja hindu, "
                              "et valida endale sobiv pakett.")
    assert state(client, project)["stories"][0]["id"] == story["id"]


def test_invalid_story_input_is_rejected(client, project):
    assert client.post(url(project, "/stories"), json={**STORY, "action": " "}).status_code == 422
    assert client.post(url(project, "/stories"), json={**STORY, "size": "XL"}).status_code == 422
    assert client.post(url(project, "/stories"), json={**STORY, "origin": "ai"}).status_code == 422
    assert client.post("/api/projects/999/stories", json=STORY).status_code == 404


def test_edit_parts_recomposes_the_title(client, project):
    story = add(client, project, size="S")
    edited = client.patch(url(project, f"/stories/{story['id']}"),
                          json={"role_name": "Klubi liige", "role_phrase": "Klubi liikmena",
                                "clear_size": True, "status": "reviewed"}).json()
    assert edited["title"].startswith("Klubi liikmena soovin näha liikmepakette")
    assert edited["size"] is None
    assert edited["status"] == "reviewed"


def test_editing_criteria_keeps_unchanged_ones(client, project, monkeypatch):
    recorder = Recorder()
    monkeypatch.setattr(providers, "get", lambda name=None: recorder)
    turn(client, project, kind="roles", roles=[{"name": "Külastaja"}])
    message = last_assistant(state(client, project))
    story = turn(client, project, kind="stories", message_id=message["id"],
                 selected=[0]).json()["stories"][0]
    with_ai = client.patch(url(project, f"/stories/{story['id']}"),
                           json={"criteria": ["A", "B"]}).json()
    kept = with_ai["criteria"][0]
    edited = client.patch(url(project, f"/stories/{story['id']}"),
                          json={"criteria": ["A", "C"]}).json()
    assert edited["criteria"][0]["id"] == kept["id"]
    assert [c["text"] for c in edited["criteria"]] == ["A", "C"]


def test_delete_compacts_positions_and_never_reuses_numbers(client, project):
    first, second, third = (add(client, project, action=f"teha {n}") for n in range(3))
    assert client.delete(url(project, f"/stories/{second['id']}")).status_code == 204
    stories = state(client, project)["stories"]
    assert [(s["key"], s["position"]) for s in stories] == [("US-1", 0), ("US-3", 1)]
    assert add(client, project)["key"] == "US-4"


def test_reorder_persists_and_must_be_a_full_permutation(client, project):
    ids = [add(client, project, action=f"teha {n}")["id"] for n in range(3)]
    new_order = [ids[2], ids[0], ids[1]]
    assert client.put(url(project, "/stories/order"), json={"ids": new_order}).status_code == 204
    assert [s["id"] for s in state(client, project)["stories"]] == new_order
    assert client.put(url(project, "/stories/order"), json={"ids": ids[:2]}).status_code == 422
    assert client.put(url(project, "/stories/order"), json={"ids": [ids[0]] * 3}).status_code == 422


def test_each_change_can_be_undone(client, project):
    story = add(client, project, criteria=["Hind on eurodes."])
    other = add(client, project, action="registreeruda")

    client.patch(url(project, f"/stories/{story['id']}"), json={"action": "muudetud", "criteria": []})
    assert state(client, project)["undo"] == {"action": "story_edited", "params": {"key": "US-1"}}
    client.post(url(project, "/undo"))
    restored = state(client, project)["stories"][0]
    assert restored["action"] == STORY["action"]
    assert [c["text"] for c in restored["criteria"]] == ["Hind on eurodes."]

    client.put(url(project, "/stories/order"), json={"ids": [other["id"], story["id"]]})
    client.post(url(project, "/undo"))
    assert [s["id"] for s in state(client, project)["stories"]] == [story["id"], other["id"]]

    client.delete(url(project, f"/stories/{story['id']}"))
    undone = client.post(url(project, "/undo")).json()
    assert undone == {"action": "story_deleted", "params": {"key": "US-1"}}
    back = state(client, project)["stories"]
    assert back[0]["id"] == story["id"] and back[0]["key"] == "US-1"
    assert back[0]["criteria"][0]["text"] == "Hind on eurodes."

    client.post(url(project, "/undo"))  # the second add
    client.post(url(project, "/undo"))  # the first add
    assert state(client, project)["stories"] == []
    assert client.post(url(project, "/undo")).status_code == 409


def test_adding_ai_stories_can_be_undone(client, project, monkeypatch):
    recorder = Recorder()
    monkeypatch.setattr(providers, "get", lambda name=None: recorder)
    message = last_assistant(turn(client, project, kind="roles", roles=[{"name": "Külastaja"}]).json())
    turn(client, project, kind="stories", message_id=message["id"], selected=[0, 1, 2])
    assert state(client, project)["undo"]["action"] == "stories_added"
    client.post(url(project, "/undo"))
    assert state(client, project)["stories"] == []


def test_manual_management_works_with_ai_off(client, project, monkeypatch):
    monkeypatch.setenv("AI_PROVIDER", "off")
    story = add(client, project)
    assert client.patch(url(project, f"/stories/{story['id']}"), json={"size": "L"}).status_code == 200
    second = add(client, project)
    assert client.put(url(project, "/stories/order"),
                      json={"ids": [second["id"], story["id"]]}).status_code == 204
    assert client.delete(url(project, f"/stories/{story['id']}")).status_code == 204
    assert client.post(url(project, "/undo")).status_code == 200
    assert len(state(client, project)["stories"]) == 2


def test_manual_edits_reach_the_ai(client, project, monkeypatch):
    recorder = Recorder()
    monkeypatch.setattr(providers, "get", lambda name=None: recorder)
    story = add(client, project)
    client.patch(url(project, f"/stories/{story['id']}"),
                 json={"criteria": ["Hinna juures on märge „sh km“."], "size": "S"})
    turn(client, project, kind="text", text="Jätkame")
    sent = recorder.payloads[-1]["backlog"][0]
    assert sent["criteria"] == ["Hinna juures on märge „sh km“."]
    assert sent["size"] == "S"


def test_stories_of_another_project_are_out_of_reach(client, project):
    other = client.post("/api/projects", json={"name": "Teine"}).json()
    story = add(client, other)
    assert client.patch(url(project, f"/stories/{story['id']}"), json={"size": "S"}).status_code == 404
    assert client.delete(url(project, f"/stories/{story['id']}")).status_code == 404


def test_upgrade_starts_story_numbers_after_existing_ones(tmp_path, monkeypatch):
    path = tmp_path / "old.db"
    monkeypatch.setattr(db, "MIGRATIONS", db.MIGRATIONS[:3])
    db.init(path)
    conn = db.connect(path)
    with conn:
        conn.execute("INSERT INTO projects (name, created_at, updated_at) VALUES ('P', 't', 't')")
        conn.execute("INSERT INTO stories (project_id, number, role_name, role_phrase, action, benefit,"
                     " position, origin, created_at, updated_at) VALUES (1, 7, 'r', 'r', 'a', 'b', 0,"
                     " 'ai', 't', 't')")
    conn.close()
    monkeypatch.undo()
    db.init(path)
    conn = db.connect(path)
    assert conn.execute("SELECT story_seq FROM projects WHERE id = 1").fetchone()[0] == 7
    conn.close()
