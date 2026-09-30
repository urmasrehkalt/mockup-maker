"""Mockups shown in a browser or phone frame (#29).

The frame is presentation only: the tree and its versions do not change. The
PNG export and the tracker push add a browser frame when asked to.
"""
import io
import re
from pathlib import Path

import pytest
from PIL import Image

from app import mockup_png
from app.mockup_templates import TEMPLATES
from app.mockups import Tree
from tests.test_tracker import add, base, fake, push  # noqa: F401 (fixture)

PUBLIC = Path(__file__).resolve().parent.parent / "public" / "js"


@pytest.fixture
def project(client):
    return client.post("/api/projects", json={"name": "E-pood Õun"}).json()


def size(data: bytes) -> tuple[int, int]:
    return Image.open(io.BytesIO(data)).size


@pytest.mark.parametrize("name, title, language, address", [
    ("E-pood", "E-poe avaleht", "et", "e-pood.ee/e-poe-avaleht"),
    ("Spordiklubi Õun", "Hinnakiri", "en", "spordiklubi-oun.com/hinnakiri"),
    ("  ", "Žürii & „tulemused“", "et", "example.ee/zurii-tulemused"),
    ("Kohvik", "", "et", "kohvik.ee"),
])
def test_the_address_comes_from_the_project_and_view(name, title, language, address):
    assert mockup_png.site_address(name, title, language) == address


def test_a_framed_png_is_the_same_view_under_a_browser_bar():
    tree = Tree(**TEMPLATES["pricing"][1])
    plain = Image.open(io.BytesIO(mockup_png.render_png(tree)))
    framed = Image.open(io.BytesIO(mockup_png.render_png(tree, address="e-pood.ee/hinnakiri")))
    assert plain.size[1] < 640  # short enough for the window's minimum to show
    assert framed.size == (plain.size[0] + 2, 640 + mockup_png.FRAME_BAR + 1)
    view = framed.crop((1, mockup_png.FRAME_BAR, 1 + plain.size[0], mockup_png.FRAME_BAR + plain.size[1]))
    assert view.tobytes() == plain.convert("RGB").tobytes()
    assert framed.getpixel((framed.size[0] // 2, 4)) == mockup_png.SOFT
    assert framed.getpixel((framed.size[0] // 2, framed.size[1] - 3)) == mockup_png.WHITE


def test_a_framed_window_is_at_least_16_by_10_and_long_pages_grow():
    long = Tree(title="Pikk", components=[{"id": f"t{i}", "type": "text", "text": "Rida " * 60} for i in range(20)])
    plain = Image.open(io.BytesIO(mockup_png.render_png(long)))
    framed = Image.open(io.BytesIO(mockup_png.render_png(long, address="x.ee")))
    assert plain.size[1] > 640 and framed.size[1] == plain.size[1] + mockup_png.FRAME_BAR + 1


def test_png_download_is_framed_only_when_asked(client, project):
    story = add(client, project)
    mockup = client.post(f"{base(project)}/mockups", json={"template": "pricing", "story_id": story["id"]}).json()
    url = f"{base(project)}/mockups/{mockup['id']}/png"
    plain, framed = client.get(url).content, client.get(f"{url}?frame=true&version=1").content
    assert size(plain)[0] == 1024 and size(framed)[0] == 1026
    assert client.get(f"{url}?frame=maybe").status_code == 422


def test_tracker_push_follows_the_frame_choice(client, project, fake):  # noqa: F811
    story = add(client, project)
    client.post(f"{base(project)}/mockups", json={"template": "pricing", "story_id": story["id"]})
    first = push(client, project)["results"][0]
    assert size(fake.images[first["tracker_id"]][1])[0] == 1024
    assert push(client, project, frame=True)["results"][0]["mockup"] == "uploaded"
    assert size(fake.images[first["tracker_id"]][1])[0] == 1026
    assert push(client, project, frame=True)["results"][0]["mockup"] == "unchanged"


def test_every_literal_ui_key_exists_in_both_languages():
    source = (PUBLIC / "i18n.js").read_text()
    et, en = source.split("\n  en: {", 1)
    keys = {"et": set(re.findall(r'^\s{4}"([\w.]+)":', et, re.M)),
            "en": set(re.findall(r'^\s{4}"([\w.]+)":', en.split("\n};", 1)[0], re.M))}
    used = set()
    for path in PUBLIC.rglob("*.js"):
        used |= set(re.findall(r'\bt\("([\w.]+)"', path.read_text()))
    assert used, "no t() calls found"
    assert {"mockup.frame", "mockup.frame_hint"} <= used
    for language, known in keys.items():
        assert used - known == set(), language
