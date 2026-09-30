import pytest

STORY = {"role_name": "Külastaja", "role_phrase": "Külastajana", "action": "näha pakette", "benefit": "valida"}


@pytest.fixture
def project(client):
    return client.post("/api/projects", json={"name": "P"}).json()


def base(project):
    return f"/api/projects/{project['id']}"


@pytest.fixture
def mockup(client, project):
    story = client.post(f"{base(project)}/stories", json=STORY).json()
    return client.post(f"{base(project)}/mockups", json={"template": "pricing", "story_id": story["id"]}).json()


def edited(tree):
    tree = {**tree, "components": [dict(c) for c in tree["components"]]}
    tree["components"].insert(2, {"id": "vat-note", "type": "note", "text": "Hinnad sisaldavad käibemaksu"})
    tree["components"] = [c for c in tree["components"] if c["id"] != "footer"]
    return tree


def test_saving_an_edit_makes_a_new_version(client, project, mockup):
    response = client.post(f"{base(project)}/mockups/{mockup['id']}/versions", json={"tree": edited(mockup["tree"])})
    assert response.status_code == 200, response.text
    saved = response.json()
    assert saved["version"] == 2
    ids = [c["id"] for c in saved["tree"]["components"]]
    assert "vat-note" in ids and "footer" not in ids
    versions = client.get(f"{base(project)}/mockups/{mockup['id']}/versions").json()
    assert versions[-1]["note"] == "manual"


def test_saving_the_same_tree_adds_no_version(client, project, mockup):
    same = client.post(f"{base(project)}/mockups/{mockup['id']}/versions", json={"tree": mockup["tree"]}).json()
    assert same["version"] == 1


def test_an_invalid_edit_is_rejected(client, project, mockup):
    bad = {**mockup["tree"], "components": [*mockup["tree"]["components"], {"id": "header", "type": "text", "text": "x"}]}
    response = client.post(f"{base(project)}/mockups/{mockup['id']}/versions", json={"tree": bad})
    assert response.status_code == 422 and "used twice" in response.text
    script = {**mockup["tree"], "components": [{"id": "x", "type": "script", "text": "alert(1)"}]}
    assert client.post(f"{base(project)}/mockups/{mockup['id']}/versions", json={"tree": script}).status_code == 422


def test_an_edit_can_be_undone(client, project, mockup):
    client.post(f"{base(project)}/mockups/{mockup['id']}/versions", json={"tree": edited(mockup["tree"])})
    state = client.get(base(project)).json()
    assert state["undo"] == {"action": "mockup_edited", "params": {"title": "Hinnakiri"}}
    client.post(f"{base(project)}/undo")
    assert client.get(base(project)).json()["mockups"][0]["version"] == 1


def test_editing_works_without_ai_and_only_in_its_project(client, project, mockup, monkeypatch):
    monkeypatch.setenv("AI_PROVIDER", "off")
    assert client.post(f"{base(project)}/mockups/{mockup['id']}/versions",
                       json={"tree": edited(mockup["tree"])}).status_code == 200
    other = client.post("/api/projects", json={"name": "Teine"}).json()
    assert client.post(f"{base(other)}/mockups/{mockup['id']}/versions",
                       json={"tree": mockup["tree"]}).status_code == 404
