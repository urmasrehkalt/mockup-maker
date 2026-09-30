import pytest

from app import conversation
from app.ai import providers
from tests.test_conversation import Recorder, last_assistant, turn

DESCRIPTION = "Leht, kus tutvustatakse klubi treenereid: pilt, spordiala ja tunniplaan."


@pytest.fixture
def ai(monkeypatch):
    recorder = Recorder()
    monkeypatch.setattr(providers, "get", lambda name=None: recorder)
    return recorder


@pytest.fixture
def project(client):
    project = client.post("/api/projects", json={"name": "Spordiklubi"}).json()
    return project


def base(project):
    return f"/api/projects/{project['id']}"


def state(client, project):
    return client.get(base(project)).json()


def proposed(client, project, **extra):
    response = turn(client, project, kind="new_view", text=DESCRIPTION, **extra)
    assert response.status_code == 200, response.text
    return last_assistant(response.json())


def test_describing_a_view_proposes_story_criteria_and_mockup_without_saving(client, project, ai):
    message = proposed(client, project)
    view = message["content"]["new_view"]
    assert view["story"]["action"] and view["story"]["benefit"]
    assert len(view["criteria"]) >= 3 and all("issues" in c for c in view["criteria"])
    assert view["mockup"]["components"]
    current = state(client, project)
    assert current["stories"] == [] and current["mockups"] == []
    assert ai.payloads[-1]["user_input"]["text"] == DESCRIPTION


def test_a_chosen_template_is_the_starting_point(client, project, ai):
    proposed(client, project, template="pricing")
    assert ai.payloads[-1]["template"]["title"] == "Hinnakiri"
    assert turn(client, project, kind="new_view", text="x", template="nope").status_code == 422


def test_adding_creates_story_criteria_and_mockup_and_makes_it_current(client, project, ai):
    message = proposed(client, project)
    offered = message["content"]["new_view"]["criteria"]
    wording = {"role_phrase": "Külastajana", "action": "näha klubi treenereid",
               "benefit": "valida endale sobiv treener"}
    items = [{"index": 0}, {"index": 1, "text": "Iga treeneri juures on tema spordiala."},
             {"index": None, "text": "Iga treeneri juures on tema pilt."}]
    current = turn(client, project, kind="view_add", message_id=message["id"], decision="add",
                   wording=wording, items=items).json()
    story = current["stories"][0]
    assert story["title"] == "Külastajana soovin näha klubi treenereid, et valida endale sobiv treener."
    assert story["origin"] == "ai"
    assert [(c["text"], c["origin"]) for c in story["criteria"]] == [
        (offered[0]["text"], "ai"), ("Iga treeneri juures on tema spordiala.", "manual"),
        ("Iga treeneri juures on tema pilt.", "manual")]
    assert story["criteria"][0]["component_id"] == offered[0]["component_id"]
    assert len(story["mockup_ids"]) == 1 and current["mockups"][0]["story_ids"] == [story["id"]]
    assert current["project"]["current_story_id"] == story["id"]
    assert current["project"]["step"] == "refinements"
    card = next(m for m in current["messages"] if m["id"] == message["id"])["content"]["new_view"]
    assert card["decided"] == {"added": True, "key": story["key"], "mockup_id": story["mockup_ids"][0]}


def test_discarding_creates_nothing_and_each_card_is_decided_once(client, project, ai):
    message = proposed(client, project)
    turn(client, project, kind="view_add", message_id=message["id"], decision="discard")
    assert state(client, project)["stories"] == []
    assert turn(client, project, kind="view_add", message_id=message["id"], decision="add",
                items=[{"index": 0}]).status_code == 409
    other = state(client, project)["messages"][0]
    assert turn(client, project, kind="view_add", message_id=other["id"], decision="add").status_code == 400


def test_one_undo_removes_the_story_and_its_mockup(client, project, ai):
    message = proposed(client, project)
    turn(client, project, kind="view_add", message_id=message["id"], decision="add", items=[{"index": 0}])
    assert state(client, project)["undo"]["action"] == "view_added"
    client.post(f"{base(project)}/undo")
    current = state(client, project)
    assert current["stories"] == [] and current["mockups"] == []


def _with_new_role(payload):
    answer = conversation.mock_turn(payload)
    if answer.get("new_view"):
        answer["new_view"]["new_role"] = {"name": "Treener", "description": "Viib treeninguid läbi."}
        answer["new_view"]["story"].update(role_name="Treener", role_phrase="Treenerina")
    return answer


def test_a_new_role_is_added_only_when_the_view_is_added(client, project, monkeypatch):
    recorder = Recorder(_with_new_role)
    monkeypatch.setattr(providers, "get", lambda name=None: recorder)
    turn(client, project, kind="roles", roles=[{"name": "Külastaja"}])
    message = proposed(client, project)
    assert [r["name"] for r in state(client, project)["roles"]] == ["Külastaja"]
    current = turn(client, project, kind="view_add", message_id=message["id"], decision="add",
                   items=[{"index": 0}, {"index": 1}]).json()
    assert [r["name"] for r in current["roles"]] == ["Külastaja", "Treener"]
    assert current["stories"][-1]["role_name"] == "Treener"


def test_ai_off_says_so_and_saves_nothing(client, project, monkeypatch):
    monkeypatch.setenv("AI_PROVIDER", "off")
    response = turn(client, project, kind="new_view", text=DESCRIPTION)
    assert response.status_code == 503 and response.json()["error"]["code"] == "ai_disabled"
    assert state(client, project)["stories"] == []


def test_english_project_gets_an_english_template(client, ai):
    project = client.post("/api/projects", json={"name": "Club", "language": "en"}).json()
    turn(client, project, kind="new_view", text="A page for the club's coaches.", template="pricing")
    assert ai.payloads[-1]["template"]["title"] == "Pricing"
    assert ai.payloads[-1]["language"] == "en"


def _view(**overrides):
    data = {"story": {"role_name": "Külastaja", "role_phrase": "Külastajana", "action": "näha treenereid",
                      "benefit": "valida treener"},
            "new_role": None,
            "criteria": [{"text": "Lehel on pealkiri.", "component_id": "t"},
                         {"text": "Lehel on nupp.", "component_id": "b"},
                         {"text": "Kinnitus saadetakse e-postile.", "component_id": None}],
            "mockup": {"title": "Treenerid", "components": [{"id": "t", "type": "heading", "text": "Treenerid"},
                                                            {"id": "b", "type": "button", "text": "Vali"}]}}
    data.update(overrides)
    return conversation.Turn.model_validate({
        "message": "Uus vaade.", "step": "stories", "question": None, "roles": None, "stories": None,
        "priority": None, "proposal": None, "change": None, "new_view": data,
        "next_steps": [{"label": "Edasi", "kind": "reply", "step": None}]})


PAYLOAD = {"step": "stories", "user_input": {"kind": "new_view"}, "clarifications_asked": 1,
           "backlog": [], "roles": [{"name": "Külastaja"}], "current_story": None}


def test_new_view_rules():
    assert conversation.check_turn(_view(), PAYLOAD) is None
    stranger = {"role_name": "Häkker", "role_phrase": "Häkkerina", "action": "a", "benefit": "b"}
    assert "not in INPUT.roles" in conversation.check_turn(_view(story=stranger), PAYLOAD)
    existing = _view(new_role={"name": "külastaja", "description": ""})
    assert "already a role" in conversation.check_turn(existing, PAYLOAD)
    mismatch = _view(new_role={"name": "Treener", "description": ""})
    assert "new_role's name" in conversation.check_turn(mismatch, PAYLOAD)
    dangling = _view(criteria=[{"text": "Lehel on x.", "component_id": "nope"},
                               {"text": "Lehel on y.", "component_id": "t"}, {"text": "Lehel on z.", "component_id": None}])
    assert "not in the mockup" in conversation.check_turn(dangling, PAYLOAD)
    vague = _view(criteria=[{"text": "Leht on kasutajasõbralik.", "component_id": "t"},
                            {"text": "Lehel on y.", "component_id": "t"}, {"text": "Lehel on z.", "component_id": None}])
    assert "yes or no" in conversation.check_turn(vague, PAYLOAD)
    no_card = conversation.Turn.model_validate({**_view().model_dump(), "new_view": None})
    assert "same turn" in conversation.check_turn(no_card, PAYLOAD)
