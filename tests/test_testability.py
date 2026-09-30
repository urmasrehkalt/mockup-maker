import pytest

from app import conversation
from app.ai import providers
from app.testability import check
from tests.test_conversation import Recorder, last_assistant, turn


def codes(text):
    return [issue.code for issue in check(text)]


# The table from the assignment: testable vs untestable, with the stated problem.
@pytest.mark.parametrize("text, expected", [
    ("Treeningute leht on kasutajasõbralik.", ["evaluative"]),
    ("Hinnad on selgelt näha.", ["evaluative"]),
    ("Registreerumine on kiire ja lihtne.", ["evaluative", "multiple"]),
    ("Vorm kontrollib andmeid ja saadab meili.", ["multiple"]),
])
def test_assignment_examples_that_are_not_testable(text, expected):
    assert codes(text) == expected


@pytest.mark.parametrize("text", [
    "Treeningute lehel on iga treeningu juures selle kestus minutites.",
    "Paketi hinna juures on märge, kas hind sisaldab käibemaksu.",
    "Pärast registreerumist kuvatakse kinnitusteade.",
    "Registreerumisvorm ei lase saata tühja e-posti väljaga.",
])
def test_assignment_examples_that_are_testable(text):
    assert check(text) == []


@pytest.mark.parametrize("text, word", [
    ("Maksmine käib lihtsalt.", "lihtsalt"),
    ("Leht avaneb kiiresti.", "kiiresti"),
    ("Menüü on mugavalt kasutatav.", "mugavalt"),
    ("Vorm on intuitiivselt täidetav.", "intuitiivselt"),
    ("The page is user-friendly.", "user-friendly"),
    ("Results load quickly.", "quickly"),
    ("Vaade on hea.", "hea"),
])
def test_evaluative_words_in_their_inflected_forms(text, word):
    issues = check(text)
    assert issues[0].code == "evaluative" and word in issues[0].words


def test_vague_wording():
    assert codes("Lehel on võimalikult palju infot.") == ["vague"]
    assert codes("Kuvatakse nimi, hind jne.") == ["vague"]


def test_several_sentences_count_as_several_conditions():
    assert codes("Kuvatakse teade. Saadetakse e-kiri.") == ["multiple"]
    assert codes("Kuvatakse teade.") == []


def test_words_are_matched_whole_not_inside_other_words():
    assert check("Kasutaja vastab jah või ei.") == []  # "jah" is not "ja"
    assert check("Lehel on selgitus paketi kohta.") == []  # "selgitus" is not "selge"


def test_check_endpoint(client):
    response = client.post("/api/criteria/check", json={"texts": [
        "Hinnad on selgelt näha.", "Pärast registreerumist kuvatakse kinnitusteade."]})
    assert response.status_code == 200
    first, second = response.json()
    assert first == [{"code": "evaluative", "words": ["selgelt"]}]
    assert second == []


def test_stored_criteria_carry_their_warnings(client):
    project = client.post("/api/projects", json={"name": "P"}).json()
    client.post(f"/api/projects/{project['id']}/stories", json={
        "role_name": "Külastaja", "role_phrase": "Külastajana", "action": "registreeruda",
        "benefit": "saada liikmeks", "criteria": ["Registreerumine on kiire ja lihtne.",
                                                   "Pärast registreerumist kuvatakse kinnitusteade."]})
    criteria = client.get(f"/api/projects/{project['id']}").json()["stories"][0]["criteria"]
    assert [c["code"] for c in criteria[0]["issues"]] == ["evaluative", "multiple"]
    assert criteria[1]["issues"] == []


def test_ai_is_sent_back_to_fix_untestable_criteria(client, monkeypatch):
    project = client.post("/api/projects", json={"name": "P"}).json()
    story = client.post(f"/api/projects/{project['id']}/stories", json={
        "role_name": "Külastaja", "role_phrase": "Külastajana", "action": "näha pakette",
        "benefit": "valida sobiv"}).json()

    def answers(payload):
        answer = conversation.mock_turn(payload)
        if len(recorder.payloads) == 1:  # first attempt: one untestable criterion
            answer["proposal"]["criteria"][0]["text"] = "Pakettide leht on kasutajasõbralik."
        return answer
    recorder = Recorder(answers)
    monkeypatch.setattr(providers, "get", lambda name=None: recorder)
    state = turn(client, project, kind="focus", story_id=story["id"]).json()
    assert "kasutajasõbralik" in recorder.prompts[1] and "yes or no" in recorder.prompts[1]
    criteria = last_assistant(state)["content"]["proposal"]["criteria"]
    assert all(c["issues"] == [] for c in criteria)


def test_untestable_criterion_the_model_insists_on_is_flagged_on_the_card(client, monkeypatch):
    project = client.post("/api/projects", json={"name": "P"}).json()
    story = client.post(f"/api/projects/{project['id']}/stories", json={
        "role_name": "Külastaja", "role_phrase": "Külastajana", "action": "näha pakette",
        "benefit": "valida sobiv"}).json()

    def stubborn(payload):
        answer = conversation.mock_turn(payload)
        answer["proposal"]["criteria"][0]["text"] = "Hinnad on selgelt näha."
        return answer
    monkeypatch.setattr(providers, "get", lambda name=None: Recorder(stubborn))
    state = turn(client, project, kind="focus", story_id=story["id"]).json()
    first = last_assistant(state)["content"]["proposal"]["criteria"][0]
    assert first["issues"] == [{"code": "evaluative", "words": ["selgelt"]}]
