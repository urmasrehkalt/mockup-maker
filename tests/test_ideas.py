"""#37: free text is classified; thoughts that are not plain refinements are kept as ideas the user decides on."""
import pytest

from app import conversation
from app.ai import providers
from tests.test_conversation import Recorder, last_assistant, turn
from tests.test_refinement import PRICING, SIGNUP, make_current, prepared


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


def state(client, project):
    return client.get(base(project)).json()


def say(client, project, text):
    return last_assistant(turn(client, project, kind="text", text=text).json())


@pytest.fixture
def story(client, project, ai):
    story = prepared(client, project, PRICING)
    make_current(client, project, story)  # the refinements step with the story chosen
    return story


def counts(client, project):
    current = state(client, project)
    return (len(current["stories"]), [(m["id"], m["version"]) for m in current["mockups"]],
            [[c["text"] for c in s["criteria"]] for s in current["stories"]])


def test_a_thought_for_later_is_kept_as_an_idea_and_changes_nothing(client, project, story):
    before = counts(client, project)
    message = say(client, project, "Hiljem võiks olla ka push-teavitus.")
    content = message["content"]
    assert content["intent"] == "later" and content["change"] is None
    card = content["idea"]
    assert card["recommended"] == "park" and card["text"] == "Hiljem võiks olla ka push-teavitus."
    assert counts(client, project) == before
    ideas = state(client, project)["ideas"]
    assert [i["text"] for i in ideas] == [card["text"]] and ideas[0]["id"] == card["idea_id"]
    assert ideas[0]["message_id"] == message["id"]


def test_a_plain_refinement_of_the_chosen_story_is_still_a_change_card(client, project, story):
    content = say(client, project, "Hinnas peab olema näha, kas see sisaldab käibemaksu.")["content"]
    assert content["intent"] == "refinement" and content["change"] and content["idea"] is None
    assert state(client, project)["ideas"] == []


def test_a_new_view_thought_gets_a_card_not_a_view(client, project, story):
    before = counts(client, project)
    content = say(client, project, "Klient tahab uut vaadet treenerite jaoks.")["content"]
    assert content["intent"] == "new_view" and content["idea"]["recommended"] == "new_view"
    assert content["new_view"] is None and counts(client, project) == before


def test_a_question_is_answered_without_a_card_or_an_idea(client, project, story):
    content = say(client, project, "Mitu lugu meil praegu on?")["content"]
    assert content["intent"] == "question" and content["idea"] is None and content["change"] is None
    assert state(client, project)["ideas"] == []


def test_a_refinement_without_a_chosen_story_is_parked(client, project, ai):
    client.patch(base(project), json={"step": "roles"})
    content = say(client, project, "Täpsusta, et hind sisaldab km.")["content"]
    assert content["intent"] == "refinement" and content["idea"]["recommended"] == "park"


def test_a_refinement_at_another_step_recommends_refining_the_story(client, project, ai):
    pricing = prepared(client, project, PRICING)
    turn(client, project, kind="focus", story_id=pricing["id"])
    client.patch(base(project), json={"step": "priorities"})
    content = say(client, project, "Täpsusta, et hind sisaldab km.")["content"]
    assert content["idea"]["recommended"] == "refine" and content["idea"]["story_key"] == pricing["key"]


def test_turning_an_idea_into_a_new_view_asks_for_the_view_and_closes_the_idea(client, project, story):
    card = say(client, project, "Klient tahab uut vaadet treenerite jaoks.")
    idea = card["content"]["idea"]
    stories_before = len(state(client, project)["stories"])
    result = turn(client, project, kind="idea", idea_id=idea["idea_id"], decision="new_view").json()
    view = last_assistant(result)["content"]["new_view"]
    assert view and view["story"]["action"]
    assert len(result["stories"]) == stories_before  # the view still waits for the user's confirmation
    assert result["ideas"] == []
    old = next(m for m in result["messages"] if m["id"] == card["id"])["content"]["idea"]
    assert old["decided"] == {"choice": "new_view"}
    user = [m for m in result["messages"] if m["role"] == "user"][-1]["content"]
    assert user["input"]["kind"] == "idea" and user["idea_text"] == idea["text"]


def test_the_ai_is_asked_about_the_idea_as_a_new_view(client, project, story, ai):
    idea = say(client, project, "Klient tahab uut vaadet treenerite jaoks.")["content"]["idea"]
    turn(client, project, kind="idea", idea_id=idea["idea_id"], decision="new_view")
    asked = ai.payloads[-1]["user_input"]
    assert asked == {"kind": "new_view", "text": idea["text"], "template": None}
    assert any("parked idea" in m["text"] for m in ai.payloads[-1]["recent_messages"])


def test_turning_an_idea_into_a_refinement_works_on_the_chosen_story(client, project, ai):
    pricing = prepared(client, project, PRICING)
    other = prepared(client, project, SIGNUP)
    turn(client, project, kind="focus", story_id=pricing["id"])
    client.patch(base(project), json={"step": "priorities"})
    idea = say(client, project, "Täpsusta, et hind sisaldab km.")["content"]["idea"]
    result = turn(client, project, kind="idea", idea_id=idea["idea_id"], decision="refine",
                  story_id=other["id"]).json()
    change = last_assistant(result)["content"]["change"]
    assert change["story_key"] == other["key"]
    assert result["project"]["step"] == "refinements" and result["project"]["current_story_id"] == other["id"]
    assert result["ideas"] == []


def test_a_refinement_needs_a_story(client, project, ai):
    client.patch(base(project), json={"step": "roles"})
    idea = say(client, project, "Täpsusta, et hind sisaldab km.")["content"]["idea"]
    response = turn(client, project, kind="idea", idea_id=idea["idea_id"], decision="refine")
    assert response.status_code == 422 and response.json()["detail"]["code"] == "no_story"
    assert len(state(client, project)["ideas"]) == 1  # nothing was closed


def test_parking_keeps_the_idea_and_closes_the_card(client, project, story):
    card = say(client, project, "Hiljem võiks olla ka push-teavitus.")
    idea = card["content"]["idea"]
    result = client.put(f"{base(project)}/ideas/{idea['idea_id']}/decision", json={"decision": "park"}).json()
    assert [i["id"] for i in result["ideas"]] == [idea["idea_id"]]
    shown = next(m for m in result["messages"] if m["id"] == card["id"])["content"]["idea"]
    assert shown["decided"] == {"choice": "park"}
    assert len(result["messages"]) == len(state(client, project)["messages"])  # no chat message was added


def test_dismissing_drops_the_idea_and_a_closed_idea_cannot_be_decided_again(client, project, story):
    idea = say(client, project, "Hiljem võiks olla ka push-teavitus.")["content"]["idea"]
    url = f"{base(project)}/ideas/{idea['idea_id']}/decision"
    assert client.put(url, json={"decision": "dismiss"}).json()["ideas"] == []
    assert client.put(url, json={"decision": "park"}).status_code == 409
    assert turn(client, project, kind="idea", idea_id=idea["idea_id"], decision="new_view").status_code == 409
    assert client.put(f"{base(project)}/ideas/999/decision", json={"decision": "park"}).status_code == 404


def test_an_idea_can_be_added_by_hand_and_survives_a_reload(client, project):
    added = client.post(f"{base(project)}/ideas", json={"text": "  Treenerite fotod avalehele  "})
    assert added.status_code == 201
    assert [i["text"] for i in added.json()["ideas"]] == ["Treenerite fotod avalehele"]
    assert [i["text"] for i in state(client, project)["ideas"]] == ["Treenerite fotod avalehele"]
    assert client.post(f"{base(project)}/ideas", json={"text": "  "}).status_code == 422
    assert client.post(f"{base(project)}/ideas", json={"text": "x", "extra": 1}).status_code == 422


def test_ideas_belong_to_their_project(client, project, story):
    idea = say(client, project, "Hiljem võiks olla ka push-teavitus.")["content"]["idea"]
    other = client.post("/api/projects", json={"name": "Teine"}).json()
    assert state(client, other)["ideas"] == []
    assert client.put(f"{base(other)}/ideas/{idea['idea_id']}/decision", json={"decision": "dismiss"}).status_code == 404
    assert turn(client, other, kind="idea", idea_id=idea["idea_id"], decision="new_view").status_code == 404
    assert len(state(client, project)["ideas"]) == 1


def test_the_markdown_export_lists_open_ideas_only(client, project):
    assert "Avatud ideed" not in client.get(f"{base(project)}/export.md").text
    for text in ("Push-teavitus", "Treenerite lehekülg", "Unustatud mõte"):
        client.post(f"{base(project)}/ideas", json={"text": text})
    kept = state(client, project)["ideas"]
    client.put(f"{base(project)}/ideas/{kept[2]['id']}/decision", json={"decision": "dismiss"})
    markdown = client.get(f"{base(project)}/export.md").text
    assert "## Avatud ideed" in markdown and "- Push-teavitus" in markdown and "- Treenerite lehekülg" in markdown
    assert "Unustatud mõte" not in markdown


# --- the rules the AI's answer must meet ----------------------------------

PAYLOAD = {"step": "refinements", "classify_text": True, "open_question": None, "current_story": "US-1",
           "clarifications_asked": 1, "backlog": [{"key": "US-1"}], "roles": [],
           "user_input": {"kind": "text", "text": "x"}, "current_story_detail": None}


def turn_of(**fields):
    base = {"message": "Selge.", "step": "refinements", "question": None, "roles": None,
            "next_steps": [{"label": "Edasi", "kind": "reply", "step": None}]}
    return conversation.Turn(**{**base, **fields})


def idea(recommended, reason="Sest."):
    return {"recommended": recommended, "reason": reason}


def test_free_text_needs_an_intent():
    assert "intent" in conversation.check_turn(turn_of(), PAYLOAD)
    assert conversation.check_turn(turn_of(intent="question"), PAYLOAD) is None
    assert conversation.check_turn(turn_of(intent="other"), PAYLOAD) is None


def test_nothing_is_classified_when_the_server_did_not_ask():
    no_ask = {**PAYLOAD, "classify_text": False}
    assert conversation.check_turn(turn_of(), no_ask) is None
    assert "only for" in conversation.check_turn(turn_of(intent="later", idea=idea("park")), no_ask)


def test_later_and_new_view_need_their_idea_card():
    assert "idea" in conversation.check_turn(turn_of(intent="later"), PAYLOAD)
    assert conversation.check_turn(turn_of(intent="later", idea=idea("park")), PAYLOAD) is None
    assert "not 'new_view'" in conversation.check_turn(turn_of(intent="later", idea=idea("new_view")), PAYLOAD)
    assert "not 'park'" in conversation.check_turn(turn_of(intent="new_view", idea=idea("park")), PAYLOAD)
    assert conversation.check_turn(turn_of(intent="new_view", idea=idea("new_view")), PAYLOAD) is None


def test_a_question_or_an_answer_takes_no_idea_card():
    assert "takes no idea card" in conversation.check_turn(turn_of(intent="question", idea=idea("park")), PAYLOAD)
    assert "open_question is null" in conversation.check_turn(turn_of(intent="answer"), PAYLOAD)
    answering = {**PAYLOAD, "open_question": "Kes?"}
    assert conversation.check_turn(turn_of(intent="answer"), answering) is None


def test_a_refinement_of_the_chosen_story_is_a_change_and_otherwise_an_idea():
    assert "`change`" in conversation.check_turn(turn_of(intent="refinement"), PAYLOAD)
    assert "`change`" in conversation.check_turn(turn_of(intent="refinement", idea=idea("refine")), PAYLOAD)
    elsewhere = {**PAYLOAD, "step": "priorities"}
    assert conversation.check_turn(turn_of(intent="refinement", idea=idea("refine")), elsewhere) is None
    assert "not 'park'" in conversation.check_turn(turn_of(intent="refinement", idea=idea("park")), elsewhere)
    nobody = {**PAYLOAD, "current_story": None}
    assert conversation.check_turn(turn_of(intent="refinement", idea=idea("park")), nobody) is None


def test_a_wrong_classification_is_sent_back_and_corrected(client, project, story, ai):
    calls = []

    def answer(payload):
        calls.append(payload)
        reply = conversation.mock_turn(payload)
        if len(calls) == 1:  # the first try forgets the classification
            reply = {**reply, "intent": None, "idea": None}
        return reply

    ai.override = answer
    content = say(client, project, "Hiljem võiks olla ka push-teavitus.")["content"]
    assert content["intent"] == "later" and content["idea"]
    assert len(calls) == 2 and "Set `intent`" in ai.prompts[-1]


def test_every_idea_string_exists_in_both_languages():
    import re
    from pathlib import Path
    public = Path(__file__).resolve().parent.parent / "public" / "js"
    source = (public / "i18n.js").read_text()
    et, en = source.split("\n  en: {", 1)
    used = set(re.findall(r't\("(ideas\.[a-z_]+)"', "".join(
        p.read_text() for p in public.rglob("*.js") if p.name != "i18n.js")))
    assert len(used) >= 8
    assert [k for k in used if f'"{k}"' not in et] == []
    assert [k for k in used if f'"{k}"' not in en] == []
