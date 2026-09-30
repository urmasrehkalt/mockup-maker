import io

import pytest
from PIL import Image
from pydantic import ValidationError

from app import mockup_png, mockups
from app.mockup_templates import TEMPLATES
from tests.test_tracker import FakeTracker

STORY = {"role_name": "Külastaja", "role_phrase": "Külastajana", "action": "näha pakette", "benefit": "valida",
         "criteria": ["Lehel on iga paketi nimi."]}
RECT = {"id": "a1", "tool": "rect", "anchor": "packages", "points": [[0, 0], [60, 40]], "color": "red"}
NOTE = {"id": "a2", "tool": "note", "anchor": "pricing-title", "points": [[300, 0]], "text": "Lisa „sh km“!", "color": "blue"}


@pytest.fixture
def project(client):
    return client.post("/api/projects", json={"name": "P"}).json()


def base(project):
    return f"/api/projects/{project['id']}"


@pytest.fixture
def mockup(client, project):
    story = client.post(f"{base(project)}/stories", json=STORY).json()
    return client.post(f"{base(project)}/mockups", json={"template": "pricing", "story_id": story["id"]}).json()


def annotate(client, project, mockup, marks):
    return client.put(f"{base(project)}/mockups/{mockup['id']}/annotations", json={"annotations": marks})


# --- the model -------------------------------------------------------------

@pytest.mark.parametrize("mark, message", [
    ({"id": "x", "tool": "rect", "points": [[0, 0]]}, "needs 2 points"),
    ({"id": "x", "tool": "pen", "points": [[0, 0]]}, "needs 2 to 500"),
    ({"id": "x", "tool": "note", "points": [[0, 0]]}, "needs text"),
    ({"id": "x", "tool": "circle", "points": [[0, 0], [1, 1]]}, "tool"),
    ({"id": "x", "tool": "rect", "points": [[0, 0], [1, 1]], "html": "<b>"}, "html"),
    ({"id": "x", "tool": "rect", "points": [[0, 0], [1, 99999]]}, "out of range"),
    ({"id": "x", "tool": "rect", "points": [[0, 0], [1, 1]], "color": "pink"}, "color"),
])
def test_invalid_annotations_are_rejected(mark, message):
    with pytest.raises(ValidationError) as info:
        mockups.Annotation(**mark)
    assert message in str(info.value)


def test_annotation_ids_must_be_unique():
    with pytest.raises(ValidationError):
        mockups.AnnotationsIn(annotations=[RECT, {**NOTE, "id": "a1"}])


# --- storage ---------------------------------------------------------------

def test_saving_annotations_makes_a_version_with_the_same_view(client, project, mockup):
    saved = annotate(client, project, mockup, [RECT, NOTE]).json()
    assert saved["version"] == 2 and saved["tree"] == mockup["tree"]
    assert [a["id"] for a in saved["annotations"]] == ["a1", "a2"]
    versions = client.get(f"{base(project)}/mockups/{mockup['id']}/versions").json()
    assert versions[-1]["note"] == "annotations" and versions[0]["annotations"] == []
    assert annotate(client, project, mockup, saved["annotations"]).json()["version"] == 2  # unchanged


def test_annotations_survive_a_new_layout_and_restore_brings_old_ones_back(client, project, mockup):
    annotate(client, project, mockup, [RECT])
    tree = {**mockup["tree"], "components": [c for c in mockup["tree"]["components"] if c["id"] != "footer"]}
    edited = client.post(f"{base(project)}/mockups/{mockup['id']}/versions", json={"tree": tree}).json()
    assert [a["id"] for a in edited["annotations"]] == ["a1"]  # carried forward
    restored = client.post(f"{base(project)}/mockups/{mockup['id']}/versions/1/restore").json()
    assert restored["annotations"] == []  # version 1 had none


def test_annotating_can_be_undone(client, project, mockup):
    annotate(client, project, mockup, [RECT])
    assert client.get(base(project)).json()["undo"]["action"] == "mockup_annotated"
    client.post(f"{base(project)}/undo")
    current = client.get(base(project)).json()["mockups"][0]
    assert current["version"] == 1 and current["annotations"] == []


def test_markup_in_a_note_is_kept_as_text(client, project, mockup):
    evil = {**NOTE, "text": "<script>alert(1)</script>"}
    saved = annotate(client, project, mockup, [evil]).json()
    assert saved["annotations"][0]["text"] == "<script>alert(1)</script>"


# --- PNG -------------------------------------------------------------------

def test_png_draws_annotations_at_their_anchor():
    tree = mockups.Tree(**TEMPLATES["pricing"][1])
    measure = mockup_png.Painter(None)
    measure.stack(tree.components, mockup_png.PAD, mockup_png.PAD, mockup_png.WIDTH - 2 * mockup_png.PAD)
    x, y, _, _ = measure.boxes["packages"]
    plain = Image.open(io.BytesIO(mockup_png.render_png(tree)))
    marked = Image.open(io.BytesIO(mockup_png.render_png(tree, [mockups.Annotation(**RECT)])))
    corner = (int(x) + 1, int(y) + 20)  # on the rectangle's left edge
    assert plain.getpixel(corner) != marked.getpixel(corner)
    assert marked.getpixel(corner) == mockup_png.MARK_COLORS["red"]


def test_a_missing_anchor_falls_back_to_the_whole_view():
    mark = mockups.Annotation(**{**RECT, "anchor": "gone"})
    assert mockup_png.absolute(mark, {"packages": (100, 100, 10, 10)}) == [(0, 0), (60, 40)]


def test_a_note_below_the_content_makes_the_image_taller():
    tree = mockups.Tree(**TEMPLATES["confirmation"][1])
    low = mockups.Annotation(id="n", tool="note", points=[(40, 900)], text="Siia lisada kontakt")
    assert Image.open(io.BytesIO(mockup_png.render_png(tree, [low]))).size[1] > 900


def test_the_tracker_gets_the_annotated_image(client, project, mockup, monkeypatch):
    from app import tracker
    fake = FakeTracker()
    monkeypatch.setenv("TRACKER_URL", "http://fake")
    monkeypatch.setattr(tracker, "transport", lambda: fake)
    client.post(f"{base(project)}/tracker/push", json={})
    annotate(client, project, mockup, [RECT])
    report = client.post(f"{base(project)}/tracker/push", json={}).json()
    assert report["results"][0]["mockup"] == "uploaded"
