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

from . import backlog, db, projects
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
    next_steps: list[NextStep] = Field(min_length=1, max_length=4)

    @model_validator(mode="after")
    def _one_card_and_a_way_on(self):
        if sum(1 for card in (self.question, self.roles, self.stories) if card) > 1:
            raise ValueError("one card per turn: a question, roles or stories, not several")
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
  user added them to the backlog: acknowledge and move to the priorities step.
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
  stories or asking for different ones).
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


class NextInput(_Strict):
    kind: Literal["next"]
    label: str = Field(min_length=1, max_length=60)
    step: Step | None = None


class RetryInput(_Strict):
    kind: Literal["retry"]


UserInput = Annotated[TextInput | AnswerInput | RolesInput | StoriesInput | NextInput | RetryInput,
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
            added = backlog.add_stories(conn, project_id, chosen, origin="ai")
            message.content["stories_added"] = {"selected": sorted(data.selected),
                                                "keys": [s.key for s in added]}
            projects.update_message(conn, message.id, message.content)
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
            "stories": None}
    answered = len(payload["clarifications"])
    if payload["open_question"] and data["kind"] == "text":
        base["interpreted_answer"] = data["text"][:300]
        answered += 1

    if data["kind"] == "stories":
        return {**base, "step": "priorities",
                "message": "Lood on backlog'is. Järgmiseks valime, millest alustada.",
                "next_steps": [reply("Vali, millest alustada", "priorities"),
                               reply("Paku veel lugusid", "stories")]}
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
        "next_steps": [s.model_dump() for s in turn.next_steps],
    })
    return projects.state(conn, project_id)


# --- API -----------------------------------------------------------------

router = APIRouter(prefix="/api/projects", tags=["conversation"])


@router.post("/{project_id}/turn", response_model=projects.ProjectState)
async def post_turn(project_id: int, data: UserInput,
                    conn: sqlite3.Connection = Depends(db.get_db)):
    return await take_turn(conn, project_id, data)
