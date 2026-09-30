"""AI backlog review: findings with a concrete proposal each, applied only on request.

The review is its own AI task, not a conversation turn. The model gets the whole
backlog, including what the server already knows by rule (untestable criteria,
too few criteria, a missing mockup, malformed Connextra parts), and returns
findings. Each finding carries exactly one proposal of the kind that fits it.

The review is stored as an assistant message, so it stays in the conversation;
every finding is applied or ignored on its own. Applying goes through the same
backlog operations as manual grooming, so it is checked and can be undone.
"""
from __future__ import annotations

import re
import sqlite3
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field, model_validator

from . import backlog, db, mockups, projects, testability
from .ai import Task, run_task
from .mockup_templates import TEMPLATES

FindingKind = Literal["too_large", "overlap", "untestable_criteria", "missing_criteria",
                      "no_mockup", "not_connextra"]
TemplateKey = Literal[tuple(TEMPLATES)]  # type: ignore[valid-type]
Text = Annotated[str, Field(min_length=1, max_length=300)]


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class Wording(_Strict):
    role_phrase: str = Field(min_length=1, max_length=80)
    action: str = Field(min_length=1, max_length=300)
    benefit: str = Field(min_length=1, max_length=300)


class SplitPart(Wording):
    criteria: list[int] = Field(max_length=30)  # indexes into the story's criteria
    new_criteria: list[Text] = Field(max_length=10)


class SplitProposal(_Strict):
    parts: list[SplitPart] = Field(min_length=2, max_length=5)


class MergeProposal(_Strict):
    keep_key: str
    remove_key: str
    wording: Wording | None
    criteria: list[Text] = Field(min_length=1, max_length=30)  # merged, without duplicates


class CriteriaProposal(_Strict):
    criteria: list[Text] = Field(min_length=1, max_length=30)  # the story's full new list


class MockupProposal(_Strict):
    template: TemplateKey
    title: str = Field(min_length=1, max_length=120)


PROPOSAL_FOR = {"too_large": "split", "overlap": "merge", "untestable_criteria": "criteria",
                "missing_criteria": "criteria", "no_mockup": "mockup", "not_connextra": "wording"}


class Finding(_Strict):
    kind: FindingKind
    story_keys: list[str] = Field(min_length=1, max_length=2)
    problem: str = Field(min_length=1, max_length=300)
    reason: str = Field(min_length=1, max_length=400)
    split: SplitProposal | None = None
    merge: MergeProposal | None = None
    criteria: CriteriaProposal | None = None
    mockup: MockupProposal | None = None
    wording: Wording | None = None

    @model_validator(mode="after")
    def _one_matching_proposal(self):
        given = [name for name in ("split", "merge", "criteria", "mockup", "wording") if getattr(self, name)]
        if given != [PROPOSAL_FOR[self.kind]]:
            raise ValueError(f"a {self.kind} finding needs exactly one proposal, `{PROPOSAL_FOR[self.kind]}`")
        return self


class Review(_Strict):
    summary: str = Field(min_length=1, max_length=600)
    findings: list[Finding] = Field(max_length=15)


INSTRUCTIONS = """\
Review the whole backlog in INPUT.backlog like an experienced product owner before a grooming
session, and return findings. Look for at least:
- too_large: a story with several roles or several separate actions, or very many criteria.
  Propose `split`: 2 to 5 parts, each one role and one goal, with the story's criteria distributed
  by their index (`criteria`), every index in at most one part, plus `new_criteria` if a part needs
  its own. Keep role_phrase in the same form as the story.
- overlap: two stories that mean essentially the same thing. Propose `merge`: keep_key, remove_key,
  optional new `wording`, and the merged `criteria` list without duplicates.
- untestable_criteria / missing_criteria: criteria that cannot be answered yes or no (see each
  criterion's `issues`), or fewer than 3 criteria. Propose `criteria`: the story's FULL new list,
  each one simple condition checkable with yes or no.
- no_mockup: a story with needs_view true and has_mockup false. Propose `mockup`: the best fitting
  template from INPUT.templates and a title for the view.
- not_connextra: a story whose parts do not read as "<role_phrase> soovin <action>, et <benefit>"
  (see missing_for_ready "connextra"). Propose `wording`.
Every story with a rule-based problem in missing_for_ready (connextra, criteria_count,
criteria_testable, mockup) needs a finding. One finding per problem; story_keys names the
stories it is about. Write problem, reason and all texts in the language given by
INPUT.language (et = Estonian, en = English). `summary` says in one or two sentences how the
backlog looks. If everything is fine, return no findings."""


# --- payload and checks --------------------------------------------------

def build_payload(conn: sqlite3.Connection, project_id: int) -> dict[str, Any]:
    stories = backlog.stories(conn, project_id)
    return {
        "language": "et",
        "templates": {key: name for key, (name, _) in TEMPLATES.items()},
        "backlog": [{
            "key": s.key, "role_name": s.role_name, "role_phrase": s.role_phrase, "action": s.action,
            "benefit": s.benefit, "title": s.title, "status": s.status, "in_mvp": s.in_mvp,
            "needs_view": s.needs_view, "has_mockup": bool(s.mockup_ids),
            "missing_for_ready": [m.code for m in s.readiness],
            "criteria": [{"index": i, "text": c.text, "issues": [x.code for x in c.issues]}
                         for i, c in enumerate(s.criteria)],
        } for s in stories],
    }


RULE_CODES = {"connextra": "not_connextra", "criteria_count": "missing_criteria",
              "criteria_testable": "untestable_criteria", "mockup": "no_mockup"}
COVERS = {"not_connextra": {"not_connextra"}, "missing_criteria": {"missing_criteria", "untestable_criteria", "too_large"},
          "untestable_criteria": {"untestable_criteria", "missing_criteria", "too_large"},
          "no_mockup": {"no_mockup"}}


def uncovered(review: Review, payload: dict[str, Any]) -> list[tuple[str, str]]:
    """(story key, finding kind) pairs the server knows about but the review missed."""
    found = {(key, f.kind) for f in review.findings for key in f.story_keys}
    missing = []
    for story in payload["backlog"]:
        for code in story["missing_for_ready"]:
            kind = RULE_CODES.get(code)
            if kind and not any((story["key"], k) in found for k in COVERS[kind]):
                missing.append((story["key"], kind))
    return missing


def check_review(review: Review, payload: dict[str, Any]) -> str | None:
    by_key = {s["key"]: s for s in payload["backlog"]}
    for f in review.findings:
        unknown = [k for k in f.story_keys if k not in by_key]
        if unknown:
            return f"Finding refers to stories that are not in the backlog: {unknown}."
        story = by_key[f.story_keys[0]]
        if f.split:
            indexes = [i for part in f.split.parts for i in part.criteria]
            if len(set(indexes)) != len(indexes) or not all(0 <= i < len(story["criteria"]) for i in indexes):
                return (f"Split of {story['key']}: each criterion index (0 to {len(story['criteria']) - 1}) "
                        "may appear in one part at most.")
        if f.merge:
            keys = {f.merge.keep_key, f.merge.remove_key}
            if len(keys) != 2 or not keys <= set(by_key):
                return "A merge needs two different stories from the backlog as keep_key and remove_key."
        texts = [*(f.criteria.criteria if f.criteria else []), *(f.merge.criteria if f.merge else []),
                 *(t for part in (f.split.parts if f.split else []) for t in part.new_criteria)]
        untestable = [testability.describe(t, issues) for t in texts if (issues := testability.check(t))]
        if untestable:
            return ("Proposed criteria must be answerable with yes or no: " + " | ".join(untestable) + ".")
    missed = uncovered(review, payload)
    if missed:
        return ("These known problems have no finding: "
                + ", ".join(f"{key} ({kind})" for key, kind in missed) + ".")
    return None


# --- a stand-in review, and filling gaps by rule ----------------------------

def _rule_finding(story: dict[str, Any], kind: str) -> dict[str, Any]:
    """A finding the server can propose on its own for a known problem."""
    base = {"kind": kind, "story_keys": [story["key"]], "split": None, "merge": None,
            "criteria": None, "mockup": None, "wording": None}
    testable = [c["text"] for c in story["criteria"] if not c["issues"]]
    if kind in ("untestable_criteria", "missing_criteria"):
        fillers = ["Vaates on pealkiri.", "Vaates on nupp põhitegevuse jaoks.", "Pärast tegevust kuvatakse kinnitus."]
        proposed = testable + [f for f in fillers if f not in testable][:max(0, 3 - len(testable))]
        return {**base, "problem": "Kriteeriumid on puudulikud või mittekontrollitavad.",
                "reason": "Iga kriteerium peab olema üks jah/ei tingimus ja neid peab olema vähemalt kolm.",
                "criteria": {"criteria": proposed}}
    if kind == "no_mockup":
        return {**base, "problem": "Vaadet puudutaval lool puudub mockup.",
                "reason": "Klient ei saa lugu visuaalselt kontrollida.",
                "mockup": {"template": "detail", "title": story["action"][:120]}}
    return {**base, "problem": "Pealkiri ei ole Connextra vormis.",
            "reason": "Rolli, tegevuse ja kasu osad peavad lauses olema eraldi.",
            "wording": {"role_phrase": re.sub(r"\s*soovin$", "", story["role_phrase"]).strip() or story["role_phrase"],
                        "action": re.sub(r"^(soovin|tahan)\s+", "", story["action"]),
                        "benefit": re.sub(r"^(et|selleks et)\s+", "", story["benefit"])}}


def _words(text: str) -> set[str]:
    return {w for w in re.findall(r"\w+", text.lower()) if len(w) > 3}


def mock_review(payload: dict[str, Any]) -> dict[str, Any]:
    """A deterministic review: the rule-based problems plus simple size and overlap signals."""
    findings = []
    stories = payload["backlog"]
    for story in stories:
        if " ja " in f" {story['action']} " and len(story["criteria"]) >= 2:
            first, _, second = story["action"].partition(" ja ")
            half = len(story["criteria"]) // 2
            findings.append({"kind": "too_large", "story_keys": [story["key"]],
                             "problem": "Lugu sisaldab mitut eraldi tegevust.",
                             "reason": "Kaks tegevust ühes loos on raske hinnata ja testida.",
                             "split": {"parts": [
                                 {"role_phrase": story["role_phrase"], "action": first, "benefit": story["benefit"],
                                  "criteria": list(range(half)), "new_criteria": []},
                                 {"role_phrase": story["role_phrase"], "action": second, "benefit": story["benefit"],
                                  "criteria": list(range(half, len(story["criteria"]))), "new_criteria": []}]},
                             "merge": None, "criteria": None, "mockup": None, "wording": None})
    for i, a in enumerate(stories):
        for b in stories[i + 1:]:
            wa, wb = _words(a["action"]), _words(b["action"])
            if wa and wb and len(wa & wb) / len(wa | wb) >= 0.5:
                seen: dict[str, str] = {}
                for c in a["criteria"] + b["criteria"]:
                    if not c["issues"]:
                        seen.setdefault(backlog._same(c["text"]), c["text"])
                merged = list(seen.values())
                findings.append({"kind": "overlap", "story_keys": [a["key"], b["key"]],
                                 "problem": f"Lood {a['key']} ja {b['key']} kattuvad.",
                                 "reason": "Mõlemad kirjeldavad sisuliselt sama vajadust.",
                                 "merge": {"keep_key": a["key"], "remove_key": b["key"], "wording": None,
                                           "criteria": merged or ["Vaates on pealkiri."]},
                                 "split": None, "criteria": None, "mockup": None, "wording": None})
    draft = Review.model_construct(findings=[Finding.model_construct(**f) for f in findings])
    for key, kind in uncovered(draft, payload):
        findings.append(_rule_finding(next(s for s in stories if s["key"] == key), kind))
    return {"summary": f"Leidsin {len(findings)} kohta, mis vajavad tähelepanu." if findings
            else "Backlog on korras.", "findings": findings}


REVIEW = Task(name="review", instructions=INSTRUCTIONS, response=Review, mock=mock_review)


# --- running and applying --------------------------------------------------

def _stored_finding(conn: sqlite3.Connection, project_id: int, finding: Finding) -> dict[str, Any]:
    """The finding as stored: plus criterion ids at review time, and what a merge drops."""
    data = finding.model_dump()
    data["status"] = "pending"
    stories = {s.key: s for s in backlog.stories(conn, project_id)}
    story = stories[finding.story_keys[0]]
    data["criterion_ids"] = [c.id for c in story.criteria]
    data["before"] = [{"key": stories[k].key, "title": stories[k].title,
                       "criteria": [c.text for c in stories[k].criteria]} for k in finding.story_keys]
    if finding.merge:
        # What the merge leaves out of the two stories' criteria: repeats of an earlier
        # criterion (duplicates), and anything else the proposal drops.
        kept = {backlog._same(t) for t in finding.merge.criteria}
        union = [c.text for k in (finding.merge.keep_key, finding.merge.remove_key) for c in stories[k].criteria]
        seen: set[str] = set()
        data["dropped_duplicates"], data["dropped_other"] = [], []
        for text in union:
            same = backlog._same(text)
            if same in seen:
                data["dropped_duplicates"].append(text)
            elif same not in kept:
                data["dropped_other"].append(text)
            seen.add(same)
    return data


async def run_review(conn: sqlite3.Connection, project_id: int) -> projects.ProjectState:
    projects.get(conn, project_id)
    if not backlog.stories(conn, project_id):
        raise HTTPException(409, "The backlog is empty")
    projects.add_message(conn, project_id, "user", {"input": {"kind": "review"}})
    payload = build_payload(conn, project_id)
    review = await run_task(REVIEW, payload, check=lambda r: check_review(r, payload))
    # Anything the model still missed after the retry is filled in by rule.
    extra = [Finding(**_rule_finding(next(s for s in payload["backlog"] if s["key"] == key), kind))
             for key, kind in uncovered(review, payload)]
    keys = {s["key"] for s in payload["backlog"]}
    valid = [f for f in [*review.findings, *extra]
             if set(f.story_keys) <= keys and (not f.merge or {f.merge.keep_key, f.merge.remove_key} <= keys)]
    with conn:
        conn.execute("UPDATE projects SET step = 'grooming' WHERE id = ?", (project_id,))
    reply = lambda label, step=None: {"label": label, "kind": "reply", "step": step}  # noqa: E731
    projects.add_message(conn, project_id, "assistant", {
        "text": review.summary, "step": "grooming",
        "review": {"findings": [_stored_finding(conn, project_id, f) for f in valid]},
        "next_steps": [reply("Järgmine lugu", "priorities"),
                       {"label": "Lõpetame kohtumise", "kind": "end_meeting", "step": None}],
    })
    return projects.state(conn, project_id)


class FindingDecision(_Strict):
    decision: Literal["apply", "ignore"]
    split: SplitProposal | None = None      # the user's edited proposal, if changed
    merge: MergeProposal | None = None
    criteria: CriteriaProposal | None = None
    mockup: MockupProposal | None = None
    wording: Wording | None = None


def decide(conn: sqlite3.Connection, project_id: int, message_id: int, index: int,
           data: FindingDecision) -> projects.ProjectState:
    message = projects.get_message(conn, project_id, message_id)
    findings = (message.content.get("review") or {}).get("findings")
    if message.role != "assistant" or findings is None:
        raise HTTPException(400, "That message is not a backlog review")
    if not 0 <= index < len(findings):
        raise HTTPException(404, "Finding not found")
    finding = findings[index]
    if finding["status"] != "pending":
        raise HTTPException(409, "That finding was already decided")
    if data.decision == "apply":
        kind = PROPOSAL_FOR[finding["kind"]]
        edited = getattr(data, kind)
        proposal = edited.model_dump() if edited else finding[kind]
        _apply(conn, project_id, finding, kind, proposal)
        finding[kind] = proposal
    finding["status"] = "applied" if data.decision == "apply" else "ignored"
    with conn:
        projects.update_message(conn, message.id, message.content)
    return projects.state(conn, project_id)


def _story(conn: sqlite3.Connection, project_id: int, key: str) -> backlog.Story:
    story = next((s for s in backlog.stories(conn, project_id) if s.key == key), None)
    if story is None:
        raise HTTPException(409, f"Story {key} is no longer in the backlog; run the review again")
    return story


def _apply(conn: sqlite3.Connection, project_id: int, finding: dict, kind: str, proposal: dict) -> None:
    story = _story(conn, project_id, finding["story_keys"][0])
    if kind == "split":
        ids = finding["criterion_ids"]
        if [c.id for c in story.criteria] != ids:
            raise HTTPException(409, f"The criteria of {story.key} changed since the review; run it again")
        parts = [backlog.SplitPart(role_phrase=p["role_phrase"], action=p["action"], benefit=p["benefit"],
                                   criterion_ids=[ids[i] for i in p["criteria"]], new_criteria=p["new_criteria"])
                 for p in proposal["parts"]]
        backlog.split(conn, project_id, story.id, backlog.SplitIn(parts=parts), origin="ai")
    elif kind == "merge":
        keep = _story(conn, project_id, proposal["keep_key"])
        remove = _story(conn, project_id, proposal["remove_key"])
        backlog.merge(conn, project_id, backlog.MergeIn(
            keep_id=keep.id, remove_id=remove.id, criteria=proposal["criteria"],
            wording=backlog.Wording(**proposal["wording"]) if proposal["wording"] else None))
    elif kind == "criteria":
        backlog.update_story(conn, project_id, story.id, backlog.StoryPatch(criteria=proposal["criteria"]))
    elif kind == "wording":
        backlog.update_story(conn, project_id, story.id, backlog.StoryPatch(**proposal))
    elif kind == "mockup":
        tree = mockups.Tree(**TEMPLATES[proposal["template"]][1]).model_copy(update={"title": proposal["title"]})
        with conn:
            backlog.record_undo(conn, project_id, "mockup_linked", key=story.key)
            mockups.create(conn, project_id, tree, note=f"template:{proposal['template']}", story_id=story.id)
            backlog.check_status(conn, project_id, story.id, None)


# --- API -----------------------------------------------------------------

router = APIRouter(prefix="/api/projects/{project_id}", tags=["review"])


@router.post("/review", response_model=projects.ProjectState)
async def post_review(project_id: int, conn: sqlite3.Connection = Depends(db.get_db)):
    return await run_review(conn, project_id)


@router.post("/review/{message_id}/findings/{index}", response_model=projects.ProjectState)
def post_decision(project_id: int, message_id: int, index: int, data: FindingDecision,
                  conn: sqlite3.Connection = Depends(db.get_db)):
    return decide(conn, project_id, message_id, index, data)
