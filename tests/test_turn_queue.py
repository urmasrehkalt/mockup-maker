"""#36: inputs queue up; a project's turns run one at a time, each on the state the last left."""
import asyncio
import threading
import time

import pytest
from fastapi.testclient import TestClient

from app import db, mockups, turns
from app.ai import AIError, providers
from tests.test_refinement import PRICING, prepared, refine
from tests.test_conversation import IDEA, last_assistant


class Gated:
    """A provider whose answers wait for the test: records every payload, counts how many run at once."""

    name = "gated"

    def __init__(self):
        self.gate = threading.Event()
        self.started = threading.Event()
        self.payloads = []
        self.running = 0
        self.most_running = 0
        self.hold = lambda payload: True
        self.fail = lambda payload: None

    async def run(self, request):
        import json
        payload = json.loads(request.prompt.split("INPUT (JSON):\n", 1)[1].split("\n\nYour previous")[0])
        self.payloads.append(payload)
        self.running += 1
        self.most_running = max(self.most_running, self.running)
        self.started.set()
        try:
            if self.hold(payload):
                await asyncio.get_running_loop().run_in_executor(None, self.gate.wait, 10)
            error = self.fail(payload)
            if error:
                raise error
            return request.mock_answer()
        finally:
            self.running -= 1


@pytest.fixture
def ai(monkeypatch):
    provider = Gated()
    provider.gate.set()  # open unless a test closes it
    monkeypatch.setattr(providers, "get", lambda name=None: provider)
    return provider


@pytest.fixture
def project(client):
    return client.post("/api/projects", json={"name": "A"}).json()


def base(project):
    return f"/api/projects/{project['id']}"


def post(client, project, **data):
    return client.post(f"{base(project)}/turns", json=data)


def state(client, project):
    return client.get(base(project)).json()


def wait_idle(client, project, timeout=5):
    deadline = time.time() + timeout
    while time.time() < deadline:
        current = state(client, project)
        if not [q for q in current["queue"] if q["status"] != "failed"]:
            return current
        time.sleep(0.02)
    raise AssertionError(f"the queue did not drain: {state(client, project)['queue']}")


def assistants(current):
    return [m for m in current["messages"] if m["role"] == "assistant"]


def test_a_second_input_is_accepted_while_the_first_runs_and_shown_as_queued(client, project, ai):
    ai.gate.clear()
    first = post(client, project, kind="text", text=IDEA)
    assert first.status_code == 202
    assert ai.started.wait(5)
    second = post(client, project, kind="text", text="Klient tahab ka treenerite lehte.")
    assert second.status_code == 202
    queue = second.json()["queue"]
    assert [q["status"] for q in queue] == ["running", "queued"]
    assert queue[1]["input"]["text"] == "Klient tahab ka treenerite lehte."
    assert state(client, project)["queue"] == queue  # the queue is part of the stored state
    ai.gate.set()
    done = wait_idle(client, project)
    assert len(assistants(done)) == 2 and done["queue"] == []


def test_turns_run_in_the_order_sent_and_one_at_a_time(client, project, ai):
    ai.gate.clear()
    texts = [IDEA, "Teine mõte.", "Kolmas mõte."]
    for text in texts:
        post(client, project, kind="text", text=text)
    ai.gate.set()
    wait_idle(client, project)
    assert [p["user_input"]["text"] for p in ai.payloads] == texts
    assert ai.most_running == 1


def test_the_second_turn_sees_the_state_the_first_left(client, project, ai):
    ai.gate.clear()
    post(client, project, kind="text", text=IDEA)
    assert ai.started.wait(5)
    post(client, project, kind="text", text="Kliendil on veel üks mõte.")
    ai.gate.set()
    wait_idle(client, project)
    first, second = ai.payloads
    assert first["open_question"] is None and first["clarifications_asked"] == 0
    # The first turn asked a question; the payload of the second was built after that.
    assert second["clarifications_asked"] == 1 and second["open_question"]
    assert any(m["role"] == "assistant" for m in second["recent_messages"])


def test_projects_do_not_wait_for_each_other(client, project, ai):
    other = client.post("/api/projects", json={"name": "B"}).json()
    ai.hold = lambda payload: payload["project"]["name"] == "A"
    ai.gate.clear()
    post(client, project, kind="text", text=IDEA)
    assert ai.started.wait(5)
    post(client, other, kind="text", text=IDEA)
    assert state(client, other) and wait_idle(client, other)["queue"] == []
    assert len(assistants(state(client, other))) == 1
    assert [q["status"] for q in state(client, project)["queue"]] == ["running"]
    ai.gate.set()
    wait_idle(client, project)


def test_a_failed_turn_does_not_block_the_next_and_can_be_retried(client, project, ai):
    calls = []
    ai.fail = lambda payload: (calls.append(1) or AIError("ai_unavailable", "Codex is down")) if len(calls) == 0 else None
    post(client, project, kind="text", text=IDEA)
    post(client, project, kind="text", text="Teine mõte.")
    deadline = time.time() + 5
    while time.time() < deadline and len(assistants(state(client, project))) < 1:
        time.sleep(0.02)
    current = state(client, project)
    failed = [q for q in current["queue"] if q["status"] == "failed"]
    assert len(failed) == 1 and failed[0]["error_code"] == "ai_unavailable"
    assert failed[0]["input"]["text"] == IDEA
    assert len(assistants(current)) == 1  # the second one was answered
    # The user's input was kept even though the AI failed.
    assert [m["content"]["input"]["text"] for m in current["messages"] if m["role"] == "user"][0] == IDEA

    again = client.post(f"{base(project)}/turns/{failed[0]['id']}/retry")
    assert again.status_code == 202
    done = wait_idle(client, project)
    assert done["queue"] == [] and len(assistants(done)) == 2


def test_only_an_ai_failure_can_be_retried_and_a_failed_input_can_be_removed(client, project, ai):
    post(client, project, kind="answer", message_id=999, selected=["x"])  # no such message
    time.sleep(0.3)
    failed = state(client, project)["queue"]
    assert [q["status"] for q in failed] == ["failed"] and failed[0]["error_code"] == "rejected"
    assert client.post(f"{base(project)}/turns/{failed[0]['id']}/retry").status_code == 409
    assert client.delete(f"{base(project)}/turns/{failed[0]['id']}").json()["queue"] == []
    assert client.delete(f"{base(project)}/turns/{failed[0]['id']}").status_code == 404


def test_a_waiting_input_can_be_removed_but_a_running_one_cannot(client, project, ai):
    ai.gate.clear()
    post(client, project, kind="text", text=IDEA)
    assert ai.started.wait(5)
    queue = post(client, project, kind="text", text="Teine mõte.").json()["queue"]
    running, waiting = queue
    assert client.delete(f"{base(project)}/turns/{running['id']}").status_code == 409
    assert client.delete(f"{base(project)}/turns/{waiting['id']}").json()["queue"][0]["id"] == running["id"]
    ai.gate.set()
    done = wait_idle(client, project)
    assert len(assistants(done)) == 1


def test_too_many_waiting_inputs_are_refused(client, project, ai, monkeypatch):
    monkeypatch.setattr(turns, "MAX_QUEUED", 2)
    ai.gate.clear()
    post(client, project, kind="text", text=IDEA)
    assert ai.started.wait(5)
    assert post(client, project, kind="text", text="2").status_code == 202
    assert post(client, project, kind="text", text="3").status_code == 202
    refused = post(client, project, kind="text", text="4")
    assert refused.status_code == 429 and refused.json()["detail"]["code"] == "queue_full"
    ai.gate.set()
    wait_idle(client, project)


def test_after_a_restart_a_running_turn_is_failed_and_the_waiting_ones_run(client, project, ai):
    from app.main import app
    conn = db.connect()
    with conn:
        for status, text in (("running", "Jäi pooleli"), ("queued", "Ootab")):
            conn.execute("INSERT INTO turns (project_id, input, status, created_at) VALUES (?, ?, ?, ?)",
                         (project["id"], '{"kind": "text", "text": "%s"}' % text, status, db.now()))
    conn.close()
    with TestClient(app) as restarted:
        done = wait_idle(restarted, project)
        failed = [q for q in done["queue"] if q["status"] == "failed"]
        assert [q["error_code"] for q in failed] == ["interrupted"]
        assert all(q["status"] != "running" for q in done["queue"])
        assert [m["content"]["input"]["text"] for m in done["messages"] if m["role"] == "user"] == ["Ootab"]


def test_the_synchronous_turn_goes_through_the_same_queue(client, project, ai):
    ai.gate.clear()
    post(client, project, kind="text", text=IDEA)
    assert ai.started.wait(5)
    result = {}
    thread = threading.Thread(target=lambda: result.update(
        response=client.post(f"{base(project)}/turn", json={"kind": "text", "text": "Teine."})))
    thread.start()
    time.sleep(0.2)
    assert thread.is_alive()  # it waits behind the first one
    ai.gate.set()
    thread.join(5)
    assert result["response"].status_code == 200 and len(assistants(result["response"].json())) == 2
    assert result["response"].json()["queue"] == []


def test_the_synchronous_turn_still_fails_as_one_request(client, project, ai):
    ai.fail = lambda payload: AIError("ai_invalid_answer", "bad shape")
    response = client.post(f"{base(project)}/turn", json={"kind": "text", "text": IDEA})
    assert response.status_code == 502
    current = state(client, project)
    assert current["queue"] == []  # delivered as the response, not left in the queue
    assert [m["role"] for m in current["messages"]] == ["user"]  # the input is kept


# --- cards made for an older state ---------------------------------------

def test_a_change_card_is_refused_after_the_mockup_moved_on(client, project, ai):
    story = prepared(client, project, PRICING)
    message = refine(client, project, story)
    mockup = state(client, project)["mockups"][0]
    edited = dict(mockup["tree"], title="Käsitsi muudetud")
    client.post(f"{base(project)}/mockups/{mockup['id']}/versions", json={"tree": edited})
    before = state(client, project)
    response = client.post(f"{base(project)}/turn", json={"kind": "change", "message_id": message["id"],
                                                          "decision": "apply"})
    assert response.status_code == 409 and response.json()["detail"]["code"] == "stale_card"
    after = state(client, project)
    assert after["mockups"] == before["mockups"] and after["stories"] == before["stories"]
    card = next(m for m in after["messages"] if m["id"] == message["id"])["content"]["change"]
    assert "decided" not in card


def test_a_change_card_is_refused_after_another_change_was_applied(client, project, ai):
    story = prepared(client, project, PRICING)
    first = refine(client, project, story)
    second = refine(client, project, story)  # made from the same state
    assert client.post(f"{base(project)}/turn", json={"kind": "change", "message_id": first["id"],
                                                      "decision": "apply"}).status_code == 200
    response = client.post(f"{base(project)}/turn", json={"kind": "change", "message_id": second["id"],
                                                          "decision": "apply"})
    assert response.status_code == 409 and response.json()["detail"]["code"] == "stale_card"


def test_a_fresh_change_card_still_applies_and_discarding_a_stale_one_is_allowed(client, project, ai):
    story = prepared(client, project, PRICING)
    message = refine(client, project, story)
    mockup = state(client, project)["mockups"][0]
    client.post(f"{base(project)}/mockups/{mockup['id']}/versions",
                json={"tree": dict(mockup["tree"], title="Käsitsi muudetud")})
    discarded = client.post(f"{base(project)}/turn", json={"kind": "change", "message_id": message["id"],
                                                           "decision": "discard"})
    assert discarded.status_code == 200
    fresh = refine(client, project, story)
    applied = client.post(f"{base(project)}/turn", json={"kind": "change", "message_id": fresh["id"],
                                                         "decision": "apply"})
    assert applied.status_code == 200


def test_a_proposal_is_refused_after_the_mockup_moved_on(client, project, ai):
    story = client.post(f"{base(project)}/stories", json={
        "role_name": "Külastaja", "role_phrase": "Külastajana", "action": "näha liikmepakette ja hindu",
        "benefit": "valida endale sobiv pakett"}).json()
    client.post(f"{base(project)}/mockups", json={"template": "pricing", "story_id": story["id"]})
    proposal = last_assistant(client.post(f"{base(project)}/turn", json={"kind": "focus", "story_id": story["id"]}).json())
    assert proposal["content"]["proposal"]["base"]["version"] == 1
    mockup = state(client, project)["mockups"][0]
    client.post(f"{base(project)}/mockups/{mockup['id']}/versions",
                json={"tree": dict(mockup["tree"], title="Käsitsi muudetud")})
    response = client.post(f"{base(project)}/turn", json={
        "kind": "criteria", "message_id": proposal["id"],
        "items": [{"index": i} for i in range(len(proposal["content"]["proposal"]["criteria"]))]})
    assert response.status_code == 409 and response.json()["detail"]["code"] == "stale_card"


def test_every_queue_string_exists_in_both_languages():
    from pathlib import Path
    source = (Path(__file__).resolve().parent.parent / "public" / "js" / "i18n.js").read_text()
    et, en = source.split("\n  en: {", 1)
    keys = ["chat.queued", "chat.remove", "error.turn_failed", "error.interrupted", "error.stale_card",
            "error.rejected", "error.queue_full", "error.turn_running", "error.not_retryable"]
    assert [k for k in keys if f'"{k}"' not in et] == []
    assert [k for k in keys if f'"{k}"' not in en] == []
