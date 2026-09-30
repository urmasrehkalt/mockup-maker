"""The guided conversation: one turn = the user's input, then one AI answer.

The user's decisions (answers, confirmed roles, step changes) are stored before
the AI is called, so a failed or slow AI never loses them; `retry` simply asks
again. The AI sees the project's state from the database, not only the chat
history, and proposes: it never writes roles or stories itself.
"""
from __future__ import annotations

import sqlite3
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field, model_validator

from . import backlog, db, mockups, projects, testability
from .ai import Task, run_task
from .projects import Role, Step

MAX_CLARIFICATIONS = 3
MIN_FIRST_STORIES = 5
NOTE = "(noted from the user's free text)"  # the "question" of a fact stated unprompted
RECENT_MESSAGES = 12


# --- the AI's answer -----------------------------------------------------

class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class QuestionCard(_Strict):
    text: str = Field(min_length=1, max_length=300)
    multi_select: bool
    options: list[Annotated[str, Field(min_length=1, max_length=80)]] = Field(
        min_length=2, max_length=6)

    @model_validator(mode="after")
    def _unique_options(self):
        if len({o.casefold() for o in self.options}) != len(self.options):
            raise ValueError("question options must be unique")
        return self


class RoleSuggestion(_Strict):
    name: str = Field(min_length=1, max_length=60)
    description: str = Field(max_length=300)
    recommended: bool


class PriorityCard(_Strict):
    story_key: str = Field(min_length=1, max_length=20)
    reason: str = Field(min_length=1, max_length=400)


class ProposedCriterion(_Strict):
    text: str = Field(min_length=1, max_length=300)
    component_id: str | None = Field(default=None, max_length=40)


class Proposal(_Strict):
    story_key: str = Field(min_length=1, max_length=20)
    criteria: list[ProposedCriterion] = Field(min_length=3, max_length=8)
    mockup: mockups.Tree


class Wording(_Strict):
    role_phrase: str = Field(min_length=1, max_length=80)
    action: str = Field(min_length=1, max_length=300)
    benefit: str = Field(min_length=1, max_length=300)


class OtherStory(_Strict):
    story_key: str = Field(min_length=1, max_length=20)
    reason: str = Field(min_length=1, max_length=300)


class Change(_Strict):
    """A client's refinement, as a change to ONE story. None fields stay as they are."""
    story_key: str = Field(min_length=1, max_length=20)
    summary: str = Field(min_length=1, max_length=400)
    wording: Wording | None = None
    criteria: list[ProposedCriterion] | None = Field(default=None, min_length=1, max_length=10)
    mockup: mockups.Tree | None = None
    other_stories: list[OtherStory] = Field(default_factory=list, max_length=5)

    @model_validator(mode="after")
    def _changes_something(self):
        if self.wording is None and self.criteria is None and self.mockup is None and not self.other_stories:
            raise ValueError("a change must change the wording, the criteria or the mockup, or "
                             "name the other stories it affects")
        return self


class NextStep(_Strict):
    label: str = Field(min_length=1, max_length=60)
    kind: Literal["reply", "end_meeting"]
    step: Step | None


class Turn(_Strict):
    message: str = Field(min_length=1, max_length=2000)
    step: Step
    interpreted_answer: str | None = Field(default=None, max_length=300)
    noted_fact: str | None = Field(default=None, max_length=300)
    question: QuestionCard | None
    roles: list[RoleSuggestion] | None = Field(min_length=2, max_length=8)
    stories: list[backlog.StoryParts] | None = Field(default=None, min_length=1, max_length=10)
    priority: PriorityCard | None = None
    proposal: Proposal | None = None
    change: Change | None = None
    next_steps: list[NextStep] = Field(min_length=1, max_length=4)

    @model_validator(mode="after")
    def _one_card_and_a_way_on(self):
        cards = (self.question, self.roles, self.stories, self.priority, self.proposal, self.change)
        if sum(1 for card in cards if card) > 1:
            raise ValueError("one card per turn: a question, roles, stories, a priority, a "
                             "proposal or a change, not several")
        if not any(s.kind == "reply" for s in self.next_steps):
            raise ValueError("next_steps needs at least one option of kind 'reply'")
        return self


INSTRUCTIONS = """\
You lead a requirements conversation with a project manager and their client, one turn at a time.
The process steps are: idea -> roles -> stories -> priorities -> criteria (acceptance criteria and
mockup) -> refinements -> grooming. INPUT.step is where the process is now; INPUT.user_input is what
the user just did. Base your answer on INPUT's project state (clarifications, roles), which reflects
manual changes; the recent messages are only context.

Rules for this turn:
- idea step: a client's first idea always leaves something open (who the users are, whether they
  pay online, what matters most), so after the first description ask ONE clarifying question in
  `question` with 2 to 6 short answer options; set multi_select when several answers can apply.
  Ask 1 to 3 clarifying questions in total, one per turn (INPUT.clarifications_asked counts
  them), then move on. Do not add "Other" or "Skip" options: the interface adds those. The question card shows the question, so do not
  repeat it in `message`; use `message` for a short lead-in. When the idea is clear enough, or 3 were asked, move
  to the roles step.
- roles step: propose 3 to 6 user roles in `roles`, each with a one-line description; mark the ones
  the idea clearly needs as recommended. When INPUT.user_input.kind is "roles" the user confirmed
  INPUT.roles: move to the stories step and propose the stories in this same turn.
- stories step: propose user stories as cards in `stories`: 5 to 8 stories for the main role's
  happy path (the typical successful flow from first contact to reaching the goal, no errors or
  edge cases), in the order the user walks through it. The main role is the first of INPUT.roles
  unless the idea clearly centres on another. One role and one goal per story. Fields:
  role_name exactly as in INPUT.roles; role_phrase = the role as the Connextra sentence starts in
  INPUT.language (Estonian essive, e.g. "Külastajana", "Klubi liikmena"); action = what they want,
  the words after "soovin" (e.g. "näha liikmepakette ja hindu"); benefit = why, the words after
  "et" (e.g. "valida endale sobiv pakett"). Do not repeat stories already in INPUT.backlog; when
  asked for different ones, offer a different cut. When INPUT.user_input.kind is "stories" the
  user added them to the backlog: move to the priorities step and, in this same turn, ask which
  story matters most to the client.
- priorities step: recommend the story to start with in `priority`: story_key from INPUT.backlog
  and a one-sentence reason (usually the story without which the rest of the flow is pointless).
  Ask in `message` which story is most important to the client. When INPUT.user_input.kind is
  "focus" the user chose INPUT.current_story: move to the criteria step and, in this same turn,
  make the proposal described next.
- criteria step: for INPUT.current_story propose, in `proposal`, 3 to 7 acceptance criteria and a
  wireframe mockup of the view. Each criterion is ONE simple condition that can be checked with yes
  or no: no evaluative words (user-friendly, fast, simple, convenient, intuitive, clear, or their
  Estonian equivalents), never two conditions joined with "and"/"ja"/"ning". For a criterion about
  what the view shows or lets the user do, set component_id to the id of the mockup component that
  shows it; null only when the view cannot show it (e.g. an e-mail is sent). The mockup is a tree
  of components: short unique ids in lowercase with hyphens; only header, card, grid, price_card,
  form, footer and section have children; set every unused field to null. If
  INPUT.current_story_detail has a mockup, start from it and keep the ids of what stays. Do not
  repeat criteria the story already has. When INPUT.user_input.kind is "criteria" the user decided
  on the proposal: move to the refinements step and offer next steps such as the next story, a
  backlog review or ending the meeting. A next step cannot pick a story: to work on another story,
  offer the priorities step (the user chooses the story there), never "work on US-n" directly.
- refinements step: when the user passes on something the client said about INPUT.current_story
  (free text, or INPUT.user_input.kind "refine"), turn it into `change` for that story only:
  `wording` (role_phrase, action, benefit) if the story's wording changes, `criteria` = the
  story's FULL criteria list after the change (keep unchanged ones word for word, same rules as
  above), `mockup` = the FULL mockup after the change (start from INPUT.current_story_detail's
  mockup and keep the ids of everything that stays); null for what does not change. `summary`
  says in one or two sentences what changes. Never change another story: if the refinement also
  affects other stories in INPUT.backlog, list them in `other_stories` with the reason; the user
  can ask for their change separately. If the refinement does not concern the chosen story at
  all, still return `change` with wording, criteria and mockup null and the affected stories in
  `other_stories`. For "refine", the refinement text is
  INPUT.user_input.text. When INPUT.user_input.kind is "change" the user applied or discarded it:
  acknowledge and ask what to do next (next story, backlog review, end the meeting).
- Later steps: explain briefly what happens in the step and offer next steps; do not invent
  stories or criteria in the message text.
- Free text: the user may ignore the buttons and write. If INPUT.open_question is set and the text
  answers it, put a short summary of that answer in `interpreted_answer`; otherwise null. If the
  text states a requirement or decision that is not that answer, summarise it in `noted_fact` so it
  is kept with the project state (not for the first description, INPUT.idea); otherwise null.
- `step` is the step the process is in after this turn.
- Always end with 1 to 4 `next_steps`, the recommended one first; at least one of kind "reply".
  Next steps are moves in the conversation (e.g. suggest different roles, move to a step); never
  duplicate what a card's own buttons do (answering the question, confirming the roles, adding
  stories or asking for different ones, agreeing to or changing the recommended story, accepting
  or editing criteria).
  A "reply" is sent back to you as the user's choice; set its `step` when choosing it moves the
  process to that step. Use "end_meeting" only to offer ending the session.
- You propose; the user decides. Never claim that you saved or changed anything.
- Keep `message` short (1 to 3 sentences). Write every user-facing string in the language given by
  INPUT.language (et = Estonian, en = English)."""


# --- the user's input ----------------------------------------------------

class TextInput(_Strict):
    kind: Literal["text"]
    text: str = Field(min_length=1, max_length=4000)


class AnswerInput(_Strict):
    kind: Literal["answer"]
    message_id: int
    selected: list[str] = Field(default_factory=list, max_length=6)
    other: str | None = Field(default=None, max_length=300)
    skipped: bool = False


class RolesInput(_Strict):
    kind: Literal["roles"]
    message_id: int | None = None
    roles: list[Role] = Field(min_length=1, max_length=12)


class StoriesInput(_Strict):
    kind: Literal["stories"]
    message_id: int
    selected: list[int] = Field(min_length=1, max_length=10)


class FocusInput(_Strict):
    kind: Literal["focus"]
    message_id: int | None = None
    story_id: int


class CriteriaItem(_Strict):
    index: int | None = None  # a proposed criterion; None for one the user added
    text: str | None = Field(default=None, max_length=300)  # the user's wording, if changed


class CriteriaInput(_Strict):
    kind: Literal["criteria"]
    message_id: int
    items: list[CriteriaItem] = Field(max_length=15)


class ChangeEdits(_Strict):
    wording: Wording | None = None
    criteria: list[str] | None = Field(default=None, min_length=1, max_length=15)


class ChangeInput(_Strict):
    kind: Literal["change"]
    message_id: int
    decision: Literal["apply", "discard"]
    edits: ChangeEdits | None = None


class RefineInput(_Strict):
    """Ask for a change to another story that a refinement affects."""
    kind: Literal["refine"]
    story_id: int
    text: str = Field(min_length=1, max_length=2000)


class NextInput(_Strict):
    kind: Literal["next"]
    label: str = Field(min_length=1, max_length=60)
    step: Step | None = None


class RetryInput(_Strict):
    kind: Literal["retry"]


UserInput = Annotated[TextInput | AnswerInput | RolesInput | StoriesInput | FocusInput
                      | CriteriaInput | ChangeInput | RefineInput | NextInput | RetryInput,
                      Field(discriminator="kind")]


# --- turn ----------------------------------------------------------------

def open_question(history: list[projects.Message]) -> projects.Message | None:
    """The latest assistant message, if it asks a question nobody answered yet."""
    for message in reversed(history):
        if message.role == "assistant":
            question = message.content.get("question")
            return message if question and "answer" not in question else None
    return None


def questions_asked(history: list[projects.Message]) -> int:
    return sum(1 for m in history if m.role == "assistant" and m.content.get("question"))


def apply_input(conn: sqlite3.Connection, project_id: int, data: Any) -> projects.Message | None:
    """Store the user's decision; return the question that is still open, if any."""
    if data.kind == "retry":
        return open_question(projects.messages(conn, project_id))

    with conn:
        if data.kind == "answer":
            message = projects.get_message(conn, project_id, data.message_id)
            question = message.content.get("question")
            if message.role != "assistant" or not question:
                raise HTTPException(400, "That message has no question to answer")
            if "answer" in question:
                raise HTTPException(409, "That question is already answered")
            unknown = [s for s in data.selected if s not in question["options"]]
            if unknown:
                raise HTTPException(422, f"Not an option of the question: {unknown}")
            other = (data.other or "").strip()
            if not data.skipped and not data.selected and not other:
                raise HTTPException(422, "Choose an option, write an answer or skip")
            parts = [] if data.skipped else [*data.selected, *([other] if other else [])]
            answer = "; ".join(parts) or None
            projects.add_clarification(conn, project_id, message.id, question["text"], answer)
            question["answer"] = {"selected": [] if data.skipped else data.selected,
                                  "other": None if data.skipped else (other or None),
                                  "skipped": data.skipped}
            projects.update_message(conn, message.id, message.content)
        elif data.kind == "roles":
            projects.replace_roles(conn, project_id, data.roles)
            if data.message_id is not None:
                message = projects.get_message(conn, project_id, data.message_id)
                if message.role != "assistant" or not message.content.get("roles"):
                    raise HTTPException(400, "That message has no roles to confirm")
                message.content["roles_confirmed"] = [r.name for r in data.roles]
                projects.update_message(conn, message.id, message.content)
        elif data.kind == "stories":
            message = projects.get_message(conn, project_id, data.message_id)
            offered = message.content.get("stories") if message.role == "assistant" else None
            if not offered:
                raise HTTPException(400, "That message has no stories to add")
            if "stories_added" in message.content:
                raise HTTPException(409, "Stories from that suggestion were already added")
            if len(set(data.selected)) != len(data.selected) or not all(
                    0 <= i < len(offered) for i in data.selected):
                raise HTTPException(422, "Selected stories must be distinct suggestions")
            chosen = [backlog.StoryParts(**offered[i]) for i in sorted(data.selected)]
            backlog.record_undo(conn, project_id, "stories_added", count=len(chosen))
            added = backlog.add_stories(conn, project_id, chosen, origin="ai")
            message.content["stories_added"] = {"selected": sorted(data.selected),
                                                "keys": [s.key for s in added]}
            projects.update_message(conn, message.id, message.content)
        elif data.kind == "focus":
            story = backlog.get_story(conn, project_id, data.story_id)
            conn.execute("UPDATE projects SET current_story_id = ? WHERE id = ?", (story.id, project_id))
            if data.message_id is not None:
                message = projects.get_message(conn, project_id, data.message_id)
                card = message.content.get("priority") if message.role == "assistant" else None
                if not card:
                    raise HTTPException(400, "That message has no recommendation to answer")
                card["chosen"] = {"key": story.key, "agreed": story.key == card["story_key"]}
                projects.update_message(conn, message.id, message.content)
        elif data.kind == "criteria":
            apply_criteria(conn, project_id, data)
        elif data.kind == "change":
            apply_change(conn, project_id, data)
        elif data.kind == "refine":
            story = backlog.get_story(conn, project_id, data.story_id)
            conn.execute("UPDATE projects SET current_story_id = ?, step = 'refinements' WHERE id = ?",
                         (story.id, project_id))
        elif data.kind == "next" and data.step:
            conn.execute("UPDATE projects SET step = ? WHERE id = ?", (data.step, project_id))

    projects.add_message(conn, project_id, "user", {"input": data.model_dump()})
    return open_question(projects.messages(conn, project_id))


def describe(message: projects.Message) -> str:
    """One line of history for the prompt."""
    content = message.content
    if message.role == "assistant":
        line = content.get("text", "")
        if content.get("question"):
            line += f" [asked: {content['question']['text']}]"
        if content.get("roles"):
            line += " [proposed roles: " + ", ".join(r["name"] for r in content["roles"]) + "]"
        if content.get("stories"):
            line += f" [proposed {len(content['stories'])} stories]"
        if content.get("priority"):
            line += f" [recommended starting with {content['priority']['story_key']}]"
        if content.get("proposal"):
            line += (f" [proposed {len(content['proposal']['criteria'])} criteria and a mockup "
                     f"for {content['proposal']['story_key']}]")
        if content.get("change"):
            line += f" [proposed a change to {content['change']['story_key']}]"
        return line
    data = content.get("input", {})
    match data.get("kind"):
        case "text":
            return data["text"]
        case "answer":
            if data.get("skipped"):
                return "(skipped the question)"
            return "Answered: " + "; ".join([*data.get("selected", []), *filter(None, [data.get("other")])])
        case "roles":
            return "Confirmed roles: " + ", ".join(r["name"] for r in data["roles"])
        case "stories":
            return f"Added {len(data['selected'])} of the proposed stories to the backlog"
        case "focus":
            return "Chose the story to start with"
        case "criteria":
            return f"Decided on the proposal: kept {len(data['items'])} criteria and the mockup"
        case "change":
            return "Applied the change" if data["decision"] == "apply" else "Discarded the change"
        case "refine":
            return f"Asked for a separate change: {data['text']}"
        case "next":
            return f"Chose: {data['label']}"
        case _:
            return content.get("text", "")


def build_payload(conn: sqlite3.Connection, project_id: int, data: Any,
                  pending: projects.Message | None) -> dict[str, Any]:
    project = projects.get(conn, project_id)
    history = projects.messages(conn, project_id)
    first_text = next((m.content["input"]["text"] for m in history
                       if m.role == "user" and m.content.get("input", {}).get("kind") == "text"), None)
    clarifications = projects.clarifications(conn, project_id)
    return {
        "language": "et",
        "project": {"name": project.name, "description": project.description},
        "idea": first_text,
        "step": project.step,
        "clarifications": [c.model_dump() for c in clarifications],
        "clarifications_asked": questions_asked(history),
        "roles": [r.model_dump() for r in projects.roles(conn, project_id)],
        "backlog": backlog.snapshot(conn, project_id),
        "current_story": _current_key(conn, project),
        "current_story_detail": _current_detail(conn, project),
        "open_question": pending.content["question"]["text"] if pending else None,
        "recent_messages": [{"role": m.role, "text": describe(m)}
                            for m in history[-RECENT_MESSAGES:]],
        "user_input": data.model_dump(),
    }


MOCK_HAPPY_PATH = [
    ("näha avalehel ülevaadet pakutavatest teenustest", "mõista, mida mulle pakutakse"),
    ("näha pakette ja nende hindu", "valida endale sobiv pakett"),
    ("luua endale konto", "saaksin teenust kasutada"),
    ("valida sobiv pakett", "saaksin liituda just mulle sobival viisil"),
    ("tasuda paketi eest veebis", "ei peaks maksmiseks kohale minema"),
    ("saada liitumise kohta kinnitus e-postiga", "oleksin kindel, et liitumine õnnestus"),
    ("näha oma paketi andmeid ja kehtivust", "teaksin, milleks mul õigus on"),
]


def mock_turn(payload: dict[str, Any]) -> dict[str, Any]:
    """A plausible, deterministic walk through the first steps, driven by state."""
    data = payload["user_input"]
    reply = lambda label, step=None: {"label": label, "kind": "reply", "step": step}  # noqa: E731
    base = {"interpreted_answer": None, "noted_fact": None, "question": None, "roles": None,
            "stories": None, "priority": None, "proposal": None, "change": None}
    answered = len(payload["clarifications"])
    if payload["open_question"] and data["kind"] == "text":
        base["interpreted_answer"] = data["text"][:300]
        answered += 1

    if data["kind"] == "change":
        return {**base, "step": "refinements",
                "message": ("Muudatus on rakendatud. " if data["decision"] == "apply" else "Muudatusest loobuti. ")
                           + "Mida teeme edasi?",
                "next_steps": [reply("Järgmine lugu", "priorities"),
                               reply("Vaatame backlog'i üle", "grooming"),
                               {"label": "Lõpetame kohtumise", "kind": "end_meeting", "step": None}]}
    if payload["current_story"] and (data["kind"] == "refine" or (
            payload["step"] == "refinements" and data["kind"] == "text")):
        return {**base, "step": "refinements",
                "message": "Muudatusettepanek: mockup'i lisandub märge ja kriteeriumide hulka üks "
                           "kriteerium. Teisi lugusid see ei mõjuta.",
                "change": mock_change(payload),
                "next_steps": [reply("Järgmine lugu", "priorities")]}
    if data["kind"] == "criteria":
        return {**base, "step": "refinements",
                "message": "Kriteeriumid ja mockup on loos. Kui klient soovib midagi täpsustada, "
                           "kirjuta see siia. Mida teeme edasi?",
                "next_steps": [reply("Järgmine lugu", "priorities"),
                               reply("Vaatame backlog'i üle", "grooming"),
                               {"label": "Lõpetame kohtumise", "kind": "end_meeting", "step": None}]}
    if payload["current_story"] and (data["kind"] == "focus" or payload["step"] == "criteria"):
        return {**base, "step": "criteria",
                "message": f"Pakun loole {payload['current_story']} vastuvõtukriteeriumid ja mockup'i.",
                "proposal": mock_proposal(payload),
                "next_steps": [reply("Paku teistsugune mockup", "criteria")]}
    if data["kind"] == "stories" or (payload["step"] == "priorities" and payload["backlog"]):
        first = payload["backlog"][0]
        return {**base, "step": "priorities",
                "message": "Milline neist on kliendile kõige olulisem?",
                "priority": {"story_key": first["key"],
                             "reason": "Ilma selleta ei ole ülejäänud töövoogu mõtet kasutada."},
                "next_steps": [reply("Paku veel lugusid", "stories")]}
    if payload["step"] == "stories" or data["kind"] == "roles":
        role = (payload["roles"] or [{"name": "Kasutaja"}])[0]["name"]
        return {**base, "step": "stories",
                "message": f"Pakun rolli „{role}“ põhitöövoo põhjal 7 lugu happy path'i järjekorras.",
                "stories": [{"role_name": role, "role_phrase": f"{role}na", "action": action,
                             "benefit": benefit} for action, benefit in MOCK_HAPPY_PATH],
                "next_steps": [reply("Liigu prioriteetide juurde", "priorities")]}
    if payload["step"] == "idea" and answered == 0:
        return {**base, "step": "idea",
                "message": "Enne lugude pakkumist täpsustan paari asja.",
                "question": {"text": "Kes on rakenduse kasutajad?", "multi_select": True,
                             "options": ["Külastaja", "Registreeritud kasutaja", "Administraator"]},
                "next_steps": [reply("Liigu rollide juurde", "roles")]}
    if payload["step"] == "idea" and answered == 1:
        return {**base, "step": "idea",
                "message": "Veel üks täpsustus.",
                "question": {"text": "Kas rakenduses makstakse veebis?", "multi_select": False,
                             "options": ["Jah, veebis", "Ei, kohapeal", "Otsustame hiljem"]},
                "next_steps": [reply("Liigu rollide juurde", "roles")]}
    if payload["step"] in ("idea", "roles"):
        return {**base, "step": "roles",
                "message": "Pakun järgmised kasutajarollid. Vali sobivad, lisa puuduvad ja kinnita.",
                "roles": [
                    {"name": "Külastaja", "description": "Tutvub pakkumisega enne liitumist.",
                     "recommended": True},
                    {"name": "Registreeritud kasutaja", "description": "Kasutab teenust sisse logituna.",
                     "recommended": True},
                    {"name": "Administraator", "description": "Haldab sisu ja kasutajaid.",
                     "recommended": True},
                    {"name": "Klienditugi", "description": "Aitab kasutajaid probleemide korral.",
                     "recommended": False},
                ],
                "next_steps": [reply("Paku teistsuguseid rolle", "roles")]}
    return {**base, "step": payload["step"],
            "message": "Selge. Jätkame sellest etapist.",
            "next_steps": [reply("Jätka"), {"label": "Lõpetame kohtumise", "kind": "end_meeting",
                                            "step": None}]}


def check_turn(turn: Turn, payload: dict[str, Any]) -> str | None:
    """Process rules that depend on the project's state, not only the answer's shape."""
    asked = payload["clarifications_asked"]
    if turn.question and asked >= MAX_CLARIFICATIONS:
        return (f"{asked} clarifying questions were already asked, the maximum is "
                f"{MAX_CLARIFICATIONS}: do not ask another; move the process on.")
    first_idea = payload["step"] == "idea" and payload["user_input"]["kind"] == "text"
    if first_idea and asked == 0 and not turn.question:
        return ("This is the client's first description: ask one clarifying question with "
                "answer options before proposing roles or stories.")
    if payload["user_input"]["kind"] == "roles" and not turn.stories:
        return ("The user just confirmed the roles: propose the happy-path stories as cards in "
                "`stories` in this same turn.")
    keys = {story["key"] for story in payload["backlog"]}
    if turn.priority and turn.priority.story_key not in keys:
        return (f"priority.story_key {turn.priority.story_key!r} is not in INPUT.backlog; "
                f"recommend one of {sorted(keys)}.")
    asked_for_priority = (payload["user_input"]["kind"] == "stories"
                          or (payload["user_input"]["kind"] == "next"
                              and payload["user_input"].get("step") == "priorities"))
    if asked_for_priority and keys and not turn.priority:
        return ("The process is at the priorities step: recommend the story to start with in "
                "`priority`, with a reason, in this same turn.")
    if turn.proposal:
        problem = _check_proposal(turn.proposal, payload)
        if problem:
            return problem
    if turn.change:
        problem = _check_change(turn.change, payload)
        if problem:
            return problem
    if payload["user_input"]["kind"] == "refine" and not turn.change:
        return (f"The user asked for a change to {payload.get('current_story')}: return it in "
                "`change` in this same turn.")
    wants_proposal = payload.get("current_story") and (
        payload["user_input"]["kind"] == "focus"
        or (payload["user_input"]["kind"] == "next" and payload["user_input"].get("step") == "criteria"))
    if wants_proposal and not turn.proposal:
        return (f"The user chose {payload['current_story']}: propose its acceptance criteria and "
                "mockup in `proposal` in this same turn.")
    if turn.stories:
        if not payload["backlog"] and len(turn.stories) < MIN_FIRST_STORIES:
            return (f"The backlog is empty: propose at least {MIN_FIRST_STORIES} stories for the "
                    "main role's happy path.")
        known = {r["name"].casefold() for r in payload["roles"]}
        strangers = sorted({st.role_name for st in turn.stories if st.role_name.casefold() not in known})
        if known and strangers:
            return (f"Stories use roles that are not in INPUT.roles: {strangers}. Use role_name "
                    "exactly as listed there, or propose the new role separately.")
    return None


def _current_detail(conn: sqlite3.Connection, project: projects.Project) -> dict | None:
    """The chosen story as the AI needs it for a proposal: wording, criteria, current mockup."""
    if project.current_story_id is None:
        return None
    try:
        story = backlog.get_story(conn, project.id, project.current_story_id)
    except HTTPException:
        return None
    linked = [m for m in mockups.mockups(conn, project.id) if m.id in story.mockup_ids]
    return {"key": story.key, "title": story.title, "role_name": story.role_name,
            "role_phrase": story.role_phrase, "action": story.action, "benefit": story.benefit,
            "criteria": [{"text": c.text, "component_id": c.component_id} for c in story.criteria],
            "mockup": linked[0].tree.model_dump() if linked else None}


def _check_proposal(proposal: Proposal, payload: dict[str, Any]) -> str | None:
    current = payload.get("current_story")
    if current and proposal.story_key != current:
        return f"The proposal is for {proposal.story_key}, but the chosen story is {current}."
    ids = mockups.component_ids(proposal.mockup)
    dangling = [c.component_id for c in proposal.criteria if c.component_id and c.component_id not in ids]
    if dangling:
        return (f"Criteria refer to components that are not in the mockup: {dangling}. Use ids "
                f"from the mockup: {sorted(ids)}.")
    if not any(c.component_id for c in proposal.criteria):
        return ("No criterion refers to the mockup: set component_id on every criterion about "
                "what the view shows.")
    untestable = [testability.describe(c.text, issues) for c in proposal.criteria
                  if (issues := testability.check(c.text))]
    if untestable:
        return ("Some criteria cannot be answered with yes or no: " + " | ".join(untestable)
                + ". Rewrite each as one simple, checkable condition.")
    return None


def _with_issues(proposal: Proposal) -> dict[str, Any]:
    """The proposal as stored: each criterion carries its testability warnings (if the model
    kept an untestable one after the retry, the user sees why)."""
    data = proposal.model_dump()
    for criterion in data["criteria"]:
        criterion["issues"] = [i.model_dump() for i in testability.check(criterion["text"])]
    return data


def _check_change(change: Change, payload: dict[str, Any]) -> str | None:
    current = payload.get("current_story")
    if change.story_key != current:
        return (f"A change may only touch the chosen story {current}, not {change.story_key}; "
                "list other affected stories in other_stories instead.")
    keys = {story["key"] for story in payload["backlog"]}
    strangers = [o.story_key for o in change.other_stories if o.story_key not in keys or o.story_key == current]
    if strangers:
        return f"other_stories must be other stories from INPUT.backlog; not {strangers}."
    detail = payload.get("current_story_detail") or {}
    tree = change.mockup or (mockups.Tree(**detail["mockup"]) if detail.get("mockup") else None)
    ids = mockups.component_ids(tree) if tree else set()
    dangling = [c.component_id for c in change.criteria or [] if c.component_id and c.component_id not in ids]
    if dangling:
        return f"Criteria refer to components that are not in the mockup: {dangling}."
    untestable = [testability.describe(c.text, issues) for c in change.criteria or []
                  if (issues := testability.check(c.text))]
    if untestable:
        return ("Some criteria cannot be answered with yes or no: " + " | ".join(untestable)
                + ". Rewrite each as one simple, checkable condition.")
    return None


def _stored_change(conn: sqlite3.Connection, project_id: int, change: Change) -> dict[str, Any] | None:
    """The change card as stored: the proposal plus the story as it is now, for the
    before/after preview. A change for any story but the chosen one is never stored."""
    project = projects.get(conn, project_id)
    story = (backlog.get_story(conn, project_id, project.current_story_id)
             if project.current_story_id else None)
    if story is None or story.key != change.story_key:
        return None
    linked = [m for m in mockups.mockups(conn, project_id) if m.id in story.mockup_ids]
    data = change.model_dump()
    for criterion in data["criteria"] or []:
        criterion["issues"] = [i.model_dump() for i in testability.check(criterion["text"])]
    data["story_id"] = story.id
    data["before"] = {
        "title": story.title,
        "wording": {"role_phrase": story.role_phrase, "action": story.action, "benefit": story.benefit},
        "criteria": [{"text": c.text, "component_id": c.component_id} for c in story.criteria],
        "mockup_id": linked[0].id if linked else None,
        "mockup": linked[0].tree.model_dump() if linked else None,
    }
    if change.wording:
        data["after_title"] = backlog.title(backlog.StoryParts(
            role_name=story.role_name, **change.wording.model_dump()))
    return data


def apply_change(conn: sqlite3.Connection, project_id: int, data: ChangeInput) -> None:
    """Apply or discard a change card. Only the card's own story is touched."""
    message = projects.get_message(conn, project_id, data.message_id)
    change = message.content.get("change") if message.role == "assistant" else None
    if not change:
        raise HTTPException(400, "That message has no change to decide on")
    if "decided" in change:
        raise HTTPException(409, "That change was already decided on")
    changes_story = any(change[k] is not None for k in ("wording", "criteria", "mockup"))
    if data.decision == "discard" or not changes_story:
        if data.decision == "apply":
            raise HTTPException(409, "That change does not change this story; ask for the other stories separately")
        change["decided"] = {"applied": False}
        projects.update_message(conn, message.id, message.content)
        return

    story = backlog.get_story(conn, project_id, change["story_id"])
    edits = data.edits or ChangeEdits()
    wording = edits.wording or (Wording(**change["wording"]) if change["wording"] else None)
    new_tree = mockups.Tree(**change["mockup"]) if change["mockup"] else None
    backlog.record_undo(conn, project_id, "story_refined", key=story.key)

    if wording:
        conn.execute("UPDATE stories SET role_phrase = ?, action = ?, benefit = ?, updated_at = ? "
                     "WHERE id = ?", (wording.role_phrase, wording.action, wording.benefit,
                                      db.now(), story.id))
    proposed = change["criteria"]
    if edits.criteria is not None:
        by_position = proposed or change["before"]["criteria"]
        items = []
        for i, text in enumerate(" ".join(t.split()) for t in edits.criteria):
            if not text:
                continue
            match = next((c for c in by_position if c["text"] == text), None)
            component = (match or (by_position[i] if i < len(by_position) else {})).get("component_id")
            items.append((text, "ai" if match and proposed else "manual", component))
        backlog.replace_criteria(conn, story.id, items)
    elif proposed is not None:
        backlog.replace_criteria(conn, story.id, [(c["text"], "ai", c["component_id"]) for c in proposed])

    version = None
    if new_tree:
        mockup_id, version = mockups.update_for_story(conn, project_id, story.id,
                                                      change["before"]["mockup_id"], new_tree,
                                                      note=f"change:{message.id}")
        change["decided"] = {"applied": True, "mockup_id": mockup_id, "version": version}
    else:
        change["decided"] = {"applied": True}
    projects.update_message(conn, message.id, message.content)


def apply_criteria(conn: sqlite3.Connection, project_id: int, data: CriteriaInput) -> None:
    """Store the user's decision on a proposal. Called inside the input's transaction."""
    message = projects.get_message(conn, project_id, data.message_id)
    proposal = message.content.get("proposal") if message.role == "assistant" else None
    if not proposal:
        raise HTTPException(400, "That message has no proposal to decide on")
    if "decided" in proposal:
        raise HTTPException(409, "That proposal was already decided on")
    key = proposal["story_key"]
    story = next((s for s in backlog.stories(conn, project_id) if s.key == key), None)
    if story is None:
        raise HTTPException(409, f"Story {key} is no longer in the backlog")
    offered = proposal["criteria"]
    indexes = [item.index for item in data.items if item.index is not None]
    if len(set(indexes)) != len(indexes) or not all(0 <= i < len(offered) for i in indexes):
        raise HTTPException(422, "Criteria must refer to distinct proposed criteria")

    kept: list[tuple[str, backlog.Origin, str | None]] = []
    for item in data.items:
        written = " ".join((item.text or "").split())
        if item.index is None:
            if not written:
                raise HTTPException(422, "An added criterion needs text")
            kept.append((written, "manual", None))
        else:
            original = offered[item.index]
            edited = written and written != original["text"]
            kept.append((written if edited else original["text"], "manual" if edited else "ai",
                         original["component_id"]))

    backlog.record_undo(conn, project_id, "criteria_added", key=key, count=len(kept))
    backlog.append_criteria(conn, story.id, kept)
    tree = mockups.Tree(**proposal["mockup"])
    if story.mockup_ids:
        mockup_id = story.mockup_ids[0]
        mockups.add_version(conn, mockup_id, tree, note=f"proposal:{message.id}")
    else:
        mockup_id = mockups.create(conn, project_id, tree, note=f"proposal:{message.id}",
                                   story_id=story.id).id
    proposal["decided"] = {"kept": len(kept), "rejected": len(offered) - len(indexes),
                           "mockup_id": mockup_id}
    projects.update_message(conn, message.id, message.content)


MOCK_PROPOSALS = {
    # keyword in the story's action -> (template, [(criterion, component id)])
    "pakett": ("pricing", [("Lehel on iga paketi nimi.", "package-basic"),
                           ("Iga paketi juures on kuutasu eurodes.", "package-plus"),
                           ("Iga paketi juures on nupp „Vali“.", "package-basic-choose"),
                           ("Paketid on kuvatud kõrvuti võrdlemiseks.", "packages")]),
    "hind": ("pricing", [("Lehel on iga paketi nimi.", "package-basic"),
                         ("Iga paketi juures on kuutasu eurodes.", "package-plus"),
                         ("Iga paketi juures on nupp „Vali“.", "package-basic-choose")]),
    "konto": ("form", [("Vormis on nõutud väli „E-post“.", "email"),
                       ("Vorm ei lase saata tühja e-posti väljaga.", "email"),
                       ("Vormis on nupp „Saada“.", "submit"),
                       ("Tingimustega nõustumine on kohustuslik.", "terms")]),
    "tasu": ("checkout", [("Kokkuvõttes on valitud paketi hind.", "order"),
                          ("Hinna juures on märge, kas hind sisaldab käibemaksu.", "vat-note"),
                          ("Lehel on nupp „Maksa“.", "pay")]),
    "kinnitus": ("confirmation", [("Pärast liitumist kuvatakse kinnitusteade.", "success"),
                                  ("Kinnitusel on tellimuse number.", "summary"),
                                  ("Kinnitus saadetakse e-postile.", None)]),
}


def mock_change(payload: dict[str, Any]) -> dict[str, Any]:
    """Add a note under the view's main heading and one criterion that checks it."""
    from .mockup_templates import TEMPLATES
    detail = payload["current_story_detail"] or {}
    tree = detail.get("mockup") or TEMPLATES["detail"][1]
    components = [dict(c) for c in tree["components"]]
    note = {"id": "refinement-note", "type": "note", "text": "Hinnad sisaldavad käibemaksu (sh km)"}
    at = next((i + 1 for i, c in enumerate(components) if c["type"] == "heading"), len(components))
    if not any(c["id"] == "refinement-note" for c in components):
        components.insert(at, note)
    criteria = [dict(c) for c in detail.get("criteria", [])]
    criteria.append({"text": "Hinna all on märge „sh km“.", "component_id": "refinement-note"})
    return {"story_key": payload["current_story"],
            "summary": "Mockup'i lisandub hinna alla märge „sh km“ ja kriteeriumide hulka üks kriteerium.",
            "wording": None, "criteria": criteria,
            "mockup": {"title": tree["title"], "components": components}, "other_stories": []}


def mock_proposal(payload: dict[str, Any]) -> dict[str, Any]:
    from .mockup_templates import TEMPLATES
    detail = payload["current_story_detail"] or {}
    title = detail.get("title", "")
    template, criteria = next((v for k, v in MOCK_PROPOSALS.items() if k in title),
                              ("detail", [("Lehel on kirje nimi.", "detail-title"),
                                          ("Lehel on kirje kirjeldus.", "detail-text"),
                                          ("Lehel on nupp „Vali see“.", "detail-cta")]))
    return {"story_key": payload["current_story"],
            "criteria": [{"text": text, "component_id": cid} for text, cid in criteria],
            "mockup": TEMPLATES[template][1]}


def _current_key(conn: sqlite3.Connection, project: projects.Project) -> str | None:
    if project.current_story_id is None:
        return None
    row = conn.execute("SELECT number FROM stories WHERE id = ?", (project.current_story_id,)).fetchone()
    return f"US-{row['number']}" if row else None


TURN = Task(name="turn", instructions=INSTRUCTIONS, response=Turn, mock=mock_turn)


async def take_turn(conn: sqlite3.Connection, project_id: int, data: Any) -> projects.ProjectState:
    projects.get(conn, project_id)
    pending = apply_input(conn, project_id, data)
    payload = build_payload(conn, project_id, data, pending)
    turn = await run_task(TURN, payload, check=lambda answer: check_turn(answer, payload))

    if payload["clarifications_asked"] >= MAX_CLARIFICATIONS:
        turn.question = None  # the model insisted; the cap is the server's
    with conn:
        if pending and data.kind == "text" and turn.interpreted_answer:
            question = pending.content["question"]
            projects.add_clarification(conn, project_id, pending.id, question["text"],
                                       turn.interpreted_answer)
            question["answer"] = {"selected": [], "other": turn.interpreted_answer,
                                  "skipped": False}
            projects.update_message(conn, pending.id, pending.content)
        if data.kind == "text" and turn.noted_fact and data.text != payload["idea"]:
            projects.add_clarification(conn, project_id, None, NOTE, turn.noted_fact)
        conn.execute("UPDATE projects SET step = ? WHERE id = ?", (turn.step, project_id))
    projects.add_message(conn, project_id, "assistant", {
        "text": turn.message,
        "step": turn.step,
        "question": turn.question.model_dump() if turn.question else None,
        "roles": [r.model_dump() for r in turn.roles] if turn.roles else None,
        "stories": [st.model_dump() for st in turn.stories] if turn.stories else None,
        "priority": turn.priority.model_dump() if turn.priority else None,
        "proposal": _with_issues(turn.proposal) if turn.proposal else None,
        "change": _stored_change(conn, project_id, turn.change) if turn.change else None,
        "next_steps": [s.model_dump() for s in turn.next_steps],
    })
    return projects.state(conn, project_id)


# --- API -----------------------------------------------------------------

router = APIRouter(prefix="/api/projects", tags=["conversation"])


@router.post("/{project_id}/turn", response_model=projects.ProjectState)
async def post_turn(project_id: int, data: UserInput,
                    conn: sqlite3.Connection = Depends(db.get_db)):
    return await take_turn(conn, project_id, data)
