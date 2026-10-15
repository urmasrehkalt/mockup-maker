"""#34: a `row` container places components side by side, in every layer that draws or edits a mockup."""
import io
import json
import shutil
import subprocess
from pathlib import Path

import pytest
from PIL import Image
from pydantic import ValidationError

from app import mockup_chat, mockups
from app.ai import providers
from app.mockup_png import Painter, render_png
from tests.test_conversation import Recorder
from tests.test_mockup_chat import project, say, setup  # noqa: F401  (fixtures)

PUBLIC = Path(__file__).resolve().parent.parent / "public" / "js"


def button(id_, text="Ava kaamera"):
    return {"id": id_, "type": "button", "text": text}


def photo_row(id_="photo-row"):
    """The field case: buttons in a section, the photo to their right."""
    return {"id": id_, "type": "row", "children": [
        {"id": "photo-actions", "type": "section", "children": [button("take-photo"), button("change-photo", "Muuda fotot")]},
        {"id": "photo-preview", "type": "image", "text": "Portreefoto eelvaade"}]}


def tree(*components):
    return {"title": "Koera registreerimine", "components": list(components)}


def problems(data):
    with pytest.raises(ValidationError) as info:
        mockups.Tree.model_validate(data)
    return str(info.value)


# --- the rules -----------------------------------------------------------

def test_a_row_of_buttons_and_a_photo_is_valid():
    parsed = mockups.Tree.model_validate(tree(photo_row()))
    assert parsed.components[0].type == "row"


def test_a_row_may_hold_any_component_types_and_other_rows():
    inner = {"id": "inner", "type": "row", "children": [button("a"), button("b")]}
    row = {"id": "outer", "type": "row", "children": [
        inner, {"id": "t", "type": "text", "text": "x"}, {"id": "i", "type": "input", "text": "Nimi", "variant": "text"}]}
    mockups.Tree.model_validate(tree(row))


@pytest.mark.parametrize("count", [0, 1, 5])
def test_a_row_needs_two_to_four_children(count):
    row = {"id": "r", "type": "row", "children": [button(f"b{i}") for i in range(count)] or None}
    assert "a row needs 2 to 4 children" in problems(tree(row))


def test_two_and_four_children_are_fine():
    for count in (2, 4):
        mockups.Tree.model_validate(tree({"id": "r", "type": "row", "children": [button(f"b{i}") for i in range(count)]}))


def test_the_grid_rule_is_unchanged():
    grid = {"id": "g", "type": "grid", "children": [{"id": "s", "type": "section", "children": [button("b")]}]}
    assert "a grid may only hold" in problems(tree(grid))


def test_a_row_is_saved_and_served_through_the_api(client, project, setup):  # noqa: F811
    story, mockup = setup
    row_tree = {**mockup["tree"], "components": [*mockup["tree"]["components"], photo_row()]}
    saved = client.post(f"/api/projects/{project['id']}/mockups/{mockup['id']}/versions", json={"tree": row_tree})
    assert saved.status_code == 200, saved.text
    assert "photo-row" in str(saved.json()["tree"])
    bad = {**row_tree, "components": [*mockup["tree"]["components"], {"id": "lonely", "type": "row", "children": [button("x")]}]}
    assert client.post(f"/api/projects/{project['id']}/mockups/{mockup['id']}/versions", json={"tree": bad}).status_code == 422


def test_the_ai_chat_can_answer_with_a_row(client, project, setup, monkeypatch):  # noqa: F811
    story, mockup = setup
    recorder = Recorder()
    monkeypatch.setattr(providers, "get", lambda name=None: recorder)

    def answer(payload):
        reply = mockup_chat.mock_edit(payload)
        reply["mockup"] = {**reply["mockup"], "components": [*reply["mockup"]["components"], photo_row()]}
        return reply

    recorder.override = answer
    result = say(client, project, mockup, text="Pane foto nuppudest paremale")
    assert result.status_code == 200, result.text
    assert "photo-row" in str(result.json()["mockup"]["tree"])


def test_the_instructions_tell_the_ai_about_row():
    from app import conversation
    for text in (conversation.INSTRUCTIONS, mockup_chat.INSTRUCTIONS):
        flat = " ".join(text.split())
        assert "use a row with 2 to 4 children" in flat and "side by side" in flat


# --- the PNG layout --------------------------------------------------------

def laid_out(*components):
    parsed = mockups.Tree.model_validate(tree(*components))
    painter = Painter(None)
    painter.stack(parsed.components, 0, 0, 800)
    return painter.boxes


def test_png_children_of_a_row_sit_side_by_side_in_equal_columns():
    boxes = laid_out(photo_row())
    left, right = boxes["photo-actions"], boxes["photo-preview"]
    assert left[1] == right[1]                      # same top
    assert right[0] > left[0] + left[2]             # the second starts after the first ends
    assert left[2] == pytest.approx(right[2])       # equal columns
    assert boxes["photo-row"][2] == 800 and boxes["photo-row"][3] == max(left[3], right[3])


def test_png_cards_in_a_row_share_the_tallest_ones_height():
    short = {"id": "a", "type": "card", "text": "Lühike"}
    tall = {"id": "b", "type": "card", "text": "Pikk", "secondary": "kirjeldus " * 30}
    boxes = laid_out({"id": "r", "type": "row", "children": [short, tall]})
    assert boxes["a"][3] == boxes["b"][3] > 0


def test_png_row_is_shorter_than_the_same_components_stacked():
    def height(*components):
        png = render_png(mockups.Tree.model_validate(tree(*components)))
        return Image.open(io.BytesIO(png)).size[1]
    stacked = [{"id": "s", "type": "section", "children": [button("b1"), button("b2")]},
               {"id": "i", "type": "image", "text": "Foto"}]
    assert height(photo_row()) < height(*stacked)


# --- the editor's tree operations and the renderer (run with node) -----------

NODE = shutil.which("node")


def run_node(script: str):
    result = subprocess.run([NODE, "--input-type=module", "-e", script], capture_output=True, text=True,
                            timeout=30, cwd=PUBLIC)
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout)


@pytest.mark.skipif(NODE is None, reason="node is not installed")
def test_the_editor_treats_a_row_as_a_container_that_takes_anything():
    out = run_node(f"""
import * as ops from "{PUBLIC}/mockup/tree-ops.js";
const tree = {{ title: "T", components: [{json.dumps(photo_row())}, {{ id: "t", type: "text", text: "x" }}] }};
const btn = {{ id: "new-button", type: "button", text: "Nupp" }};
const result = {{
  container: ops.CONTAINERS.has("row"),
  rowTakesButton: ops.fits(btn, {{ type: "row" }}),
  gridTakesButton: ops.fits(btn, {{ type: "grid" }}),
}};
result.placed = ops.place(tree, btn, "photo-row", {{ into: true }});
result.rowChildren = ops.locate(tree, "photo-row").node.children.map((c) => c.id);
ops.move(tree, "new-button", null);
result.afterMove = ops.locate(tree, "photo-row").node.children.map((c) => c.id);
result.topLevel = tree.components.map((c) => c.id);
console.log(JSON.stringify(result));
""")
    assert out["container"] and out["rowTakesButton"] and not out["gridTakesButton"]
    assert out["placed"] and out["rowChildren"] == ["photo-actions", "photo-preview", "new-button"]
    assert out["afterMove"] == ["photo-actions", "photo-preview"] and out["topLevel"][-1] == "new-button"


@pytest.mark.skipif(NODE is None, reason="node is not installed")
def test_the_browser_renders_a_row_with_its_children_in_it():
    out = run_node(f"""
class Node {{}}
globalThis.Node = Node;
class El extends Node {{
  constructor(tag) {{ super(); this.tag = tag; this.className = ""; this.dataset = {{}}; this.children = []; this.attrs = {{}}; }}
  setAttribute(k, v) {{ this.attrs[k] = v; }}
  addEventListener() {{}}
  append(...nodes) {{ this.children.push(...nodes); }}
}}
globalThis.document = {{ createElement: (tag) => new El(tag), createTextNode: (text) => ({{ text }}) }};
const {{ renderTree }} = await import("{PUBLIC}/mockup/render.js");
const view = renderTree({json.dumps(tree(photo_row()))});
const row = view.children[0];
console.log(JSON.stringify({{ cls: row.className, id: row.dataset.componentId, type: row.dataset.componentType,
  kids: row.children.map((c) => [c.dataset.componentId, c.dataset.componentType]) }}));
""")
    assert out == {"cls": "wf-row", "id": "photo-row", "type": "row",
                   "kids": [["photo-actions", "section"], ["photo-preview", "image"]]}


def test_the_row_has_styles_stacks_on_a_phone_and_is_named_in_both_languages():
    css = (PUBLIC.parent / "styles.css").read_text()
    assert ".wf-row {" in css and ".wf-mobile .wf-row" in css
    i18n = (PUBLIC / "i18n.js").read_text()
    et, en = i18n.split("\n  en: {", 1)
    assert '"component.row"' in et and '"component.row"' in en
    editor = (PUBLIC / "mockup" / "editor.js").read_text()
    assert editor.count("row: {}") == 2  # a sample in each content language
