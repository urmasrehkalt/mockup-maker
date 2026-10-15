"""#33: a layout request must not fail on a rule the AI was never told about."""
import logging
import re

from app import conversation, mockups
from tests.test_conversation import turn
from tests.test_refinement import PRICING, ai, base, prepared, project, refine  # noqa: F401


def grid_with_section(answer):
    """What the model built in the field: buttons in a section inside a grid."""
    if not answer["change"]:
        return answer
    change = dict(answer["change"])
    components = list(change["mockup"]["components"])
    components.append({"id": "photo-layout", "type": "grid", "columns": 2, "children": [
        {"id": "photo-actions", "type": "section", "children": [
            {"id": "take-photo", "type": "button", "text": "Ava kaamera"}]},
        {"id": "photo-preview", "type": "image", "text": "Portreefoto eelvaade"}]})
    change["mockup"] = {**change["mockup"], "components": components}
    return {**answer, "change": change}


def test_instructions_name_what_a_grid_may_hold():
    text = " ".join(conversation.INSTRUCTIONS.split())
    rule = re.search(r"grid[^.]*\bonly\b[^.]*\.", text)
    assert rule, "the instructions must say what a grid may hold"
    assert all(kind in rule.group(0) for kind in mockups.GRID_CHILDREN)


def test_instructions_say_how_to_place_things_side_by_side():
    text = " ".join(conversation.INSTRUCTIONS.split())
    assert "side by side" in text


def test_a_grid_with_a_section_is_rejected_and_the_retry_shows_the_problem(client, project, ai):
    pricing = prepared(client, project, PRICING)
    spoiled = []

    def answer(payload):
        reply = conversation.mock_turn(payload)
        if reply["change"] and not spoiled:
            spoiled.append(payload)
            return grid_with_section(reply)
        return reply

    ai.override = answer
    message = refine(client, project, pricing)
    assert message["content"]["change"]["summary"]
    retried = [p for p in ai.prompts if "rejected by the server" in p]
    assert retried and "a grid may only hold" in retried[0]


def test_a_rejected_ai_answer_is_logged_with_its_reason(client, project, ai, caplog):
    pricing = prepared(client, project, PRICING)
    ai.override = lambda payload: grid_with_section(conversation.mock_turn(payload))
    caplog.set_level(logging.WARNING)
    turn(client, project, kind="focus", story_id=pricing["id"])
    client.patch(base(project), json={"step": "refinements"})
    response = turn(client, project, kind="text", text="Foto paremale")
    assert response.status_code == 502
    logged = " ".join(r.getMessage() for r in caplog.records)
    assert "turn" in logged and "a grid may only hold" in logged
