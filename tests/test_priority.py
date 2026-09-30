import pytest

from app import conversation
from app.ai import providers
from tests.test_conversation import Recorder, last_assistant, turn


@pytest.fixture
def ai(monkeypatch):
    recorder = Recorder()
    monkeypatch.setattr(providers, "get", lambda name=None: recorder)
    return recorder


@pytest.fixture
def project(client):
    return client.post("/api/projects", json={"name": "Spordiklubi"}).json()


def with_backlog(client, project):
    """Confirm roles, add the offered stories; return the state with the priority card."""
    message = last_assistant(turn(client, project, kind="roles", roles=[{"name": "Külastaja"}]).json())
    return turn(client, project, kind="stories", message_id=message["id"], selected=[0, 1, 2, 3, 4]).json()


def test_adding_stories_brings_a_reasoned_recommendation(client, project, ai):
    state = with_backlog(client, project)
    card = last_assistant(state)["content"]["priority"]
    assert card["story_key"] in {s["key"] for s in state["stories"]}
    assert card["reason"]
    assert state["project"]["step"] == "priorities"
    assert state["project"]["current_story_id"] is None  # recommended, not chosen


def test_agreeing_makes_the_story_current(client, project, ai):
    state = with_backlog(client, project)
    message = last_assistant(state)
    recommended = next(s for s in state["stories"] if s["key"] == message["content"]["priority"]["story_key"])
    state = turn(client, project, kind="focus", message_id=message["id"], story_id=recommended["id"]).json()

    assert state["project"]["current_story_id"] == recommended["id"]
    card = next(m for m in state["messages"] if m["id"] == message["id"])["content"]["priority"]
    assert card["chosen"] == {"key": recommended["key"], "agreed": True}
    assert ai.payloads[-1]["current_story"] == recommended["key"]
    assert state["project"]["step"] == "criteria"


def test_choosing_another_story(client, project, ai):
    state = with_backlog(client, project)
    message = last_assistant(state)
    other = state["stories"][2]
    state = turn(client, project, kind="focus", message_id=message["id"], story_id=other["id"]).json()
    card = next(m for m in state["messages"] if m["id"] == message["id"])["content"]["priority"]
    assert card["chosen"] == {"key": other["key"], "agreed": False}
    assert state["project"]["current_story_id"] == other["id"]


def test_focus_needs_a_story_of_this_project_and_a_recommendation(client, project, ai):
    state = with_backlog(client, project)
    other_project = client.post("/api/projects", json={"name": "Teine"}).json()
    foreign = client.post(f"/api/projects/{other_project['id']}/stories", json={
        "role_name": "A", "role_phrase": "A", "action": "a", "benefit": "b"}).json()
    assert turn(client, project, kind="focus", story_id=foreign["id"]).status_code == 404
    first_message = state["messages"][0]
    assert turn(client, project, kind="focus", message_id=first_message["id"],
                story_id=state["stories"][0]["id"]).status_code == 400


def test_deleting_the_current_story_clears_it(client, project, ai):
    state = with_backlog(client, project)
    story = state["stories"][0]
    turn(client, project, kind="focus", story_id=story["id"])
    client.delete(f"/api/projects/{project['id']}/stories/{story['id']}")
    assert client.get(f"/api/projects/{project['id']}").json()["project"]["current_story_id"] is None


def _turn(**extra):
    return conversation.Turn.model_validate({
        "message": "Milline on kõige olulisem?", "step": "priorities", "interpreted_answer": None,
        "noted_fact": None, "question": None, "roles": None, "stories": None, "priority": None,
        "next_steps": [{"label": "Edasi", "kind": "reply", "step": None}], **extra})


def test_priority_rules():
    payload = {"step": "priorities", "user_input": {"kind": "stories"}, "clarifications_asked": 1,
               "backlog": [{"key": "US-1"}, {"key": "US-2"}], "roles": [{"name": "Külastaja"}]}
    assert "same turn" in conversation.check_turn(_turn(), payload)
    wrong = _turn(priority={"story_key": "US-9", "reason": "x"})
    assert "US-9" in conversation.check_turn(wrong, payload)
    good = _turn(priority={"story_key": "US-2", "reason": "Ilma selleta pole mõtet."})
    assert conversation.check_turn(good, payload) is None
    entering = {**payload, "user_input": {"kind": "next", "step": "priorities"}}
    assert "same turn" in conversation.check_turn(_turn(), entering)
    chatting = {**payload, "user_input": {"kind": "text"}}
    assert conversation.check_turn(_turn(), chatting) is None
