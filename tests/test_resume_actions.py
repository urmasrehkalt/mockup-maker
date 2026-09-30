"""Every resume action the server offers must have a label and a handler in the UI (#26)."""
import re
from pathlib import Path

from app import projects

PUBLIC = Path(__file__).resolve().parent.parent / "public" / "js"


def _object_keys(source: str, name: str) -> set[str]:
    body = re.search(rf"const {name} = \{{(.*?)\n\}};", source, re.S)
    assert body, f"{name} not found"
    return set(re.findall(r"^\s{2}(\w+):", body.group(1), re.M))


def _offered() -> set[str]:
    return {action for actions in projects.RESUME_ACTIONS.values() for action in actions}


def test_every_resume_action_has_a_handler():
    handled = _object_keys((PUBLIC / "views" / "chat.js").read_text(), "RESUME")
    assert _offered() - handled == set()


def test_every_resume_action_has_a_label_in_both_languages():
    source = (PUBLIC / "i18n.js").read_text()
    et, en = source.split("\n  en: {", 1)
    for language, block in (("et", et), ("en", en.split("\n  },")[0])):
        labelled = set(re.findall(r'"action\.(\w+)":', block))
        assert _offered() - labelled == set(), language
