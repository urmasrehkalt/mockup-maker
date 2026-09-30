import pytest

from app import conversation, mockups
from app.ai import providers
from tests.test_conversation import Recorder, last_assistant, turn

PRICING_STORY = {"role_name": "Külastaja", "role_phrase": "Külastajana",
                 "action": "näha liikmepakette ja hindu", "benefit": "valida endale sobiv pakett"}


@pytest.fixture
def ai(monkeypatch):
    recorder = Recorder()
    monkeypatch.setattr(providers, "get", lambda name=None: recorder)
    return recorder


@pytest.fixture
def project(client):
    return client.post("/api/projects", json={"name": "Spordiklubi"}).json()


def base(project):
    return f"/api/projects/{project['id']}"


def proposed(client, project, story_json=PRICING_STORY):
    story = client.post(f"{base(project)}/stories", json=story_json).json()
    state = turn(client, project, kind="focus", story_id=story["id"]).json()
    return story, state, last_assistant(state)


def test_choosing_a_story_brings_criteria_and_a_consistent_mockup(client, project, ai):
    story, state, message = proposed(client, project)
    proposal = message["content"]["proposal"]
    assert proposal["story_key"] == story["key"]
    assert len(proposal["criteria"]) >= 3
    tree = mockups.Tree(**proposal["mockup"])
    ids = mockups.component_ids(tree)
    assert all(c["component_id"] in ids for c in proposal["criteria"] if c["component_id"])
    assert state["project"]["step"] == "criteria"
    assert state["stories"][0]["criteria"] == []  # proposed, not stored
    assert state["mockups"] == []


def test_partial_accept_edit_reject_and_add(client, project, ai):
    story, _, message = proposed(client, project)
    offered = message["content"]["proposal"]["criteria"]
    items = [{"index": 0},                                           # accepted as is
             {"index": 1, "text": "Iga paketi juures on kuutasu eurodes koos käibemaksuga."},  # edited
             {"index": 2},                                           # accepted; index 3 rejected
             {"index": None, "text": "Lehel on link paketi tingimustele."}]  # added
    state = turn(client, project, kind="criteria", message_id=message["id"], items=items).json()

    stored = state["stories"][0]["criteria"]
    assert [c["text"] for c in stored] == [offered[0]["text"], items[1]["text"], offered[2]["text"],
                                          items[3]["text"]]
    assert [c["origin"] for c in stored] == ["ai", "manual", "ai", "manual"]
    assert stored[1]["component_id"] == offered[1]["component_id"]  # edit keeps the link
    assert stored[3]["component_id"] is None

    assert len(state["mockups"]) == 1
    assert state["stories"][0]["mockup_ids"] == [state["mockups"][0]["id"]]
    card = next(m for m in state["messages"] if m["id"] == message["id"])["content"]["proposal"]
    assert card["decided"] == {"kept": 4, "rejected": 1, "mockup_id": state["mockups"][0]["id"]}
    assert state["project"]["step"] == "refinements"


def test_decision_is_validated_and_happens_once(client, project, ai):
    _, _, message = proposed(client, project)
    assert turn(client, project, kind="criteria", message_id=message["id"],
                items=[{"index": 9}]).status_code == 422
    assert turn(client, project, kind="criteria", message_id=message["id"],
                items=[{"index": 0}, {"index": 0}]).status_code == 422
    assert turn(client, project, kind="criteria", message_id=message["id"],
                items=[{"index": None, "text": "  "}]).status_code == 422
    assert turn(client, project, kind="criteria", message_id=message["id"],
                items=[{"index": 0}]).status_code == 200
    assert turn(client, project, kind="criteria", message_id=message["id"],
                items=[{"index": 1}]).status_code == 409


def test_message_without_proposal_is_rejected(client, project, ai):
    state = turn(client, project, kind="text", text="Spordiklubi veeb").json()
    response = turn(client, project, kind="criteria", message_id=last_assistant(state)["id"],
                    items=[{"index": 0}])
    assert response.status_code == 400


def test_existing_mockup_gets_a_new_version(client, project, ai):
    story = client.post(f"{base(project)}/stories", json=PRICING_STORY).json()
    existing = client.post(f"{base(project)}/mockups",
                           json={"template": "landing", "story_id": story["id"]}).json()
    state = turn(client, project, kind="focus", story_id=story["id"]).json()
    assert ai.payloads[-1]["current_story_detail"]["mockup"]["title"] == "Avaleht"
    message = last_assistant(state)
    state = turn(client, project, kind="criteria", message_id=message["id"], items=[{"index": 0}]).json()
    assert [(m["id"], m["version"]) for m in state["mockups"]] == [(existing["id"], 2)]
    assert state["mockups"][0]["title"] == "Hinnakiri"


def test_deciding_can_be_undone(client, project, ai):
    _, _, message = proposed(client, project)
    turn(client, project, kind="criteria", message_id=message["id"], items=[{"index": 0}, {"index": 1}])
    state = client.get(base(project)).json()
    assert state["undo"] == {"action": "criteria_added", "params": {"key": "US-1", "count": 2}}
    client.post(f"{base(project)}/undo")
    story = client.get(base(project)).json()["stories"][0]
    assert story["criteria"] == [] and story["mockup_ids"] == []


def _proposal(**overrides):
    data = {"story_key": "US-1", "criteria": [
        {"text": "Lehel on pealkiri.", "component_id": "t"},
        {"text": "Lehel on nupp.", "component_id": "b"},
        {"text": "Kinnitus saadetakse e-postile.", "component_id": None}],
        "mockup": {"title": "Vaade", "components": [
            {"id": "t", "type": "heading", "text": "Pealkiri"},
            {"id": "b", "type": "button", "text": "OK"}]}}
    data.update(overrides)
    return conversation.Proposal.model_validate(data)


def _turn_with(proposal):
    return conversation.Turn.model_validate({
        "message": "Pakun.", "step": "criteria", "interpreted_answer": None, "noted_fact": None,
        "question": None, "roles": None, "stories": None, "priority": None,
        "proposal": proposal.model_dump() if proposal else None,
        "next_steps": [{"label": "Edasi", "kind": "reply", "step": None}]})


PAYLOAD = {"step": "criteria", "user_input": {"kind": "focus"}, "clarifications_asked": 1,
           "backlog": [{"key": "US-1"}], "roles": [], "current_story": "US-1"}


def test_proposal_rules():
    assert conversation.check_turn(_turn_with(_proposal()), PAYLOAD) is None
    assert "same turn" in conversation.check_turn(_turn_with(None), PAYLOAD)
    assert "US-2" in conversation.check_turn(_turn_with(_proposal(story_key="US-2")), PAYLOAD)
    dangling = _proposal(criteria=[{"text": "x", "component_id": "nope"},
                                   {"text": "y", "component_id": "t"}, {"text": "z", "component_id": None}])
    assert "nope" in conversation.check_turn(_turn_with(dangling), PAYLOAD)
    unlinked = _proposal(criteria=[{"text": t, "component_id": None} for t in "xyz"])
    assert "No criterion refers" in conversation.check_turn(_turn_with(unlinked), PAYLOAD)
    chatting = {**PAYLOAD, "user_input": {"kind": "text"}}
    assert conversation.check_turn(_turn_with(None), chatting) is None
