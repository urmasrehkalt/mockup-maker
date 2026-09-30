import pytest

from app import conversation
from app.ai import providers
from tests.test_conversation import Recorder, last_assistant, turn

PRICING = {"role_name": "Külastaja", "role_phrase": "Külastajana",
           "action": "näha liikmepakette ja hindu", "benefit": "valida endale sobiv pakett"}
SIGNUP = {"role_name": "Külastaja", "role_phrase": "Külastajana",
          "action": "luua endale konto", "benefit": "saaksin liituda"}
REFINEMENT = "Klient ütleb, et paketi hinnas peab olema näha, kas see sisaldab käibemaksu."


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


def prepared(client, project, story_json):
    """A story with accepted criteria and a mockup, as after #9."""
    story = client.post(f"{base(project)}/stories", json=story_json).json()
    message = last_assistant(turn(client, project, kind="focus", story_id=story["id"]).json())
    count = len(message["content"]["proposal"]["criteria"])
    turn(client, project, kind="criteria", message_id=message["id"],
         items=[{"index": i} for i in range(count)])
    return next(s for s in state(client, project)["stories"] if s["id"] == story["id"])


def make_current(client, project, story):
    """Choose the story again and continue at the refinements step, as after deciding criteria."""
    turn(client, project, kind="focus", story_id=story["id"])
    client.patch(base(project), json={"step": "refinements"})


def refine(client, project, story):
    make_current(client, project, story)
    return last_assistant(turn(client, project, kind="text", text=REFINEMENT).json())


def snapshot(client, project, story_id):
    current = state(client, project)
    story = next(s for s in current["stories"] if s["id"] == story_id)
    tree = [m for m in current["mockups"] if m["id"] in story["mockup_ids"]]
    return story, [(m["id"], m["version"], m["tree"]) for m in tree]


def test_refinement_becomes_a_change_with_a_before_snapshot(client, project, ai):
    pricing = prepared(client, project, PRICING)
    message = refine(client, project, pricing)
    change = message["content"]["change"]
    assert change["story_key"] == pricing["key"]
    assert change["summary"]
    assert change["before"]["criteria"] == [{"text": c["text"], "component_id": c["component_id"]}
                                            for c in pricing["criteria"]]
    assert change["before"]["mockup_id"] == pricing["mockup_ids"][0]
    assert len(change["criteria"]) == len(pricing["criteria"]) + 1
    assert "refinement-note" in str(change["mockup"])
    assert "decided" not in change


def test_applying_changes_story_and_mockup_but_no_other_story(client, project, ai):
    other = prepared(client, project, SIGNUP)
    pricing = prepared(client, project, PRICING)
    other_before = snapshot(client, project, other["id"])

    message = refine(client, project, pricing)
    current = turn(client, project, kind="change", message_id=message["id"], decision="apply").json()

    story, mockup = snapshot(client, project, pricing["id"])
    assert story["criteria"][-1]["text"] == "Hinna all on märge „sh km“."
    assert story["criteria"][-1]["component_id"] == "refinement-note"
    assert [c["id"] for c in story["criteria"][:-1]] == [c["id"] for c in pricing["criteria"]]
    assert mockup[0][1] == 2 and "refinement-note" in str(mockup[0][2])
    assert snapshot(client, project, other["id"]) == other_before
    card = next(m for m in current["messages"] if m["id"] == message["id"])["content"]["change"]
    assert card["decided"] == {"applied": True, "mockup_id": mockup[0][0], "version": 2}


def test_discarding_changes_nothing(client, project, ai):
    pricing = prepared(client, project, PRICING)
    before = snapshot(client, project, pricing["id"])
    message = refine(client, project, pricing)
    turn(client, project, kind="change", message_id=message["id"], decision="discard")
    after_story, after_mockup = snapshot(client, project, pricing["id"])
    assert after_mockup == before[1]
    assert [c["text"] for c in after_story["criteria"]] == [c["text"] for c in before[0]["criteria"]]


def test_applying_with_the_users_edits(client, project, ai):
    pricing = prepared(client, project, PRICING)
    message = refine(client, project, pricing)
    edits = {"wording": {"role_phrase": "Külastajana", "action": "näha liikmepakette ja hindu koos käibemaksuga",
                         "benefit": "teada, kui palju ma tegelikult maksan"},
             "criteria": ["Iga paketi juures on kuutasu eurodes.", "Hinna all on märge „sh km“ või „km-ta“."]}
    turn(client, project, kind="change", message_id=message["id"], decision="apply", edits=edits)
    story, _ = snapshot(client, project, pricing["id"])
    assert story["action"] == edits["wording"]["action"]
    assert story["title"].endswith("et teada, kui palju ma tegelikult maksan.")
    assert [c["text"] for c in story["criteria"]] == edits["criteria"]
    assert story["criteria"][1]["origin"] == "manual"


def test_change_is_decided_once_and_only_on_a_change_card(client, project, ai):
    pricing = prepared(client, project, PRICING)
    message = refine(client, project, pricing)
    assert turn(client, project, kind="change", message_id=message["id"], decision="discard").status_code == 200
    assert turn(client, project, kind="change", message_id=message["id"], decision="apply").status_code == 409
    first = state(client, project)["messages"][0]
    assert turn(client, project, kind="change", message_id=first["id"], decision="apply").status_code == 400


def test_a_shared_mockup_is_copied_so_the_other_story_keeps_its_view(client, project, ai):
    other = client.post(f"{base(project)}/stories", json=SIGNUP).json()
    pricing = prepared(client, project, PRICING)
    shared = pricing["mockup_ids"][0]
    client.put(f"{base(project)}/stories/{other['id']}/mockups/{shared}")
    other_before = snapshot(client, project, other["id"])

    message = refine(client, project, pricing)
    turn(client, project, kind="change", message_id=message["id"], decision="apply")

    assert snapshot(client, project, other["id"]) == other_before
    story, mockup = snapshot(client, project, pricing["id"])
    assert story["mockup_ids"] != [shared] and "refinement-note" in str(mockup[0][2])


def test_applying_can_be_undone_including_the_mockup(client, project, ai):
    pricing = prepared(client, project, PRICING)
    before = snapshot(client, project, pricing["id"])
    message = refine(client, project, pricing)
    turn(client, project, kind="change", message_id=message["id"], decision="apply")
    assert state(client, project)["undo"]["action"] == "story_refined"
    client.post(f"{base(project)}/undo")
    story, mockup = snapshot(client, project, pricing["id"])
    assert mockup == before[1]
    assert [c["text"] for c in story["criteria"]] == [c["text"] for c in before[0]["criteria"]]


def test_a_change_aimed_at_another_story_is_never_stored(client, project, monkeypatch):
    recorder = Recorder()
    monkeypatch.setattr(providers, "get", lambda name=None: recorder)
    other = prepared(client, project, SIGNUP)
    pricing = prepared(client, project, PRICING)
    make_current(client, project, pricing)
    other_before = snapshot(client, project, other["id"])

    def wrong_story(payload):
        answer = conversation.mock_turn(payload)
        if answer.get("change"):
            answer["change"]["story_key"] = other["key"]
        return answer
    recorder.override = wrong_story
    message = last_assistant(turn(client, project, kind="text", text=REFINEMENT).json())
    assert other["key"] in recorder.prompts[-1] and "only touch the chosen story" in recorder.prompts[-1]
    assert message["content"]["change"] is None
    assert snapshot(client, project, other["id"]) == other_before


def test_other_affected_stories_are_offered_separately(client, project, ai):
    other = prepared(client, project, SIGNUP)
    pricing = prepared(client, project, PRICING)
    make_current(client, project, pricing)

    def with_other(payload):
        answer = conversation.mock_turn(payload)
        if answer.get("change") and payload["user_input"]["kind"] == "text":
            answer["change"]["other_stories"] = [{"story_key": other["key"], "reason": "Konto vormis on ka hind."}]
        return answer
    ai.override = with_other
    message = last_assistant(turn(client, project, kind="text", text=REFINEMENT).json())
    assert message["content"]["change"]["other_stories"][0]["story_key"] == other["key"]

    current = turn(client, project, kind="refine", story_id=other["id"], text=REFINEMENT).json()
    assert current["project"]["current_story_id"] == other["id"]
    assert last_assistant(current)["content"]["change"]["story_key"] == other["key"]


def _change(**overrides):
    data = {"story_key": "US-1", "summary": "Lisandub märge.", "wording": None,
            "criteria": [{"text": "Hinna all on märge „sh km“.", "component_id": "t"}],
            "mockup": {"title": "V", "components": [{"id": "t", "type": "note", "text": "sh km"}]},
            "other_stories": []}
    data.update(overrides)
    return conversation.Change.model_validate(data)


def _turn_with(change):
    return conversation.Turn.model_validate({
        "message": "Muudatus.", "step": "refinements", "question": None, "roles": None, "stories": None,
        "priority": None, "proposal": None, "change": change.model_dump() if change else None,
        "next_steps": [{"label": "Edasi", "kind": "reply", "step": None}]})


PAYLOAD = {"step": "refinements", "user_input": {"kind": "text"}, "clarifications_asked": 1,
           "backlog": [{"key": "US-1"}, {"key": "US-2"}], "roles": [], "current_story": "US-1",
           "current_story_detail": {"mockup": None}}


def test_change_rules():
    assert conversation.check_turn(_turn_with(_change()), PAYLOAD) is None
    assert "only touch" in conversation.check_turn(_turn_with(_change(story_key="US-2")), PAYLOAD)
    assert "US-9" in conversation.check_turn(_turn_with(_change(other_stories=[
        {"story_key": "US-9", "reason": "x"}])), PAYLOAD)
    assert "not in the mockup" in conversation.check_turn(_turn_with(_change(criteria=[
        {"text": "Lehel on märge.", "component_id": "nope"}])), PAYLOAD)
    assert "yes or no" in conversation.check_turn(_turn_with(_change(criteria=[
        {"text": "Hind on selgelt näha.", "component_id": "t"}])), PAYLOAD)
    refine = {**PAYLOAD, "user_input": {"kind": "refine"}}
    assert "same turn" in conversation.check_turn(_turn_with(None), refine)
    with pytest.raises(ValueError):
        _change(wording=None, criteria=None, mockup=None)


def test_a_refinement_that_only_affects_other_stories(client, project, monkeypatch):
    recorder = Recorder()
    monkeypatch.setattr(providers, "get", lambda name=None: recorder)
    other = prepared(client, project, SIGNUP)
    pricing = prepared(client, project, PRICING)
    make_current(client, project, other)
    other_before = snapshot(client, project, other["id"])

    def elsewhere(payload):
        answer = conversation.mock_turn(payload)
        if answer.get("change") and payload["user_input"]["kind"] == "text":
            answer["change"].update(wording=None, criteria=None, mockup=None, other_stories=[
                {"story_key": pricing["key"], "reason": "Hinda näidatakse pakettide vaates."}])
        return answer
    recorder.override = elsewhere
    message = last_assistant(turn(client, project, kind="text", text=REFINEMENT).json())
    change = message["content"]["change"]
    assert change["story_key"] == other["key"] and change["other_stories"][0]["story_key"] == pricing["key"]
    assert turn(client, project, kind="change", message_id=message["id"], decision="apply").status_code == 409
    assert turn(client, project, kind="change", message_id=message["id"], decision="discard").status_code == 200
    assert snapshot(client, project, other["id"]) == other_before
