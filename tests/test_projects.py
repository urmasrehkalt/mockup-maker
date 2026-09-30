from fastapi.testclient import TestClient

from app import db, projects
from app.main import app


def create(client, name="Spordiklubi", description="Treeningud ja liikmeks astumine"):
    response = client.post("/api/projects", json={"name": name, "description": description})
    assert response.status_code == 201, response.text
    return response.json()


def test_create_project_with_name_and_description(client):
    project = create(client)
    assert project["name"] == "Spordiklubi"
    assert project["description"] == "Treeningud ja liikmeks astumine"
    assert project["step"] == "idea"
    assert project["created_at"] == project["updated_at"]


def test_name_is_required_and_trimmed(client):
    assert client.post("/api/projects", json={"name": "   "}).status_code == 422
    assert client.post("/api/projects", json={"description": "x"}).status_code == 422
    assert create(client, name="  Pood  ", description="")["name"] == "Pood"


def test_unknown_fields_are_rejected(client):
    response = client.post("/api/projects", json={"name": "A", "step": "grooming"})
    assert response.status_code == 422


def test_list_shows_projects_most_recently_changed_first(client, db_path):
    first = create(client, name="Esimene")
    second = create(client, name="Teine")
    conn = db.connect(db_path)
    with conn:
        conn.execute("UPDATE projects SET updated_at = '2000-01-01T00:00:00+00:00' WHERE id = ?",
                     (second["id"],))
    conn.close()
    listed = client.get("/api/projects").json()
    assert [p["name"] for p in listed] == ["Esimene", "Teine"]
    assert {"name", "description", "updated_at"} <= set(listed[0])
    assert listed[0]["id"] == first["id"]


def test_open_unknown_project_is_404(client):
    assert client.get("/api/projects/999").status_code == 404
    assert client.patch("/api/projects/999", json={"step": "roles"}).status_code == 404


def test_new_project_resume_asks_for_the_idea(client):
    project = create(client)
    state = client.get(f"/api/projects/{project['id']}").json()
    assert state["messages"] == []
    assert state["resume"] == {"step": "idea", "kind": "start", "actions": []}


def test_step_can_be_changed_and_is_validated(client):
    project = create(client)
    response = client.patch(f"/api/projects/{project['id']}", json={"step": "stories"})
    assert response.json()["step"] == "stories"
    assert client.patch(f"/api/projects/{project['id']}", json={"step": "done"}).status_code == 422


def test_every_step_resumes_with_one_to_four_actions():
    for step in projects.STEPS:
        project = projects.Project(id=1, name="x", description="", step=step,
                                   created_at="t", updated_at="t")
        history = [projects.Message(id=1, role="user", content={"text": "hi"}, created_at="t")]
        resume = projects.resume(project, history)
        assert resume.kind == "continue"
        assert 1 <= len(resume.actions) <= 4


def test_project_survives_restart_with_history_and_step(db_path):
    with TestClient(app) as client:
        project = create(client)
        client.patch(f"/api/projects/{project['id']}", json={"step": "criteria"})
        conn = db.connect(db_path)
        projects.add_message(conn, project["id"], "user", {"text": "Spordiklubi tahab veebi."})
        projects.add_message(conn, project["id"], "assistant",
                             {"text": "Kes on kasutajad?", "options": ["Külastaja", "Liige"]})
        conn.close()

    # A new app lifespan against the same file stands in for a server restart.
    with TestClient(app) as client:
        state = client.get(f"/api/projects/{project['id']}").json()

    assert state["project"]["name"] == "Spordiklubi"
    assert state["project"]["step"] == "criteria"
    assert [m["role"] for m in state["messages"]] == ["user", "assistant"]
    assert state["messages"][1]["content"]["options"] == ["Külastaja", "Liige"]
    assert state["resume"] == {"step": "criteria", "kind": "continue",
                               "actions": projects.RESUME_ACTIONS["criteria"]}


def test_new_message_marks_project_as_changed(client, db_path):
    project = create(client)
    conn = db.connect(db_path)
    with conn:
        conn.execute("UPDATE projects SET updated_at = '2000-01-01T00:00:00+00:00'")
    projects.add_message(conn, project["id"], "user", {"text": "x"})
    conn.close()
    assert client.get("/api/projects").json()[0]["updated_at"] > "2000-01-01T00:00:00+00:00"
