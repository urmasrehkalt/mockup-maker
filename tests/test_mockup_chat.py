"""#35: the AI chat beside a mockup changes it and keeps the stories in sync."""
import pytest

from app import db, mockup_chat, mockups
from app.ai import AIError, providers
from tests.test_conversation import Recorder
from tests.test_ready import GOOD, add, base, patch

INSTRUCTION = "Pane märkus pealkirja alla"


@pytest.fixture
def ai(monkeypatch):
    recorder = Recorder()
    monkeypatch.setattr(providers, "get", lambda name=None: recorder)
    return recorder


@pytest.fixture
def project(client):
    return client.post("/api/projects", json={"name": "P"}).json()


def with_mockup(client, project, story):
    client.post(f"{base(project)}/mockups", json={"template": "pricing", "story_id": story["id"]})
    return client.get(base(project)).json()["mockups"][-1]


def story_of(client, project, story):
    return next(s for s in client.get(base(project)).json()["stories"] if s["id"] == story["id"])


def say(client, project, mockup, text=INSTRUCTION, version=None):
    return client.post(f"{base(project)}/mockups/{mockup['id']}/chat",
                       json={"instruction": text, "base_version": version or mockup["version"]})


@pytest.fixture
def setup(client, project):
    story = add(client, project)
    return story, with_mockup(client, project, story)


def test_an_instruction_changes_the_mockup_and_the_stories_criteria(client, project, setup):
    story, mockup = setup
    response = say(client, project, mockup)
    assert response.status_code == 200, response.text
    result = response.json()
    assert result["mockup"]["version"] == 2 and "ai-note-1" in str(result["mockup"]["tree"])
    versions = client.get(f"{base(project)}/mockups/{mockup['id']}/versions").json()
    assert versions[-1]["note"] == "ai"
    criteria = story_of(client, project, story)["criteria"]
    assert [c["text"] for c in criteria][-1] == "Vaates on AI lisatud märge."
    assert criteria[-1]["component_id"] == "ai-note-1"
    assert [m["role"] for m in result["messages"]] == ["user", "assistant"]
    assert result["messages"][0]["text"] == INSTRUCTION
    assert result["messages"][1]["version"] == 2 and result["messages"][1]["story_keys"] == [story["key"]]
    assert result["can_undo"] is True


def test_every_story_linked_to_the_mockup_follows_the_change(client, project, setup):
    story, mockup = setup
    other = add(client, project, action="näha tellimuse kokkuvõtet")
    client.put(f"{base(project)}/stories/{other['id']}/mockups/{mockup['id']}")
    say(client, project, mockup)
    for each in (story, other):
        assert story_of(client, project, each)["criteria"][-1]["component_id"] == "ai-note-1"


def test_one_undo_restores_mockup_criteria_and_story_state(client, project, setup):
    story, mockup = setup
    before = story_of(client, project, story)
    say(client, project, mockup)
    undone = client.post(f"{base(project)}/undo")
    assert undone.status_code == 200 and undone.json()["action"] == "mockup_ai_edited"
    after = client.get(f"{base(project)}/mockups/{mockup['id']}").json()
    assert after["version"] == 1 and "ai-note-1" not in str(after["tree"])
    assert story_of(client, project, story)["criteria"] == before["criteria"]
    chat = client.get(f"{base(project)}/mockups/{mockup['id']}/chat").json()
    assert chat["can_undo"] is False
    assert [m["undone"] for m in chat["messages"] if m["role"] == "assistant"] == [True]


def test_a_second_instruction_after_undo_is_not_marked_undone(client, project, setup):
    _, mockup = setup
    say(client, project, mockup)
    client.post(f"{base(project)}/undo")
    say(client, project, mockup, text="Pane veel üks märkus")
    chat = client.get(f"{base(project)}/mockups/{mockup['id']}/chat").json()
    assistants = [m for m in chat["messages"] if m["role"] == "assistant"]
    assert [m["undone"] for m in assistants] == [True, False]


def test_a_stale_version_is_refused_and_changes_nothing(client, project, setup):
    story, mockup = setup
    say(client, project, mockup)  # now v2
    before = story_of(client, project, story)
    response = say(client, project, mockup, version=1)
    assert response.status_code == 409 and response.json()["detail"]["code"] == "stale_version"
    assert client.get(f"{base(project)}/mockups/{mockup['id']}").json()["version"] == 2
    assert story_of(client, project, story) == before
    assert len(client.get(f"{base(project)}/mockups/{mockup['id']}/chat").json()["messages"]) == 2


def test_a_mockup_edited_by_hand_meanwhile_is_refused(client, project, ai, setup):
    story, mockup = setup

    def edit_by_hand(payload):  # runs on the event loop, so it writes through its own connection
        other = db.connect()
        with other:
            mockups.add_version(other, mockup["id"], mockups.Tree(**dict(mockup["tree"], title="Käsitsi")),
                                note="manual")
        other.close()
        return mockup_chat.mock_edit(payload)

    ai.override = edit_by_hand
    response = say(client, project, mockup)
    assert response.status_code == 409
    versions = client.get(f"{base(project)}/mockups/{mockup['id']}/versions").json()
    assert [v["note"] for v in versions][-1] == "manual"


def test_a_failed_ai_answer_changes_nothing_and_stores_nothing(client, project, ai, setup):
    story, mockup = setup
    before = story_of(client, project, story)
    ai.override = lambda payload: AIError("ai_unavailable", "Codex is down")
    response = say(client, project, mockup)
    assert response.status_code == 503
    assert client.get(f"{base(project)}/mockups/{mockup['id']}").json()["version"] == 1
    assert story_of(client, project, story) == before
    assert client.get(f"{base(project)}/mockups/{mockup['id']}/chat").json() == {"messages": [], "can_undo": False}


def test_criteria_pointing_at_a_removed_component_are_sent_back_and_fixed(client, project, ai, setup):
    story, mockup = setup
    say(client, project, mockup)  # adds ai-note-1 and a criterion about it
    current = client.get(f"{base(project)}/mockups/{mockup['id']}").json()
    calls = []

    def answer(payload):
        calls.append(payload)
        reply = mockup_chat.mock_edit(payload)
        components = [c for c in reply["mockup"]["components"] if c["id"] != "ai-note-1"
                      and not c["id"].startswith("ai-note")]
        reply["mockup"] = {**reply["mockup"], "components": components}
        if len(calls) >= 3:  # the third attempt follows the feedback
            reply["criteria"] = [{"story_key": s["key"], "criteria": [
                {"text": c["text"], "component_id": None} for c in s["criteria"]]}
                for s in payload["stories"]]
        else:
            reply["criteria"] = []
        return reply

    ai.override = answer
    response = say(client, project, current, text="Võta märkus ära")
    assert response.status_code == 200, response.text
    assert len(calls) == 3
    assert "refer to components that are not in the new mockup" in ai.prompts[-1]
    assert all(c["component_id"] is None for c in story_of(client, project, story)["criteria"])


def test_an_answer_that_never_gets_the_criteria_right_is_refused(client, project, ai, setup):
    story, mockup = setup
    say(client, project, mockup)
    current = client.get(f"{base(project)}/mockups/{mockup['id']}").json()

    def answer(payload):
        reply = mockup_chat.mock_edit(payload)
        reply["mockup"] = {**reply["mockup"], "components": [
            c for c in reply["mockup"]["components"] if not c["id"].startswith("ai-note")]}
        reply["criteria"] = []
        return reply

    ai.override = answer
    before = story_of(client, project, story)
    response = say(client, project, current, text="Võta märkus ära")
    assert response.status_code == 502
    assert len(ai.prompts) == 1 + mockup_chat.ATTEMPTS
    assert client.get(f"{base(project)}/mockups/{mockup['id']}").json()["version"] == 2
    assert story_of(client, project, story) == before


def test_an_unchanged_tree_is_a_reply_without_a_new_version(client, project, ai, setup):
    story, mockup = setup
    ai.override = lambda payload: {"summary": "Foto on juba paremal.", "mockup": payload["mockup"]["tree"],
                                   "criteria": []}
    result = say(client, project, mockup).json()
    assert result["mockup"]["version"] == 1
    assert result["messages"][-1]["text"] == "Foto on juba paremal." and result["messages"][-1]["version"] is None
    assert result["can_undo"] is False
    assert client.get(base(project)).json()["undo"]["action"] != "mockup_ai_edited"


def test_a_story_that_was_ready_is_rechecked(client, project, ai, setup):
    story, mockup = setup
    assert patch(client, project, story, status="ready").json()["status"] == "ready"

    def too_few(payload):
        reply = mockup_chat.mock_edit(payload)
        reply["criteria"] = [{"story_key": story["key"], "criteria": [
            {"text": "Vaates on AI lisatud märge.", "component_id": "ai-note-1"}]}]
        return reply

    ai.override = too_few
    say(client, project, mockup)
    assert story_of(client, project, story)["status"] == "reviewed"


def test_history_belongs_to_one_mockup_and_survives_a_reload(client, project, setup):
    story, mockup = setup
    other = with_mockup(client, project, add(client, project, action="näha kontakte"))
    say(client, project, mockup)
    assert len(client.get(f"{base(project)}/mockups/{mockup['id']}/chat").json()["messages"]) == 2
    assert client.get(f"{base(project)}/mockups/{other['id']}/chat").json()["messages"] == []


def test_instruction_and_version_are_validated(client, project, setup):
    _, mockup = setup
    url = f"{base(project)}/mockups/{mockup['id']}/chat"
    assert client.post(url, json={"instruction": "", "base_version": 1}).status_code == 422
    assert client.post(url, json={"instruction": "x", "base_version": 1, "extra": 1}).status_code == 422
    assert client.get(f"{base(project)}/mockups/999/chat").status_code == 404


def test_the_chat_of_another_project_is_not_reachable(client, project, setup):
    _, mockup = setup
    other = client.post("/api/projects", json={"name": "Teine"}).json()
    assert client.get(f"{base(other)}/mockups/{mockup['id']}/chat").status_code == 404
    assert say(client, other, mockup).status_code == 404


def test_every_chat_string_exists_in_both_languages():
    import re
    from pathlib import Path
    public = Path(__file__).resolve().parent.parent / "public" / "js"
    source = (public / "i18n.js").read_text()
    et, en = source.split("\n  en: {", 1)
    used = set(re.findall(r't\("(mockup\.chat_[a-z_]+|mockup\.note_ai)"',
                          (public / "mockup" / "chat.js").read_text() + (public / "mockup" / "viewer.js").read_text()))
    used |= {"error.stale_version", "undo.mockup_ai_edited"}
    assert len(used) > 10
    assert [key for key in used if f'"{key}"' not in et] == []
    assert [key for key in used if f'"{key}"' not in en] == []
