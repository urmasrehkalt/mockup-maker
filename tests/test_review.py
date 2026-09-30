import pytest

from app import review
from app.ai import providers
from tests.test_conversation import Recorder

ROLE = {"role_name": "Külastaja", "role_phrase": "Külastajana"}
BIG = {**ROLE, "action": "registreeruda ja tasuda liikmetasu", "benefit": "saada liikmeks", "needs_view": False,
       "criteria": ["Vormis on väli „E-post“.", "Vormis on nupp „Registreeru“.",
                    "Maksevaates on nupp „Maksa“.", "Pärast makset kuvatakse kinnitus."]}
PACKAGES = {**ROLE, "action": "näha liikmepakette", "benefit": "valida sobiv pakett",
            "criteria": ["Lehel on iga paketi nimi.", "Hinnad on selgelt näha.", "Iga paketi juures on nupp „Vali“."]}
OVERLAP = {**ROLE, "action": "näha liikmepakette hinnaga", "benefit": "võrrelda pakette", "needs_view": False,
           "criteria": ["lehel on iga paketi NIMI", "Iga paketi juures on kuutasu eurodes."]}
MALFORMED = {"role_name": "Administraator", "role_phrase": "Administraatorina", "action": "soovin muuta hindu",
             "benefit": "hinnakiri oleks ajakohane", "needs_view": False,
             "criteria": ["Hinna muutmise vormis on väli „Hind“.", "Vormis on nupp „Salvesta“.",
                          "Pärast salvestamist kuvatakse kinnitus."]}


@pytest.fixture
def ai(monkeypatch):
    recorder = Recorder()
    monkeypatch.setattr(providers, "get", lambda name=None: recorder)
    return recorder


@pytest.fixture
def project(client):
    project = client.post("/api/projects", json={"name": "Spordiklubi"}).json()
    for story in (BIG, PACKAGES, OVERLAP, MALFORMED):
        assert client.post(f"/api/projects/{project['id']}/stories", json=story).status_code == 201
    return project


def base(project):
    return f"/api/projects/{project['id']}"


def state(client, project):
    return client.get(base(project)).json()


def reviewed(client, project):
    response = client.post(f"{base(project)}/review")
    assert response.status_code == 200, response.text
    message = response.json()["messages"][-1]
    return message, {(f["kind"], tuple(f["story_keys"])): i for i, f in enumerate(message["content"]["review"]["findings"])}


def decide(client, project, message, index, **data):
    return client.post(f"{base(project)}/review/{message['id']}/findings/{index}", json={"decision": "apply", **data})


def test_review_finds_every_kind_of_problem_and_changes_nothing(client, project, ai):
    before = state(client, project)["stories"]
    message, found = reviewed(client, project)
    kinds = {kind for kind, _ in found}
    assert {"too_large", "overlap", "untestable_criteria", "no_mockup", "not_connextra"} <= kinds
    for finding in message["content"]["review"]["findings"]:
        assert finding["problem"] and finding["reason"] and finding["status"] == "pending"
        assert finding[review.PROPOSAL_FOR[finding["kind"]]]
    assert state(client, project)["stories"] == before
    assert state(client, project)["project"]["step"] == "grooming"
    assert ai.payloads[-1]["backlog"][1]["criteria"][1]["issues"] == ["evaluative"]


def test_apply_split_distributes_criteria(client, project, ai):
    message, found = reviewed(client, project)
    finding = message["content"]["review"]["findings"][found[("too_large", ("US-1",))]]
    parts = finding["split"]["parts"]
    decide(client, project, message, found[("too_large", ("US-1",))])
    stories = state(client, project)["stories"]
    first, second = stories[0], stories[1]
    assert first["key"] == "US-1" and first["action"] == parts[0]["action"]
    assert [c["text"] for c in first["criteria"]] == [BIG["criteria"][i] for i in parts[0]["criteria"]]
    assert [c["text"] for c in second["criteria"]] == [BIG["criteria"][i] for i in parts[1]["criteria"]]
    assert second["origin"] == "ai"
    client.post(f"{base(project)}/undo")
    assert state(client, project)["stories"][0]["action"] == BIG["action"]


def test_apply_merge_without_duplicate_criteria(client, project, ai):
    message, found = reviewed(client, project)
    index = found[("overlap", ("US-2", "US-3"))]
    finding = message["content"]["review"]["findings"][index]
    assert finding["dropped_duplicates"] == ["lehel on iga paketi NIMI"]
    assert finding["dropped_other"] == ["Hinnad on selgelt näha."]  # untestable, left out
    after = decide(client, project, message, index).json()
    keys = [s["key"] for s in after["stories"]]
    assert "US-3" not in keys
    merged = next(s for s in after["stories"] if s["key"] == "US-2")
    assert [c["text"] for c in merged["criteria"]] == finding["merge"]["criteria"]


def test_apply_criteria_with_the_users_edit(client, project, ai):
    message, found = reviewed(client, project)
    edited = ["Lehel on iga paketi nimi.", "Iga paketi juures on kuutasu eurodes.", "Iga paketi juures on nupp „Vali“."]
    decide(client, project, message, found[("untestable_criteria", ("US-2",))], criteria={"criteria": edited})
    story = next(s for s in state(client, project)["stories"] if s["key"] == "US-2")
    assert [c["text"] for c in story["criteria"]] == edited
    card = state(client, project)["messages"][-1]["content"]["review"]["findings"]
    assert card[found[("untestable_criteria", ("US-2",))]]["criteria"]["criteria"] == edited


def test_apply_mockup_and_wording(client, project, ai):
    message, found = reviewed(client, project)
    decide(client, project, message, found[("no_mockup", ("US-2",))])
    decide(client, project, message, found[("not_connextra", ("US-4",))])
    stories = {s["key"]: s for s in state(client, project)["stories"]}
    assert stories["US-2"]["mockup_ids"]
    assert stories["US-4"]["title"] == "Administraatorina soovin muuta hindu, et hinnakiri oleks ajakohane."
    assert "connextra" not in [m["code"] for m in stories["US-4"]["readiness"]]


def test_ignore_and_decide_once(client, project, ai):
    before = state(client, project)["stories"]
    message, found = reviewed(client, project)
    index = found[("too_large", ("US-1",))]
    ignored = client.post(f"{base(project)}/review/{message['id']}/findings/{index}", json={"decision": "ignore"})
    assert ignored.json()["messages"][-1]["content"]["review"]["findings"][index]["status"] == "ignored"
    assert state(client, project)["stories"] == before
    assert decide(client, project, message, index).status_code == 409
    assert decide(client, project, message, 99).status_code == 404


def test_split_is_refused_when_the_story_changed_since_the_review(client, project, ai):
    message, found = reviewed(client, project)
    us1 = state(client, project)["stories"][0]
    client.patch(f"{base(project)}/stories/{us1['id']}", json={"criteria": ["Uus kriteerium."]})
    assert decide(client, project, message, found[("too_large", ("US-1",))]).status_code == 409


def test_known_problems_the_model_misses_are_filled_in(client, project, monkeypatch):
    recorder = Recorder(lambda payload: {"summary": "Kõik on hästi.", "findings": []})
    monkeypatch.setattr(providers, "get", lambda name=None: recorder)
    message, found = reviewed(client, project)
    assert "no finding" in recorder.prompts[1]
    kinds = {kind for kind, _ in found}
    assert {"untestable_criteria", "no_mockup", "not_connextra", "missing_criteria"} <= kinds


def test_check_review_rules(client, project, ai):
    import sqlite3  # noqa: F401
    payload = {"backlog": [
        {"key": "US-1", "criteria": [{"index": 0, "text": "a", "issues": []}], "missing_for_ready": []},
        {"key": "US-2", "criteria": [], "missing_for_ready": []}]}

    def one(**finding):
        base_finding = {"kind": "too_large", "story_keys": ["US-1"], "problem": "p", "reason": "r"}
        return review.Review.model_validate({"summary": "s", "findings": [{**base_finding, **finding}]})
    split = lambda idx: {"parts": [  # noqa: E731
        {"role_phrase": "A", "action": "a", "benefit": "b", "criteria": idx, "new_criteria": []},
        {"role_phrase": "A", "action": "c", "benefit": "d", "criteria": [], "new_criteria": []}]}
    assert review.check_review(one(split=split([0])), payload) is None
    assert "index" in review.check_review(one(split=split([3])), payload)
    assert "not in the backlog" in review.check_review(one(story_keys=["US-9"], split=split([])), payload)
    same = {"keep_key": "US-1", "remove_key": "US-1", "wording": None, "criteria": ["Lehel on nimi."]}
    assert "two different" in review.check_review(one(kind="overlap", merge=same), payload)
    vague = {"criteria": ["Leht on kasutajasõbralik."]}
    assert "yes or no" in review.check_review(one(kind="untestable_criteria", criteria=vague), payload)
    with pytest.raises(ValueError):
        one(kind="overlap", split=split([0]))  # the proposal must match the kind


def test_empty_backlog_is_not_reviewed(client, ai):
    empty = client.post("/api/projects", json={"name": "Tühi"}).json()
    assert client.post(f"/api/projects/{empty['id']}/review").status_code == 409


def test_review_with_ai_off_says_so(client, project, monkeypatch):
    monkeypatch.setenv("AI_PROVIDER", "off")
    response = client.post(f"{base(project)}/review")
    assert response.status_code == 503 and response.json()["error"]["code"] == "ai_disabled"
