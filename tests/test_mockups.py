import copy

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app import mockups
from app.main import app
from app.mockup_templates import TEMPLATES

REQUIRED_TYPES = {"header", "nav", "heading", "text", "image", "card", "grid", "price_card", "list",
                  "table", "form", "input", "button", "footer"}
STORY = {"role_name": "Külastaja", "role_phrase": "Külastajana",
         "action": "näha liikmepakette ja hindu", "benefit": "valida endale sobiv pakett"}


def tree(*components, title="Vaade"):
    return {"title": title, "components": list(components)}


def text(id_="t", value="Tere"):
    return {"id": id_, "type": "text", "text": value}


def problems(data):
    with pytest.raises(ValidationError) as info:
        mockups.Tree.model_validate(data)
    return str(info.value)


@pytest.fixture
def project(client):
    return client.post("/api/projects", json={"name": "Spordiklubi"}).json()


@pytest.fixture
def story(client, project):
    return client.post(f"/api/projects/{project['id']}/stories", json=STORY).json()


# --- library and templates -----------------------------------------------

def test_library_has_the_required_components():
    assert REQUIRED_TYPES <= set(mockups.ComponentType.__args__)


def test_templates_cover_the_required_pages_and_are_valid(client):
    served = client.get("/api/mockup-templates").json()
    keys = {t["key"] for t in served}
    assert {"landing", "list", "detail", "form", "checkout"} <= keys
    used = set()

    def collect(node):
        used.add(node["type"])
        for child in node.get("children") or []:
            collect(child)
    for template in served:
        mockups.Tree.model_validate(template["tree"])
        for component in template["tree"]["components"]:
            collect(component)
    assert REQUIRED_TYPES <= used  # every required component appears in some template


# --- validation ----------------------------------------------------------

def test_unknown_component_type_is_rejected():
    assert "type" in problems(tree({"id": "x", "type": "iframe", "text": "http://evil"}))


def test_unknown_fields_are_rejected():
    assert "html" in problems(tree({**text(), "html": "<b>x</b>"}))


def test_ids_must_be_unique_and_well_formed():
    assert "used twice" in problems(tree(text("a"), text("a")))
    assert "lowercase" in problems(tree(text("Bad Id")))


def test_only_containers_have_children():
    assert "may have children" in problems(tree({**text(), "children": [text("u")]}))


def test_type_specific_rules():
    assert "needs text" in problems(tree({"id": "h", "type": "heading"}))
    assert "needs items" in problems(tree({"id": "n", "type": "nav"}))
    assert "variant must be one of" in problems(tree({"id": "i", "type": "input", "text": "Nimi"}))
    assert "row 1 has 1 cells for 2 columns" in problems(tree(
        {"id": "tb", "type": "table", "items": ["A", "B"], "rows": [["x"]]}))
    assert "a grid may only hold" in problems(tree(
        {"id": "g", "type": "grid", "children": [{"id": "b", "type": "button", "text": "OK"}]}))


def test_depth_and_size_are_limited():
    node = text("leaf")
    for depth in range(8):
        node = {"id": f"s{depth}", "type": "section", "children": [node]}
    assert "nested deeper" in problems(tree(node))
    many = [{"id": f"s{i}", "type": "section", "children": [text(f"t{i}-{j}") for j in range(6)]}
            for i in range(25)]
    assert "maximum is" in problems(tree(*many))


def test_component_ids_are_collected_for_criteria_links():
    landing = mockups.Tree(**TEMPLATES["landing"][1])
    ids = mockups.component_ids(landing)
    assert {"header", "nav", "hero-cta", "feature-2", "footer"} <= ids


def test_markup_in_text_is_kept_as_plain_data():
    payload = "<script>alert(1)</script><img src=x onerror=alert(2)>"
    parsed = mockups.Tree.model_validate(tree(text("x", payload)))
    assert parsed.components[0].text == payload  # stored verbatim; the browser renders it as text


# --- API -----------------------------------------------------------------

def base(project):
    return f"/api/projects/{project['id']}"


def test_mockup_from_template_linked_to_story(client, project, story):
    response = client.post(f"{base(project)}/mockups",
                           json={"template": "pricing", "story_id": story["id"], "title": "Liikmepaketid"})
    assert response.status_code == 201, response.text
    mockup = response.json()
    assert mockup["title"] == "Liikmepaketid" and mockup["tree"]["title"] == "Liikmepaketid"
    assert mockup["version"] == 1 and mockup["story_ids"] == [story["id"]]

    state = client.get(base(project)).json()
    assert [m["id"] for m in state["mockups"]] == [mockup["id"]]
    assert state["stories"][0]["mockup_ids"] == [mockup["id"]]
    assert state["undo"] == {"action": "mockup_linked", "params": {"key": "US-1"}}


def test_mockup_from_tree_is_validated(client, project):
    good = client.post(f"{base(project)}/mockups", json={"tree": tree(text())})
    assert good.status_code == 201
    bad = client.post(f"{base(project)}/mockups", json={"tree": tree({"id": "x", "type": "marquee"})})
    assert bad.status_code == 422
    assert client.post(f"{base(project)}/mockups", json={"template": "nope"}).status_code == 422
    assert client.post(f"{base(project)}/mockups", json={}).status_code == 422
    assert client.post(f"{base(project)}/mockups",
                       json={"template": "form", "tree": tree(text())}).status_code == 422


def test_link_unlink_and_undo(client, project, story):
    mockup = client.post(f"{base(project)}/mockups", json={"template": "form"}).json()
    path = f"{base(project)}/stories/{story['id']}/mockups/{mockup['id']}"
    assert client.put(path).status_code == 204
    assert client.get(base(project)).json()["stories"][0]["mockup_ids"] == [mockup["id"]]
    assert client.delete(path).status_code == 204
    assert client.get(base(project)).json()["stories"][0]["mockup_ids"] == []
    client.post(f"{base(project)}/undo")  # undo the unlink
    assert client.get(base(project)).json()["stories"][0]["mockup_ids"] == [mockup["id"]]


def test_undoing_a_story_edit_keeps_its_mockup_link(client, project, story):
    mockup = client.post(f"{base(project)}/mockups", json={"template": "form", "story_id": story["id"]}).json()
    client.patch(f"{base(project)}/stories/{story['id']}", json={"size": "S"})
    client.post(f"{base(project)}/undo")
    assert client.get(base(project)).json()["stories"][0]["mockup_ids"] == [mockup["id"]]


def test_mockups_of_other_projects_are_out_of_reach(client, project, story):
    other = client.post("/api/projects", json={"name": "Teine"}).json()
    foreign = client.post(f"{base(other)}/mockups", json={"template": "form"}).json()
    assert client.get(f"{base(project)}/mockups/{foreign['id']}").status_code == 404
    assert client.put(f"{base(project)}/stories/{story['id']}/mockups/{foreign['id']}").status_code == 404


def test_mockups_survive_restart(db_path):
    with TestClient(app) as client:
        project = client.post("/api/projects", json={"name": "P"}).json()
        created = client.post(f"{base(project)}/mockups", json={"template": "checkout"}).json()
    with TestClient(app) as client:
        state = client.get(base(project)).json()
    assert state["mockups"][0]["tree"] == created["tree"]


def test_templates_are_not_shared_mutable_state(client, project):
    before = copy.deepcopy(TEMPLATES["form"][1])
    client.post(f"{base(project)}/mockups", json={"template": "form", "title": "Muudetud"})
    assert TEMPLATES["form"][1] == before
