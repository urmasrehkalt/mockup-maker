import json

import pytest

from app import conversation, db
from app.ai import AIError, providers


class Recorder:
    """Answers like the mock provider, but keeps every payload the AI was sent."""

    name = "recorder"

    def __init__(self, override=None):
        self.payloads = []
        self.override = override

    async def run(self, request):
        payload = json.loads(request.prompt.split("INPUT (JSON):\n", 1)[1].split("\n\nYour previous")[0])
        self.payloads.append(payload)
        if self.override:
            answer = self.override(payload)
            if isinstance(answer, Exception):
                raise answer
            return answer
        return request.mock_answer()


@pytest.fixture
def ai(monkeypatch):
    recorder = Recorder()
    monkeypatch.setattr(providers, "get", lambda name=None: recorder)
    return recorder


@pytest.fixture
def project(client):
    return client.post("/api/projects", json={"name": "Spordiklubi"}).json()


def turn(client, project, **data):
    return client.post(f"/api/projects/{project['id']}/turn", json=data)


def last_assistant(state):
    return [m for m in state["messages"] if m["role"] == "assistant"][-1]


IDEA = "Spordiklubi tahab veebi, kus saab treeningutega tutvuda ja liikmeks astuda."


def test_first_free_text_gets_a_clarifying_question_with_options(client, project, ai):
    response = turn(client, project, kind="text", text=IDEA)
    assert response.status_code == 200, response.text
    state = response.json()
    assert [m["role"] for m in state["messages"]] == ["user", "assistant"]
    reply = last_assistant(state)["content"]
    assert reply["question"]["multi_select"] is True
    assert len(reply["question"]["options"]) >= 2
    assert 1 <= len(reply["next_steps"]) <= 4
    assert ai.payloads[0]["idea"] == IDEA
    assert ai.payloads[0]["step"] == "idea"


def test_answer_with_options_is_stored_and_sent_to_the_ai(client, project, ai):
    state = turn(client, project, kind="text", text=IDEA).json()
    question = last_assistant(state)
    state = turn(client, project, kind="answer", message_id=question["id"],
                 selected=["Külastaja", "Administraator"], other="Treener").json()

    answered = next(m for m in state["messages"] if m["id"] == question["id"])
    assert answered["content"]["question"]["answer"] == {
        "selected": ["Külastaja", "Administraator"], "other": "Treener", "skipped": False}
    sent = ai.payloads[-1]
    assert sent["clarifications"] == [{"question": "Kes on rakenduse kasutajad?",
                                       "answer": "Külastaja; Administraator; Treener"}]
    assert sent["open_question"] is None


def test_skipped_question_is_recorded_as_skipped(client, project, ai):
    question = last_assistant(turn(client, project, kind="text", text=IDEA).json())
    turn(client, project, kind="answer", message_id=question["id"], skipped=True)
    assert ai.payloads[-1]["clarifications"][0]["answer"] is None
    assert "(skipped the question)" in ai.payloads[-1]["recent_messages"][-1]["text"]


def test_answer_must_choose_something_and_only_offered_options(client, project, ai):
    question = last_assistant(turn(client, project, kind="text", text=IDEA).json())
    assert turn(client, project, kind="answer", message_id=question["id"]).status_code == 422
    assert turn(client, project, kind="answer", message_id=question["id"],
                selected=["Häkker"]).status_code == 422


def test_question_cannot_be_answered_twice(client, project, ai):
    question = last_assistant(turn(client, project, kind="text", text=IDEA).json())
    turn(client, project, kind="answer", message_id=question["id"], skipped=True)
    again = turn(client, project, kind="answer", message_id=question["id"], skipped=True)
    assert again.status_code == 409


def test_free_text_answering_an_open_question_is_interpreted(client, project, ai):
    question = last_assistant(turn(client, project, kind="text", text=IDEA).json())
    state = turn(client, project, kind="text", text="Külastajad ja klubi liikmed").json()
    assert ai.payloads[-1]["open_question"] == "Kes on rakenduse kasutajad?"
    answered = next(m for m in state["messages"] if m["id"] == question["id"])
    assert answered["content"]["question"]["answer"]["other"] == "Külastajad ja klubi liikmed"
    assert turn(client, project, kind="retry").status_code == 200
    assert ai.payloads[-1]["clarifications"][0]["answer"] == "Külastajad ja klubi liikmed"


def test_at_most_three_clarifying_questions(client, project, monkeypatch):
    def always_ask(payload):
        return {"message": "Veel üks küsimus?", "step": "idea", "interpreted_answer": None,
                "roles": None,
                "question": {"text": f"Küsimus {payload['clarifications_asked'] + 1}?",
                             "multi_select": False, "options": ["Jah", "Ei"]},
                "next_steps": [{"label": "Edasi", "kind": "reply", "step": None}]}
    recorder = Recorder(always_ask)
    monkeypatch.setattr(providers, "get", lambda name=None: recorder)

    state = turn(client, project, kind="text", text=IDEA).json()
    for _ in range(4):
        question = last_assistant(state)["content"]["question"]
        if not question:
            break
        state = turn(client, project, kind="answer", message_id=last_assistant(state)["id"],
                     selected=["Jah"]).json()
    asked = [m for m in state["messages"] if m["role"] == "assistant" and m["content"]["question"]]
    assert len(asked) == 3


def test_roles_are_proposed_then_confirmed_by_the_user(client, project, ai):
    question = last_assistant(turn(client, project, kind="text", text=IDEA).json())
    state = turn(client, project, kind="answer", message_id=question["id"], selected=["Külastaja"]).json()
    state = turn(client, project, kind="answer", message_id=last_assistant(state)["id"],
                 selected=["Jah, veebis"]).json()
    proposal = last_assistant(state)
    assert state["project"]["step"] == "roles"
    assert len(proposal["content"]["roles"]) >= 2
    assert state["roles"] == []  # proposed, not stored

    chosen = [{"name": "Külastaja"}, {"name": "Administraator"}, {"name": "Treener",
                                                                  "description": "Lisatud käsitsi"}]
    state = turn(client, project, kind="roles", message_id=proposal["id"], roles=chosen).json()
    assert [r["name"] for r in state["roles"]] == ["Külastaja", "Administraator", "Treener"]
    confirmed = next(m for m in state["messages"] if m["id"] == proposal["id"])
    assert confirmed["content"]["roles_confirmed"] == ["Külastaja", "Administraator", "Treener"]
    assert [r["name"] for r in ai.payloads[-1]["roles"]] == ["Külastaja", "Administraator", "Treener"]
    assert state["project"]["step"] == "stories"


def test_duplicate_role_names_are_stored_once(client, project, ai):
    state = turn(client, project, kind="roles",
                 roles=[{"name": "Külastaja"}, {"name": "külastaja "}, {"name": "Liige"}]).json()
    assert [r["name"] for r in state["roles"]] == ["Külastaja", "Liige"]


def test_ai_sees_manual_state_changes_not_just_history(client, project, ai, db_path):
    turn(client, project, kind="roles", roles=[{"name": "Külastaja"}])
    conn = db.connect(db_path)
    with conn:
        conn.execute("UPDATE roles SET name = 'Klubi liige' WHERE project_id = ?", (project["id"],))
    conn.close()
    turn(client, project, kind="text", text="Jätkame")
    assert ai.payloads[-1]["roles"] == [{"name": "Klubi liige", "description": ""}]


def test_next_step_choice_can_move_the_process(client, project, ai):
    turn(client, project, kind="next", label="Liigu rollide juurde", step="roles")
    assert ai.payloads[-1]["step"] == "roles"
    assert ai.payloads[-1]["recent_messages"][-1]["text"] == "Chose: Liigu rollide juurde"


def test_every_reply_ends_with_next_steps_and_bad_answers_are_retried(client, project, monkeypatch):
    answers = [
        {"message": "x", "step": "idea", "interpreted_answer": None, "question": None,
         "roles": None, "next_steps": []},
        {"message": "Hea küll.", "step": "idea", "interpreted_answer": None, "question": None,
         "roles": None, "next_steps": [{"label": "Edasi", "kind": "reply", "step": None}]},
    ]
    recorder = Recorder(lambda payload: answers.pop(0))
    monkeypatch.setattr(providers, "get", lambda name=None: recorder)
    state = turn(client, project, kind="text", text=IDEA).json()
    assert len(recorder.payloads) == 2
    assert last_assistant(state)["content"]["next_steps"][0]["label"] == "Edasi"


def test_turn_model_rejects_question_and_roles_together_and_no_reply():
    base = {"message": "x", "step": "roles", "interpreted_answer": None,
            "question": {"text": "q", "multi_select": False, "options": ["a", "b"]},
            "roles": [{"name": "A", "description": "", "recommended": True},
                      {"name": "B", "description": "", "recommended": False}],
            "next_steps": [{"label": "Edasi", "kind": "reply", "step": None}]}
    with pytest.raises(ValueError):
        conversation.Turn.model_validate(base)
    with pytest.raises(ValueError):
        conversation.Turn.model_validate({**base, "roles": None, "next_steps": [
            {"label": "Lõpp", "kind": "end_meeting", "step": None}]})


def test_ai_failure_keeps_the_users_decision_and_retry_recovers(client, project, monkeypatch):
    failing = Recorder(lambda payload: AIError("ai_unavailable", "Codex exited with status 1."))
    monkeypatch.setattr(providers, "get", lambda name=None: failing)
    response = turn(client, project, kind="roles", roles=[{"name": "Külastaja"}])
    assert response.status_code == 503
    assert response.json()["error"]["code"] == "ai_unavailable"

    state = client.get(f"/api/projects/{project['id']}").json()
    assert [r["name"] for r in state["roles"]] == ["Külastaja"]
    assert [m["role"] for m in state["messages"]] == ["user"]

    working = Recorder()
    monkeypatch.setattr(providers, "get", lambda name=None: working)
    state = turn(client, project, kind="retry").json()
    assert [m["role"] for m in state["messages"]] == ["user", "assistant"]


def test_ai_off_still_stores_the_decision(client, project, monkeypatch):
    monkeypatch.setenv("AI_PROVIDER", "off")
    response = turn(client, project, kind="roles", roles=[{"name": "Külastaja"}])
    assert response.status_code == 503
    assert response.json()["error"]["code"] == "ai_disabled"
    assert client.get(f"/api/projects/{project['id']}").json()["roles"] == [
        {"name": "Külastaja", "description": ""}]


def test_unknown_input_kind_and_project_are_rejected(client, project, ai):
    assert turn(client, project, kind="hack").status_code == 422
    assert client.post("/api/projects/999/turn", json={"kind": "retry"}).status_code == 404


def test_first_idea_without_a_question_is_sent_back(client, project, monkeypatch):
    roles_first = {"message": "Selge.", "step": "roles", "interpreted_answer": None,
                   "question": None,
                   "roles": [{"name": "Külastaja", "description": "", "recommended": True},
                             {"name": "Liige", "description": "", "recommended": True}],
                   "next_steps": [{"label": "Edasi", "kind": "reply", "step": None}]}
    answers = [roles_first, None]
    recorder = Recorder(lambda payload: answers.pop(0) or conversation.mock_turn(payload))
    monkeypatch.setattr(providers, "get", lambda name=None: recorder)
    state = turn(client, project, kind="text", text=IDEA).json()
    assert len(recorder.payloads) == 2
    assert last_assistant(state)["content"]["question"] is not None


def test_check_turn_rules():
    base = {"message": "x", "step": "idea", "interpreted_answer": None, "roles": None,
            "question": {"text": "q", "multi_select": False, "options": ["a", "b"]},
            "next_steps": [{"label": "Edasi", "kind": "reply", "step": None}]}
    asking = conversation.Turn.model_validate(base)
    silent = conversation.Turn.model_validate({**base, "question": None})
    first = {"step": "idea", "user_input": {"kind": "text"}, "clarifications_asked": 0}
    assert conversation.check_turn(asking, first) is None
    assert "clarifying question" in conversation.check_turn(silent, first)
    assert conversation.check_turn(silent, {**first, "user_input": {"kind": "next"}}) is None
    assert "maximum" in conversation.check_turn(asking, {**first, "clarifications_asked": 3})


def test_fact_stated_in_free_text_is_kept_as_project_state(client, project, monkeypatch):
    def noting(payload):
        answer = conversation.mock_turn(payload)
        if payload["user_input"].get("text") == "Liikmetasu makstakse kaardiga.":
            answer["noted_fact"] = "Liikmetasu makstakse veebis kaardiga."
        if payload["user_input"].get("text") == IDEA:
            answer["noted_fact"] = "Spordiklubi veeb"  # must not duplicate the idea
        return answer
    recorder = Recorder(noting)
    monkeypatch.setattr(providers, "get", lambda name=None: recorder)
    turn(client, project, kind="text", text=IDEA)
    turn(client, project, kind="next", label="Edasi")
    turn(client, project, kind="text", text="Liikmetasu makstakse kaardiga.")
    turn(client, project, kind="retry")
    notes = [c for c in recorder.payloads[-1]["clarifications"] if c["question"] == conversation.NOTE]
    assert notes == [{"question": conversation.NOTE, "answer": "Liikmetasu makstakse veebis kaardiga."}]
