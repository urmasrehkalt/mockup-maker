import pytest

BIG = {"role_name": "Külastaja", "role_phrase": "Külastajana",
       "action": "registreeruda ja tasuda liikmetasu", "benefit": "saada liikmeks",
       "criteria": ["Vormis on väli „E-post“.", "Vormis on nupp „Registreeru“.",
                    "Maksevaates on nupp „Maksa“.", "Pärast makset kuvatakse kinnitus."],
       "open_questions": ["Kas makse on kohustuslik?"]}


@pytest.fixture
def project(client):
    return client.post("/api/projects", json={"name": "P"}).json()


def base(project):
    return f"/api/projects/{project['id']}"


def add(client, project, **data):
    return client.post(f"{base(project)}/stories", json={**BIG, **data}).json()


def state(client, project):
    return client.get(base(project)).json()


def parts(story):
    ids = [c["id"] for c in story["criteria"]]
    return [
        {"role_phrase": "Külastajana", "action": "registreeruda liikmeks", "benefit": "saada kasutajakonto",
         "criterion_ids": ids[:2]},
        {"role_phrase": "Külastajana", "action": "tasuda liikmetasu veebis", "benefit": "saada liikmeks",
         "criterion_ids": ids[2:], "new_criteria": ["Maksevaates on summa eurodes."]},
    ]


# --- split ---------------------------------------------------------------

def test_split_distributes_criteria_and_keeps_the_original_in_place(client, project):
    before = add(client, project, action="alustada")
    big = add(client, project)
    after = add(client, project, action="lõpetada")
    mockup = client.post(f"{base(project)}/mockups", json={"template": "form", "story_id": big["id"]}).json()
    big = next(s for s in state(client, project)["stories"] if s["id"] == big["id"])

    result = client.post(f"{base(project)}/stories/{big['id']}/split", json={"parts": parts(big)})
    assert result.status_code == 200, result.text
    first, second = result.json()
    assert first["id"] == big["id"] and first["key"] == big["key"]
    assert first["action"] == "registreeruda liikmeks"
    assert [c["text"] for c in first["criteria"]] == [c["text"] for c in big["criteria"][:2]]
    assert [c["text"] for c in second["criteria"]] == [c["text"] for c in big["criteria"][2:]] + [
        "Maksevaates on summa eurodes."]
    assert second["key"] == "US-4" and second["mockup_ids"] == [mockup["id"]]
    assert first["open_questions"] == big["open_questions"]
    order = [s["id"] for s in state(client, project)["stories"]]
    assert order == [before["id"], first["id"], second["id"], after["id"]]


def test_split_dry_run_changes_nothing(client, project):
    big = add(client, project)
    preview = client.post(f"{base(project)}/stories/{big['id']}/split",
                          json={"parts": parts(big), "dry_run": True}).json()
    assert len(preview) == 2
    current = state(client, project)
    assert len(current["stories"]) == 1 and current["undo"]["action"] == "story_added"
    assert current["stories"][0]["action"] == BIG["action"]


def test_split_rejects_bad_criteria_assignment(client, project):
    big = add(client, project)
    other = add(client, project, criteria=["Muu."])
    bad = parts(big)
    bad[1]["criterion_ids"] = [big["criteria"][0]["id"]]  # already in part 1
    assert client.post(f"{base(project)}/stories/{big['id']}/split", json={"parts": bad}).status_code == 422
    foreign = parts(big)
    foreign[1]["criterion_ids"] = [other["criteria"][0]["id"]]
    assert client.post(f"{base(project)}/stories/{big['id']}/split", json={"parts": foreign}).status_code == 422
    one = parts(big)[:1]
    assert client.post(f"{base(project)}/stories/{big['id']}/split", json={"parts": one}).status_code == 422


def test_split_can_be_undone(client, project):
    big = add(client, project)
    client.post(f"{base(project)}/stories/{big['id']}/split", json={"parts": parts(big)})
    client.post(f"{base(project)}/undo")
    stories = state(client, project)["stories"]
    assert len(stories) == 1 and len(stories[0]["criteria"]) == 4
    assert stories[0]["action"] == BIG["action"]


# --- merge ---------------------------------------------------------------

def test_merge_unites_criteria_without_duplicates(client, project):
    keep = add(client, project, action="näha pakette", criteria=["Lehel on iga paketi nimi.", "Iga paketi juures on hind."],
               open_questions=[])
    remove = add(client, project, action="näha hindu", criteria=["lehel on iga paketi NIMI", "Hinna juures on märge „sh km“."],
                 open_questions=["Kas km sisaldub?"])
    mockup = client.post(f"{base(project)}/mockups", json={"template": "pricing", "story_id": remove["id"]}).json()
    client.patch(base(project), json={"current_story_id": remove["id"]})

    preview = client.post(f"{base(project)}/stories/merge",
                          json={"keep_id": keep["id"], "remove_id": remove["id"], "dry_run": True}).json()
    assert preview["dropped_duplicates"] == ["lehel on iga paketi NIMI"]
    assert len(state(client, project)["stories"]) == 2  # nothing happened yet

    result = client.post(f"{base(project)}/stories/merge", json={"keep_id": keep["id"], "remove_id": remove["id"]}).json()
    merged = result["story"]
    assert result["removed_key"] == remove["key"]
    assert [c["text"] for c in merged["criteria"]] == ["Lehel on iga paketi nimi.", "Iga paketi juures on hind.",
                                                        "Hinna juures on märge „sh km“."]
    assert merged["open_questions"] == ["Kas km sisaldub?"]
    assert merged["mockup_ids"] == [mockup["id"]]
    current = state(client, project)
    assert [s["id"] for s in current["stories"]] == [keep["id"]]
    assert current["project"]["current_story_id"] == keep["id"]


def test_merge_with_edited_wording_and_criteria(client, project):
    keep = add(client, project, criteria=["A."])
    remove = add(client, project, criteria=["B."])
    wording = {"role_phrase": "Külastajana", "action": "liituda veebis", "benefit": "hakata treenima"}
    merged = client.post(f"{base(project)}/stories/merge", json={
        "keep_id": keep["id"], "remove_id": remove["id"], "wording": wording, "criteria": ["B.", "C."]}).json()["story"]
    assert merged["title"] == "Külastajana soovin liituda veebis, et hakata treenima."
    assert [(c["text"], c["origin"]) for c in merged["criteria"]] == [("B.", "manual"), ("C.", "manual")]


def test_merge_errors_and_undo(client, project):
    keep = add(client, project)
    assert client.post(f"{base(project)}/stories/merge",
                       json={"keep_id": keep["id"], "remove_id": keep["id"]}).status_code == 422
    assert client.post(f"{base(project)}/stories/merge",
                       json={"keep_id": keep["id"], "remove_id": 999}).status_code == 404
    remove = add(client, project, criteria=["Muu kriteerium."])
    client.post(f"{base(project)}/stories/merge", json={"keep_id": keep["id"], "remove_id": remove["id"]})
    client.post(f"{base(project)}/undo")
    stories = state(client, project)["stories"]
    assert [s["id"] for s in stories] == [keep["id"], remove["id"]]
    assert len(stories[0]["criteria"]) == 4


# --- MVP line and starting point -----------------------------------------

def test_mvp_line_is_placed_moved_and_kept_through_changes(client, project):
    ids = [add(client, project, action=f"teha {n}")["id"] for n in range(4)]
    assert client.put(f"{base(project)}/stories/order", json={"ids": ids, "mvp_count": 2}).status_code == 204
    current = state(client, project)
    assert current["project"]["mvp_count"] == 2
    assert [s["in_mvp"] for s in current["stories"]] == [True, True, False, False]

    client.delete(f"{base(project)}/stories/{ids[0]}")  # above the line: the line moves up with it
    assert [s["in_mvp"] for s in state(client, project)["stories"]] == [True, False, False]
    client.post(f"{base(project)}/undo")
    assert [s["in_mvp"] for s in state(client, project)["stories"]] == [True, True, False, False]

    story = next(s for s in state(client, project)["stories"] if s["id"] == ids[1])
    client.post(f"{base(project)}/stories/{ids[1]}/split", json={"parts": [
        {"role_phrase": "Külastajana", "action": "osa 1", "benefit": "x", "criterion_ids": [c["id"] for c in story["criteria"]]},
        {"role_phrase": "Külastajana", "action": "osa 2", "benefit": "x"}]})
    assert [s["in_mvp"] for s in state(client, project)["stories"]] == [True, True, True, False, False]

    client.post(f"{base(project)}/stories", json={**BIG, "action": "uus"})  # new stories go below
    assert state(client, project)["stories"][-1]["in_mvp"] is False


def test_mvp_line_can_be_removed_and_is_validated(client, project):
    ids = [add(client, project, action=f"teha {n}")["id"] for n in range(2)]
    assert client.put(f"{base(project)}/stories/order", json={"ids": ids, "mvp_count": 3}).status_code == 422
    client.put(f"{base(project)}/stories/order", json={"ids": ids, "mvp_count": 1})
    assert state(client, project)["undo"]["action"] == "mvp_moved"
    client.put(f"{base(project)}/stories/order", json={"ids": ids, "keep_mvp": False})
    assert state(client, project)["project"]["mvp_count"] is None
    client.put(f"{base(project)}/stories/order", json={"ids": ids[::-1]})  # reorder keeps no line
    assert state(client, project)["project"]["mvp_count"] is None


def test_mark_the_starting_point(client, project):
    story = add(client, project)
    assert client.patch(base(project), json={"current_story_id": story["id"]}).json()["current_story_id"] == story["id"]
    other = client.post("/api/projects", json={"name": "Teine"}).json()
    foreign = client.post(f"/api/projects/{other['id']}/stories", json=BIG).json()
    assert client.patch(base(project), json={"current_story_id": foreign["id"]}).status_code == 404
