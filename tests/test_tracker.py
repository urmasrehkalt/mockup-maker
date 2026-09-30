import io

import pytest
from PIL import Image

from app import tracker
from app.mockup_png import render_png
from app.mockup_templates import TEMPLATES
from app.mockups import Tree

PNG_MAGIC = b"\x89PNG\r\n\x1a\n"
STORY = {"role_name": "Külastaja", "role_phrase": "Külastajana", "action": "näha liikmepakette ja hindu",
         "benefit": "valida endale sobiv pakett", "size": "M",
         "criteria": ["Lehel on iga paketi nimi.", "Iga paketi juures on kuutasu eurodes.",
                      "Iga paketi juures on nupp „Vali“."]}


class FakeTracker:
    """In-memory Agile Tracker with the real API's rules (app/models.py over there)."""

    PROJECT_FIELDS = {"name", "description", "color", "status", "owner", "client", "deadline"}
    CREATE_FIELDS = {"title", "description", "status", "points", "projectId", "acceptanceCriteria"}

    def __init__(self):
        self.projects, self.stories, self.images, self.calls = {}, {}, {}, []
        self.next_id = 1
        self.down = False

    def _id(self):
        self.next_id += 1
        return self.next_id - 1

    def request(self, method, path, body=None, image=None):
        if self.down:
            raise tracker.TrackerError("The tracker at http://fake is not reachable: connection refused")
        self.calls.append((method, path, body, image))
        parts = path.strip("/").split("/")
        if parts[:2] == ["api", "projects"]:
            if method == "POST":
                if set(body) - self.PROJECT_FIELDS or not 1 <= len(body.get("name", "")) <= 120:
                    return 422, {"detail": "invalid project"}
                pid = self._id()
                self.projects[pid] = {"id": pid, **body}
                return 201, self.projects[pid]
            pid = int(parts[2])
            return (200, self.projects[pid]) if pid in self.projects else (404, {"detail": "Project not found"})
        if parts[:2] == ["api", "stories"]:
            if method == "POST":
                if set(body) - self.CREATE_FIELDS:
                    return 422, {"detail": f"extra fields {set(body) - self.CREATE_FIELDS}"}
                if not body.get("title") or not body.get("acceptanceCriteria") or body.get("points", -1) < 0:
                    return 422, {"detail": "missing required fields"}
                if body["projectId"] not in self.projects:
                    return 404, {"detail": "Project not found"}
                sid = self._id()
                self.stories[sid] = {"id": sid, "status": "todo", **body}
                return 201, self.stories[sid]
            sid = int(parts[2])
            if sid not in self.stories:
                return 404, {"detail": "Story not found"}
            if len(parts) == 4 and parts[3] == "mockup":
                name, content = image
                if not content.startswith(PNG_MAGIC) or len(content) > 5 * 1024 * 1024:
                    return 422, {"detail": "not a PNG under 5 MB"}
                self.images[sid] = (name, content)
                return 200, self.stories[sid]
            if set(body) - (self.CREATE_FIELDS - {"status"}) - {"status"}:
                return 422, {"detail": "extra fields"}
            self.stories[sid].update(body)
            return 200, self.stories[sid]
        return 404, {"detail": "no route"}


@pytest.fixture
def fake(monkeypatch):
    fake = FakeTracker()
    monkeypatch.setenv("TRACKER_URL", "http://fake")
    monkeypatch.setattr(tracker, "transport", lambda: fake)
    return fake


@pytest.fixture
def project(client):
    return client.post("/api/projects", json={"name": "Spordiklubi", "description": "Klubi veeb"}).json()


def base(project):
    return f"/api/projects/{project['id']}"


def add(client, project, **overrides):
    story = client.post(f"{base(project)}/stories", json={**STORY, **overrides}).json()
    return story


def push(client, project, **data):
    response = client.post(f"{base(project)}/tracker/push", json=data)
    assert response.status_code == 200, response.text
    return response.json()


# --- PNG export ------------------------------------------------------------

def test_every_template_renders_as_a_png_under_5_mb():
    for key, (_, tree) in TEMPLATES.items():
        data = render_png(Tree(**tree))
        assert data.startswith(PNG_MAGIC) and len(data) < 5 * 1024 * 1024, key
        assert Image.open(io.BytesIO(data)).size[0] == 1024


def test_png_endpoint_serves_latest_or_a_given_version(client, project):
    story = add(client, project)
    mockup = client.post(f"{base(project)}/mockups", json={"template": "pricing", "story_id": story["id"]}).json()
    response = client.get(f"{base(project)}/mockups/{mockup['id']}/png")
    assert response.status_code == 200 and response.headers["content-type"] == "image/png"
    assert response.content.startswith(PNG_MAGIC)
    assert client.get(f"{base(project)}/mockups/{mockup['id']}/png?version=1").status_code == 200
    assert client.get(f"{base(project)}/mockups/{mockup['id']}/png?version=7").status_code == 404


def test_estonian_text_does_not_break_the_image():
    tree = Tree(title="Ä", components=[{"id": "h", "type": "heading", "text": "Õunad, šokolaad ja žürii „sh km“ €"}])
    assert render_png(tree).startswith(PNG_MAGIC)


# --- push ------------------------------------------------------------------

def test_first_push_creates_project_stories_and_uploads_the_mockup(client, project, fake):
    story = add(client, project)
    client.post(f"{base(project)}/mockups", json={"template": "pricing", "story_id": story["id"]})
    report = push(client, project)
    assert report["results"] == [{"key": "US-1", "outcome": "created", "tracker_id": report["results"][0]["tracker_id"],
                                  "mockup": "uploaded", "message": ""}]
    pushed = fake.stories[report["results"][0]["tracker_id"]]
    assert pushed["title"] == "Külastajana soovin näha liikmepakette ja hindu, et valida endale sobiv pakett."
    assert pushed["acceptanceCriteria"] == STORY["criteria"]
    assert pushed["points"] == 5 and pushed["status"] == "todo"
    assert pushed["description"].startswith("US-1 · Mockup Maker")
    assert fake.projects[report["tracker_project_id"]]["name"] == "Spordiklubi"
    assert fake.images[pushed["id"]][1].startswith(PNG_MAGIC)
    assert client.get(base(project)).json()["stories"][0]["tracker_id"] == pushed["id"]


def test_second_push_updates_and_skips_an_unchanged_image(client, project, fake):
    story = add(client, project)
    client.post(f"{base(project)}/mockups", json={"template": "pricing", "story_id": story["id"]})
    first = push(client, project)["results"][0]
    fake.stories[first["tracker_id"]]["status"] = "doing"  # a developer picked it up
    client.patch(f"{base(project)}/stories/{story['id']}", json={"size": "L"})

    second = push(client, project)["results"][0]
    assert second["outcome"] == "updated" and second["tracker_id"] == first["tracker_id"]
    assert second["mockup"] == "unchanged"
    assert len(fake.stories) == 1 and len(fake.projects) == 1
    assert fake.stories[first["tracker_id"]]["points"] == 8
    assert fake.stories[first["tracker_id"]]["status"] == "doing"  # not reset by the push
    put = [body for method, path, body, _ in fake.calls if method == "PUT" and body]
    assert "status" not in put[-1]


def test_a_changed_mockup_is_uploaded_again(client, project, fake):
    story = add(client, project)
    mockup = client.post(f"{base(project)}/mockups", json={"template": "pricing", "story_id": story["id"]}).json()
    push(client, project)
    client.post(f"{base(project)}/mockups/{mockup['id']}/versions/1/restore")  # no change in content
    assert push(client, project)["results"][0]["mockup"] == "unchanged"
    client.put(f"{base(project)}/stories/{story['id']}/mockups/{mockup['id']}")
    client.delete(f"{base(project)}/stories/{story['id']}/mockups/{mockup['id']}")
    client.post(f"{base(project)}/mockups", json={"template": "form", "story_id": story["id"]})
    assert push(client, project)["results"][0]["mockup"] == "uploaded"


def test_things_deleted_in_the_tracker_are_created_again(client, project, fake):
    add(client, project)
    first = push(client, project)
    fake.stories.clear()
    fake.projects.clear()
    second = push(client, project)
    assert second["results"][0]["outcome"] == "created"
    assert second["tracker_project_id"] != first["tracker_project_id"]
    assert len(fake.stories) == 1


def test_stories_without_criteria_are_skipped_and_subsets_can_be_sent(client, project, fake):
    empty = add(client, project, criteria=[])
    full = add(client, project, action="registreeruda")
    report = push(client, project)
    assert [(r["key"], r["outcome"]) for r in report["results"]] == [("US-1", "skipped"), ("US-2", "created")]
    assert "criterion" in report["results"][0]["message"]
    only = push(client, project, story_ids=[full["id"]])
    assert [r["key"] for r in only["results"]] == ["US-2"]
    assert client.post(f"{base(project)}/tracker/push", json={"story_ids": [999]}).status_code == 404
    assert empty


def test_points_follow_the_configured_mapping(client, project, fake, monkeypatch):
    monkeypatch.setenv("TRACKER_POINTS", "S=1,M=3,L=13")
    add(client, project, size="L")
    add(client, project, size=None, action="muu")
    push(client, project)
    assert sorted(s["points"] for s in fake.stories.values()) == [0, 13]


def test_an_unreachable_tracker_gives_a_clear_error(client, project, fake):
    add(client, project)
    fake.down = True
    response = client.post(f"{base(project)}/tracker/push", json={})
    assert response.status_code == 502
    assert response.json()["detail"]["code"] == "tracker_unavailable"
    assert "not reachable" in response.json()["detail"]["message"]


def test_push_is_off_without_tracker_url(client, project, monkeypatch):
    monkeypatch.delenv("TRACKER_URL", raising=False)
    assert client.get("/api/tracker").json() == {"configured": False, "public_url": None}
    response = client.post(f"{base(project)}/tracker/push", json={})
    assert response.status_code == 503 and response.json()["detail"]["code"] == "tracker_off"


def test_undoing_a_delete_keeps_the_tracker_link(client, project, fake):
    story = add(client, project)
    push(client, project)
    client.delete(f"{base(project)}/stories/{story['id']}")
    client.post(f"{base(project)}/undo")
    assert push(client, project)["results"][0]["outcome"] == "updated"
    assert len(fake.stories) == 1


def test_http_transport_builds_multipart_and_reports_unreachable_hosts():
    t = tracker.HttpTransport("http://127.0.0.1:9", timeout=1)  # port 9: nothing listens
    with pytest.raises(tracker.TrackerError, match="not reachable"):
        t.request("GET", "/api/projects/1")
