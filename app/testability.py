"""Rule-based testability check for acceptance criteria.

A criterion should be ONE simple condition that can be answered yes or no.
Three rules catch the common ways it fails, in Estonian and English:

- evaluative words ("kasutajasõbralik", "kiire", "selgelt", "user-friendly"):
  a quality, not a check;
- several conditions in one ("kontrollib andmeid ja saadab meili"): split it;
- vague phrases ("võimalikult", "jne", "vajadusel"): no clear yes or no.

Estonian inflects heavily, so evaluative words are matched by stem prefix
("lihts" covers lihtne, lihtsalt, lihtsa ...); short words that would match
too much as prefixes are listed as exact forms. This is deliberately simple:
it warns, a human decides.
"""
from __future__ import annotations

import re
from typing import Literal

from fastapi import APIRouter
from pydantic import BaseModel, ConfigDict, Field

IssueCode = Literal["evaluative", "multiple", "vague"]

EVALUATIVE_STEMS = (
    # Estonian
    "kasutajasõbralik", "kiire", "lihts", "lihtn", "mugav", "intuitiiv", "selge", "arusaadav",
    "ilus", "kaasaegn", "moodn", "sujuv", "efektiivn", "tõhus", "piisav", "optimaaln", "meeldiv",
    "ülevaatlik", "kergesti", "atraktiivn", "professionaaln", "loogilis", "paindlik", "hõlpsa",
    "kena", "korralik", "silmapaistev",
    # English
    "user-friendly", "userfriendly", "fast", "quick", "simpl", "easy", "easil", "convenient",
    "intuitive", "clear", "nice", "modern", "seamless", "efficient", "beautiful", "attractive",
    "friendly", "smooth", "adequate", "appropriate", "sufficient", "intuitiv",
)
EVALUATIVE_WORDS = {"hea", "head", "hästi", "parem", "good", "well", "better", "great"}
VAGUE_WORDS = {"võimalikult", "jne", "vms", "jms", "piisavalt", "vajadusel", "üldiselt",
               "tavaliselt", "enamasti", "mõistlik", "mõistlikult", "etc", "possibly", "usually",
               "generally", "mostly", "reasonable", "reasonably"}
VAGUE_PHRASES = ("as possible", "if needed", "and so on", "kui vaja")
JOINERS = {"ja", "ning", "and", "samuti", "also"}

WORD = re.compile(r"[a-zA-ZõäöüšžÕÄÖÜŠŽ][a-zA-Z0-9õäöüšžÕÄÖÜŠŽ-]*")
SENTENCE_BREAK = re.compile(r"[.!?;]\s+\S")


class Issue(BaseModel):
    code: IssueCode
    words: list[str]


def check(text: str) -> list[Issue]:
    lowered = text.lower()
    words = WORD.findall(lowered)
    issues: list[Issue] = []

    evaluative = [w for w in words if w in EVALUATIVE_WORDS or w.startswith(EVALUATIVE_STEMS)]
    if evaluative:
        issues.append(Issue(code="evaluative", words=_unique(evaluative)))

    joiners = [w for w in words if w in JOINERS]
    if joiners or SENTENCE_BREAK.search(text.strip()):
        issues.append(Issue(code="multiple", words=_unique(joiners)))

    vague = [w for w in words if w in VAGUE_WORDS] + [p for p in VAGUE_PHRASES if p in lowered]
    if vague:
        issues.append(Issue(code="vague", words=_unique(vague)))
    return issues


def describe(text: str, issues: list[Issue]) -> str:
    """One line for the AI's retry feedback."""
    reasons = []
    for issue in issues:
        words = ", ".join(issue.words)
        if issue.code == "evaluative":
            reasons.append(f"uses evaluative words ({words}) that cannot be checked with yes or no")
        elif issue.code == "multiple":
            reasons.append("joins several conditions" + (f" ({words})" if words else "")
                           + "; split it into separate criteria")
        else:
            reasons.append(f"uses vague wording ({words})")
    return f"{text!r} " + "; ".join(reasons)


def _unique(items: list[str]) -> list[str]:
    return list(dict.fromkeys(items))


# --- API -----------------------------------------------------------------

class CheckIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    texts: list[str] = Field(max_length=50)


router = APIRouter(tags=["criteria"])


@router.post("/api/criteria/check", response_model=list[list[Issue]])
def post_check(data: CheckIn):
    return [check(text[:500]) for text in data.texts]

