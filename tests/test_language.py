import pytest

from app import tracker
from app.ai import providers
from app.mockup_templates import ENGLISH, TEMPLATES, localized
from tests.test_conversation import Recorder

EN_STORY = {"role_name": "Visitor", "role_phrase": "a visitor", "action": "see the membership packages",
            "benefit": "I can choose one that suits me", "criteria": ["Each package shows its name."]}


@pytest.fixture
def ai(monkeypatch):
    recorder = Recorder()
    monkeypatch.setattr(providers, "get", lambda name=None: recorder)
    return recorder


def new(client, language=None):
    body = {"name": "Club"} | ({"language": language} if language else {})
    return client.post("/api/projects", json=body).json()


def test_project_language_defaults_to_estonian_and_can_be_english(client):
    assert new(client)["language"] == "et"
    project = new(client, "en")
    assert project["language"] == "en"
    assert client.post("/api/projects", json={"name": "X", "language": "fi"}).status_code == 422
    assert client.patch(f"/api/projects/{project['id']}", json={"language": "et"}).json()["language"] == "et"


def test_titles_follow_the_project_language(client):
    en = new(client, "en")
    story = client.post(f"/api/projects/{en['id']}/stories", json=EN_STORY).json()
    assert story["title"] == "As a visitor, I want to see the membership packages, so that I can choose one that suits me."
    assert story["readiness"][0]["code"] != "connextra"


def test_the_ai_is_asked_in_the_project_language(client, ai):
    en = new(client, "en")
    client.post(f"/api/projects/{en['id']}/turn", json={"kind": "text", "text": "A sports club wants a website."})
    assert ai.payloads[-1]["language"] == "en"
    client.post(f"/api/projects/{en['id']}/stories", json=EN_STORY)
    client.post(f"/api/projects/{en['id']}/review")
    assert ai.payloads[-1]["language"] == "en"
    assert "Pricing" in ai.payloads[-1]["templates"].values()


def test_rule_based_review_findings_are_in_the_project_language(client, monkeypatch):
    monkeypatch.setattr(providers, "get", lambda name=None: Recorder(lambda p: {"summary": "Fine.", "findings": []}))
    en = new(client, "en")
    client.post(f"/api/projects/{en['id']}/stories", json={**EN_STORY, "criteria": ["The page is user-friendly."]})
    findings = client.post(f"/api/projects/{en['id']}/review").json()["messages"][-1]["content"]["review"]["findings"]
    problems = {f["kind"]: f["problem"] for f in findings}
    assert problems["untestable_criteria"] == "The criteria are missing or cannot be checked."


def test_mockup_templates_in_english_keep_their_ids(client):
    en = new(client, "en")
    mockup = client.post(f"/api/projects/{en['id']}/mockups", json={"template": "pricing"}).json()
    assert mockup["title"] == "Pricing"
    ids_en = str(mockup["tree"])
    assert "€29 / month" in ids_en and "package-basic" in ids_en
    names = [t["name"] for t in client.get("/api/mockup-templates?lang=en").json()]
    assert "Pricing" in names and "Hinnakiri" not in names


def test_every_template_text_has_an_english_version():
    missing = []

    def walk(value):
        if isinstance(value, dict):
            for key, inner in value.items():
                if key not in ("id", "type", "variant"):
                    walk(inner)
        elif isinstance(value, list):
            for inner in value:
                walk(inner)
        elif isinstance(value, str) and value not in ENGLISH:
            missing.append(value)
    for key, (name, tree) in TEMPLATES.items():
        walk(name)
        walk(tree)
    assert missing == []
    assert localized("pricing", "et") == TEMPLATES["pricing"]


def test_project_templates_in_english(client):
    names = [t["name"] for t in client.get("/api/templates?lang=en").json() if t["built_in"]]
    assert "Sports club website" in names


def test_tracker_description_labels_follow_the_language(client):
    en = new(client, "en")
    client.post(f"/api/projects/{en['id']}/stories", json={**EN_STORY, "size": "S", "open_questions": ["VAT?"]})
    story = client.get(f"/api/projects/{en['id']}").json()["stories"][0]
    from app import backlog
    description = tracker.story_payload(backlog.Story(**story), 1, "en")["description"]
    assert "Role: Visitor" in description and "Size: S" in description and "Open questions:" in description
