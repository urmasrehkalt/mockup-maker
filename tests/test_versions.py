import pytest

from app.ai import providers
from tests.test_conversation import Recorder
from tests.test_refinement import PRICING, prepared, refine, snapshot, state, turn


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


def refined(client, project):
    """A story whose mockup went through a proposal (v1) and an applied refinement (v2)."""
    story = prepared(client, project, PRICING)
    message = refine(client, project, story)
    turn(client, project, kind="change", message_id=message["id"], decision="apply")
    return story, story["mockup_ids"][0]


def test_every_applied_change_is_a_version_with_its_origin(client, project, ai):
    _, mockup_id = refined(client, project)
    versions = client.get(f"{base(project)}/mockups/{mockup_id}/versions").json()
    assert [v["number"] for v in versions] == [1, 2]
    assert versions[0]["note"].startswith("proposal:") and versions[1]["note"].startswith("change:")
    assert "refinement-note" not in str(versions[0]["tree"])
    assert "refinement-note" in str(versions[1]["tree"])


def test_restoring_makes_an_old_version_the_newest(client, project, ai):
    story, mockup_id = refined(client, project)
    restored = client.post(f"{base(project)}/mockups/{mockup_id}/versions/1/restore")
    assert restored.status_code == 200
    assert restored.json()["version"] == 3
    versions = client.get(f"{base(project)}/mockups/{mockup_id}/versions").json()
    assert [v["number"] for v in versions] == [1, 2, 3]
    assert versions[2]["note"] == "restore:1" and versions[2]["tree"] == versions[0]["tree"]
    _, mockup = snapshot(client, project, story["id"])
    assert mockup[0][1] == 3 and "refinement-note" not in str(mockup[0][2])


def test_restore_can_be_undone(client, project, ai):
    _, mockup_id = refined(client, project)
    client.post(f"{base(project)}/mockups/{mockup_id}/versions/1/restore")
    assert state(client, project)["undo"] == {"action": "mockup_restored",
                                              "params": {"title": "Hinnakiri", "version": 1}}
    client.post(f"{base(project)}/undo")
    versions = client.get(f"{base(project)}/mockups/{mockup_id}/versions").json()
    assert [v["number"] for v in versions] == [1, 2]


def test_restore_errors(client, project, ai):
    _, mockup_id = refined(client, project)
    assert client.post(f"{base(project)}/mockups/{mockup_id}/versions/9/restore").status_code == 404
    assert client.post(f"{base(project)}/mockups/{mockup_id}/versions/2/restore").status_code == 409
    other = client.post("/api/projects", json={"name": "Teine"}).json()
    assert client.get(f"{base(other)}/mockups/{mockup_id}/versions").status_code == 404
    assert client.post(f"{base(other)}/mockups/{mockup_id}/versions/1/restore").status_code == 404
