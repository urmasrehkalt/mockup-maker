import pytest

from app import backlog

GOOD = {"role_name": "Külastaja", "role_phrase": "Külastajana", "action": "näha liikmepakette ja hindu",
        "benefit": "valida endale sobiv pakett",
        "criteria": ["Lehel on iga paketi nimi.", "Iga paketi juures on kuutasu eurodes.",
                     "Iga paketi juures on nupp „Vali“."]}


@pytest.fixture
def project(client):
    return client.post("/api/projects", json={"name": "P"}).json()


def base(project):
    return f"/api/projects/{project['id']}"


def add(client, project, **overrides):
    response = client.post(f"{base(project)}/stories", json={**GOOD, **overrides})
    assert response.status_code == 201, response.text
    return response.json()


def patch(client, project, story, **data):
    return client.patch(f"{base(project)}/stories/{story['id']}", json=data)


def with_mockup(client, project, story):
    client.post(f"{base(project)}/mockups", json={"template": "pricing", "story_id": story["id"]})
    return client.get(base(project)).json()["stories"][0]


def codes(story):
    return [m["code"] for m in story["readiness"]]


def test_a_story_lists_what_keeps_it_from_ready(client, project):
    story = add(client, project, criteria=["Hinnad on selgelt näha."], open_questions=["Kas km sisaldub?"])
    assert codes(story) == ["criteria_count", "criteria_testable", "mockup", "open_questions"]
    assert story["readiness"][0]["count"] == 1


def test_ready_is_refused_with_the_missing_list(client, project):
    story = add(client, project)
    response = patch(client, project, story, status="ready")
    assert response.status_code == 422
    detail = response.json()["detail"]
    assert detail["code"] == "not_ready"
    assert [m["code"] for m in detail["missing"]] == ["mockup"]
    assert client.get(base(project)).json()["stories"][0]["status"] == "idea"  # rolled back


def test_ready_when_everything_is_in_place(client, project):
    story = with_mockup(client, project, add(client, project))
    assert codes(story) == []
    assert patch(client, project, story, status="ready").json()["status"] == "ready"


def test_a_story_without_a_view_needs_no_mockup(client, project):
    story = add(client, project, needs_view=False)
    assert codes(story) == []
    assert patch(client, project, story, status="ready").status_code == 200


def test_at_least_three_testable_criteria(client, project):
    story = with_mockup(client, project, add(client, project, criteria=GOOD["criteria"][:2]))
    assert codes(story) == ["criteria_count"]
    story = patch(client, project, story, criteria=[*GOOD["criteria"], "Registreerumine on kiire."]).json()
    assert codes(story) == ["criteria_testable"]


@pytest.mark.parametrize("parts", [
    {"action": "soovin näha pakette"},
    {"benefit": "et valida sobiv pakett"},
    {"action": "näha pakette, et valida sobiv"},
    {"role_phrase": "Külastajana soovin"},
])
def test_malformed_connextra_parts(client, project, parts):
    assert "connextra" in codes(add(client, project, **parts))


def test_needs_clarification_requires_an_open_question_and_blocks_ready(client, project):
    story = with_mockup(client, project, add(client, project))
    refused = patch(client, project, story, status="needs_clarification")
    assert refused.status_code == 422 and refused.json()["detail"]["code"] == "needs_question"
    story = patch(client, project, story, status="needs_clarification",
                  open_questions=["Klient täpsustab maksevõimalused"]).json()
    assert story["status"] == "needs_clarification"
    blocked = patch(client, project, story, status="ready")
    assert [m["code"] for m in blocked.json()["detail"]["missing"]] == ["open_questions"]
    story = patch(client, project, story, open_questions=[]).json()
    assert patch(client, project, story, status="ready").json()["status"] == "ready"


def test_a_ready_story_drops_back_when_it_stops_being_ready(client, project):
    story = with_mockup(client, project, add(client, project))
    patch(client, project, story, status="ready")
    story = patch(client, project, story, open_questions=["Kas km sisaldub?"]).json()
    assert story["status"] == "needs_clarification"

    story = patch(client, project, story, open_questions=[]).json()
    patch(client, project, story, status="ready")
    story = patch(client, project, story, criteria=GOOD["criteria"][:1]).json()
    assert story["status"] == "reviewed"

    story = patch(client, project, story, criteria=GOOD["criteria"]).json()
    patch(client, project, story, status="ready")
    client.delete(f"{base(project)}/stories/{story['id']}/mockups/{story['mockup_ids'][0]}")
    assert client.get(base(project)).json()["stories"][0]["status"] == "reviewed"


def test_creating_a_story_as_ready_is_checked(client, project):
    response = client.post(f"{base(project)}/stories", json={**GOOD, "status": "ready"})
    assert response.status_code == 422
    assert client.get(base(project)).json()["stories"] == []
    assert client.post(f"{base(project)}/stories",
                       json={**GOOD, "status": "ready", "needs_view": False}).status_code == 201


def test_the_ai_sees_what_is_missing(client, project, monkeypatch):
    from app.ai import providers
    from tests.test_conversation import Recorder
    recorder = Recorder()
    monkeypatch.setattr(providers, "get", lambda name=None: recorder)
    add(client, project, needs_view=True)
    client.post(f"{base(project)}/turn", json={"kind": "text", "text": "Jätkame"})
    sent = recorder.payloads[-1]["backlog"][0]
    assert sent["missing_for_ready"] == ["mockup"] and sent["needs_view"] is True


def test_connextra_ok_accepts_normal_parts():
    assert backlog.connextra_ok(backlog.StoryParts(**{k: GOOD[k] for k in ("role_name", "role_phrase",
                                                                         "action", "benefit")}))
