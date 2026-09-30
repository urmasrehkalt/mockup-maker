import pytest
from fastapi.testclient import TestClient

from app import backlog, conversation
from app.ai import providers
from app.main import app
from tests.test_conversation import IDEA, Recorder, last_assistant, turn


@pytest.fixture
def ai(monkeypatch):
    recorder = Recorder()
    monkeypatch.setattr(providers, "get", lambda name=None: recorder)
    return recorder


@pytest.fixture
def project(client):
    return client.post("/api/projects", json={"name": "Spordiklubi"}).json()


def offered(client, project):
    """Walk to the stories step with confirmed roles and return the story suggestion."""
    turn(client, project, kind="roles", roles=[{"name": "Külastaja"}, {"name": "Administraator"}])
    state = turn(client, project, kind="next", label="Paku kasutajalood", step="stories").json()
    return state, last_assistant(state)


def test_ai_offers_at_least_five_stories_in_order_without_adding_them(client, project, ai):
    state, message = offered(client, project)
    stories = message["content"]["stories"]
    assert len(stories) >= 5
    assert stories[0]["action"] == conversation.MOCK_HAPPY_PATH[0][0]  # happy-path order kept
    assert all(st["role_name"] == "Külastaja" for st in stories)
    assert state["stories"] == []


def test_selected_stories_are_added_with_parts_and_ai_origin(client, project, ai):
    _, message = offered(client, project)
    selected = [0, 1, 2, 4, 5, 6]  # the user unticked one
    state = turn(client, project, kind="stories", message_id=message["id"], selected=selected).json()

    stories = state["stories"]
    assert [s["key"] for s in stories] == ["US-1", "US-2", "US-3", "US-4", "US-5", "US-6"]
    assert [s["position"] for s in stories] == list(range(6))
    offered_parts = message["content"]["stories"]
    assert [s["action"] for s in stories] == [offered_parts[i]["action"] for i in selected]
    first = stories[0]
    assert first["origin"] == "ai" and first["status"] == "idea"
    assert (first["role_name"], first["role_phrase"]) == ("Külastaja", "Külastajana")
    assert first["benefit"] == "mõista, mida mulle pakutakse"
    assert first["title"] == ("Külastajana soovin näha avalehel ülevaadet pakutavatest teenustest, "
                              "et mõista, mida mulle pakutakse.")

    card = next(m for m in state["messages"] if m["id"] == message["id"])
    assert card["content"]["stories_added"]["keys"] == [s["key"] for s in stories]
    assert [b["key"] for b in ai.payloads[-1]["backlog"]] == [s["key"] for s in stories]
    assert state["project"]["step"] == "priorities"


def test_add_all(client, project, ai):
    _, message = offered(client, project)
    everything = list(range(len(message["content"]["stories"])))
    state = turn(client, project, kind="stories", message_id=message["id"], selected=everything).json()
    assert len(state["stories"]) == len(everything)


def test_stories_come_from_the_servers_copy_not_the_client(client, project, ai):
    _, message = offered(client, project)
    forged = turn(client, project, kind="stories", message_id=message["id"], selected=[0],
                  stories=[{"role_name": "x", "role_phrase": "x", "action": "hack", "benefit": "x"}])
    assert forged.status_code == 422
    assert turn(client, project, kind="stories", message_id=message["id"], selected=[99]).status_code == 422
    assert turn(client, project, kind="stories", message_id=message["id"], selected=[1, 1]).status_code == 422
    assert turn(client, project, kind="stories", message_id=message["id"], selected=[]).status_code == 422


def test_suggestion_can_be_added_only_once(client, project, ai):
    _, message = offered(client, project)
    turn(client, project, kind="stories", message_id=message["id"], selected=[0])
    again = turn(client, project, kind="stories", message_id=message["id"], selected=[1])
    assert again.status_code == 409


def test_message_without_stories_cannot_be_added(client, project, ai):
    question = last_assistant(turn(client, project, kind="text", text=IDEA).json())
    response = turn(client, project, kind="stories", message_id=question["id"], selected=[0])
    assert response.status_code == 400


def test_suggest_different_ones_gives_a_new_card(client, project, ai):
    _, first = offered(client, project)
    state = turn(client, project, kind="next", label="Paku teistsuguseid", step="stories").json()
    second = last_assistant(state)
    assert second["id"] != first["id"] and second["content"]["stories"]
    assert state["stories"] == []


def _stories_turn(stories):
    return {"message": "Lood.", "step": "stories", "interpreted_answer": None, "noted_fact": None,
            "question": None, "roles": None, "stories": stories,
            "next_steps": [{"label": "Edasi", "kind": "reply", "step": None}]}


def _story(role="Külastaja", n=1):
    return {"role_name": role, "role_phrase": f"{role}na", "action": f"teha asi {n}",
            "benefit": "saada kasu"}


def test_too_few_first_stories_are_sent_back(client, project, monkeypatch):
    answers = [_stories_turn([_story()]), _stories_turn([_story(n=n) for n in range(5)])]
    recorder = Recorder(lambda payload: answers.pop(0))
    monkeypatch.setattr(providers, "get", lambda name=None: recorder)
    state = turn(client, project, kind="roles", roles=[{"name": "Külastaja"}]).json()
    assert "at least 5" in recorder.prompts[1]
    assert len(last_assistant(state)["content"]["stories"]) == 5


def test_check_turn_story_rules():
    turn_ = conversation.Turn.model_validate(_stories_turn([_story()]))
    empty = {"step": "stories", "user_input": {"kind": "next"}, "clarifications_asked": 1,
             "backlog": [], "roles": [{"name": "Külastaja"}]}
    assert "at least 5" in conversation.check_turn(turn_, empty)
    assert conversation.check_turn(turn_, {**empty, "backlog": [{"key": "US-1"}]}) is None
    stranger = conversation.Turn.model_validate(_stories_turn([_story("Häkker", n) for n in range(5)]))
    assert "Häkker" in conversation.check_turn(stranger, empty)


def test_one_card_per_turn():
    both = {**_stories_turn([_story()]),
            "question": {"text": "q", "multi_select": False, "options": ["a", "b"]}}
    with pytest.raises(ValueError):
        conversation.Turn.model_validate(both)


def test_title_is_composed_from_parts():
    parts = backlog.StoryParts(role_name="Klubi liige", role_phrase="klubi liikmena",
                               action="broneerida treening", benefit="saada kindel koht.")
    assert backlog.title(parts) == "Klubi liikmena soovin broneerida treening, et saada kindel koht."


def test_backlog_survives_restart(db_path, monkeypatch):
    recorder = Recorder()
    monkeypatch.setattr(providers, "get", lambda name=None: recorder)
    with TestClient(app) as client:
        project = client.post("/api/projects", json={"name": "P"}).json()
        _, message = offered(client, project)
        turn(client, project, kind="stories", message_id=message["id"], selected=[0, 1])
    with TestClient(app) as client:
        state = client.get(f"/api/projects/{project['id']}").json()
    assert [s["key"] for s in state["stories"]] == ["US-1", "US-2"]


def test_confirming_roles_brings_the_stories_in_the_same_turn(client, project, ai):
    state = turn(client, project, kind="roles", roles=[{"name": "Külastaja"}]).json()
    assert len(last_assistant(state)["content"]["stories"]) >= 5

    silent = conversation.Turn.model_validate({**_stories_turn(None)})
    payload = {"step": "roles", "user_input": {"kind": "roles"}, "clarifications_asked": 2,
               "backlog": [], "roles": [{"name": "Külastaja"}]}
    assert "same turn" in conversation.check_turn(silent, payload)
