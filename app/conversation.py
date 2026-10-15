"""The guided conversation: one turn = the user's input, then one AI answer.

The user's decisions (answers, confirmed roles, step changes) are stored before
the AI is called, so a failed or slow AI never loses them; `retry` simply asks
again. The AI sees the project's state from the database, not only the chat
history, and proposes: it never writes roles or stories itself.
"""
from __future__ import annotations

import sqlite3
from typing import Annotated, Any, Literal

from fastapi import HTTPException
from pydantic import BaseModel, ConfigDict, Field, model_validator

from . import backlog, db, ideas, mockups, projects, testability
from .ai import Task, run_task
from .mockup_templates import TEMPLATES, localized
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


class NewRole(_Strict):
    name: str = Field(min_length=1, max_length=60)
    description: str = Field(max_length=300)


class NewView(_Strict):
    """A view described in words: its story, criteria and mockup, proposed together."""
    story: backlog.StoryParts
    new_role: NewRole | None = None  # only when no confirmed role fits
    criteria: list[ProposedCriterion] = Field(min_length=3, max_length=8)
    mockup: mockups.Tree


class NextStep(_Strict):
    label: str = Field(min_length=1, max_length=60)
    kind: Literal["reply", "end_meeting"]
    step: Step | None


Intent = Literal["answer", "refinement", "new_view", "later", "question", "other"]


class IdeaCard(_Strict):
    """The AI's reading of a free-text thought that is not an answer: what it recommends doing with it."""
    recommended: Literal["new_view", "refine", "park"]
    reason: str = Field(min_length=1, max_length=300)


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
    new_view: NewView | None = None
    intent: Intent | None = None
    idea: IdeaCard | None = None
    next_steps: list[NextStep] = Field(min_length=1, max_length=4)

    @model_validator(mode="after")
    def _one_card_and_a_way_on(self):
        cards = (self.question, self.roles, self.stories, self.priority, self.proposal, self.change,
                 self.new_view, self.idea)
        if sum(1 for card in cards if card) > 1:
            raise ValueError("one card per turn: a question, roles, stories, a priority, a "
                             "proposal, a change or an idea, not several")
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
  role_name exactly as in INPUT.roles; role_phrase = the role as the Connextra sentence needs it in
  INPUT.language (Estonian: the essive, e.g. "Külastajana", "Klubi liikmena"; English: with its
  article, e.g. "a visitor", "a club member"); action = what they want, the words after
  "soovin" / "I want to" (e.g. "näha liikmepakette ja hindu" / "see the membership packages");
  benefit = why, the words after "et" / "so that" (e.g. "valida endale sobiv pakett" / "I can
  choose one that suits me"). Do not repeat stories already in INPUT.backlog; when
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
  form, footer and section have children; a grid may only hold card, price_card and image
  children, so to place content side by side (for example a photo to the right of buttons) use a
  grid with columns 2 whose children are cards or images, and put the buttons inside a card;
  set every unused field to null. If
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
- New view (any step): when INPUT.user_input.kind is "new_view", the user described a view that
  is not in the backlog yet (INPUT.user_input.text). Return `new_view`: the story for it (fields as
  for stories above), 3 to 7 criteria following the criteria rules above, and the mockup. If
  INPUT.template is given, start the mockup from it and keep its ids where they fit; otherwise
  design it. Use a role from INPUT.roles when one fits; only if none does, set `new_role` (name and
  a one-line description) and use that name as the story's role_name. Do not repeat a story that
  is already in INPUT.backlog. When INPUT.user_input.kind is "view_add" the user added or
  discarded it: acknowledge in one sentence; if added, stay at the refinements step and invite the
  client's remarks about the new view.
- Later steps: explain briefly what happens in the step and offer next steps; do not invent
  stories or criteria in the message text.
- Free text: the user may ignore the buttons and write. If INPUT.open_question is set and the text
  answers it, put a short summary of that answer in `interpreted_answer`; otherwise null. If the
  text states a requirement or decision that is not that answer, summarise it in `noted_fact` so it
  is kept with the project state (not for the first description, INPUT.idea); otherwise null.
- Classifying free text: when INPUT.classify_text is true, set `intent` to what the text is.
  "answer": it answers INPUT.open_question. "refinement": the client's remark about a story.
  "new_view": a view the backlog does not have yet. "later": a thought the client wants to keep for
  later, or that does not belong to the current work. "question": a question about the project,
  answered in `message`. "other": steering the conversation (asking for different roles or stories,
  moving on). Leave `intent` and `idea` null when INPUT.classify_text is false.
  A refinement of INPUT.current_story at the refinements step is turned into `change` as described
  above, with no idea card. A remark that does not concern the chosen story (it is about another
  story or a view the backlog does not have) is not a refinement of it: classify it as "new_view" or
  "later" and return the idea card. Any other "refinement", "new_view" and "later" get an
  `idea` card and no other card: `recommended` is "new_view" for a new view, "refine" for a
  refinement when INPUT.current_story is chosen (otherwise "park"), "park" for "later"; `reason` is
  one short sentence why. The server keeps the thought as an idea; the user decides what becomes of
  it, so do not claim anything was added or changed. Leave `noted_fact` null when you return an idea
  card. When INPUT.user_input.kind is "refine" or "new_view" for a parked idea, handle it as above.
- Suggestions: when a decision just finished a step, `message` may add one or two concrete
  observations from INPUT (a role in INPUT.roles that no story in INPUT.backlog covers, a story whose
  missing_for_ready lists criteria_testable or mockup). Only what INPUT shows; never invent.
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


class NewViewInput(_Strict):
    kind: Literal["new_view"]
    text: str = Field(min_length=1, max_length=1000)
    template: str | None = Field(default=None, max_length=40)


class ViewAddInput(_Strict):
    kind: Literal["view_add"]
    message_id: int
    decision: Literal["add", "discard"]
    wording: Wording | None = None       # the user's edit of the story wording
    items: list[CriteriaItem] = Field(default_factory=list, max_length=15)


class IdeaInput(_Strict):
    """Turn a parked idea into a new view or a refinement of a story (the chosen one by default)."""
    kind: Literal["idea"]
    idea_id: int
    decision: Literal["new_view", "refine"]
    story_id: int | None = None


class RetryInput(_Strict):
    kind: Literal["retry"]


UserInput = Annotated[TextInput | AnswerInput | RolesInput | StoriesInput | FocusInput
                      | CriteriaInput | ChangeInput | RefineInput | NewViewInput | ViewAddInput
                      | IdeaInput | NextInput | RetryInput,
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

    extra: dict[str, Any] = {}
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
        elif data.kind == "new_view" and data.template and data.template not in TEMPLATE_KEYS:
            raise HTTPException(422, f"Unknown template {data.template!r}")
        elif data.kind == "view_add":
            apply_new_view(conn, project_id, data)
        elif data.kind == "refine":
            story = backlog.get_story(conn, project_id, data.story_id)
            conn.execute("UPDATE projects SET current_story_id = ?, step = 'refinements' WHERE id = ?",
                         (story.id, project_id))
        elif data.kind == "idea":
            extra["idea_text"] = _apply_idea(conn, project_id, data)
        elif data.kind == "next" and data.step:
            conn.execute("UPDATE projects SET step = ? WHERE id = ?", (data.step, project_id))

    if data.kind == "text":
        conn.execute("UPDATE projects SET draft_idea = '' WHERE id = ?", (project_id,))  # it was sent
    projects.add_message(conn, project_id, "user", {"input": data.model_dump(), **extra})
    return open_question(projects.messages(conn, project_id))


def _apply_idea(conn: sqlite3.Connection, project_id: int, data: IdeaInput) -> str:
    """The user turned a parked idea into a view or a refinement: close the idea, and for a
    refinement make its story the chosen one. Returns the idea's text. Inside the input's transaction."""
    if data.decision == "refine":
        story_id = data.story_id or projects.get(conn, project_id).current_story_id
        if story_id is None:
            raise HTTPException(422, {"code": "no_story", "message": "Choose the story to refine first."})
        story = backlog.get_story(conn, project_id, story_id)
        text = ideas.convert(conn, project_id, data.idea_id, "refinement")
        conn.execute("UPDATE projects SET current_story_id = ?, step = 'refinements' WHERE id = ?",
                     (story.id, project_id))
        return text
    return ideas.convert(conn, project_id, data.idea_id, "new_view")


def _effective_input(conn: sqlite3.Connection, project_id: int, data: Any) -> Any:
    """What the AI is asked to do. A parked idea becomes the new view or the refinement it was turned into."""
    if data.kind != "idea":
        return data
    text = ideas.get(conn, project_id, data.idea_id)["text"]
    if data.decision == "new_view":
        return NewViewInput(kind="new_view", text=text[:1000])
    story_id = data.story_id or projects.get(conn, project_id).current_story_id
    return RefineInput(kind="refine", story_id=story_id, text=text[:2000])


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
        if content.get("new_view"):
            line += f" [proposed a new view: {content['new_view']['story']['action']}]"
        if content.get("review"):
            line += f" [reviewed the backlog: {len(content['review']['findings'])} findings]"
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
        case "new_view":
            return f"Described a new view: {data['text']}"
        case "view_add":
            return "Added the new view to the backlog" if data["decision"] == "add" else "Discarded the new view"
        case "refine":
            return f"Asked for a separate change: {data['text']}"
        case "review":
            return "Asked for a backlog review"
        case "idea":
            what = "a new view" if data["decision"] == "new_view" else "a refinement of the chosen story"
            return f"Turned the client's parked idea into {what}: {content.get('idea_text', '')}"
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
        "language": project.language,
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
        # free text after the idea step is classified (`intent`), and an idea card may follow
        "classify_text": data.kind == "text" and project.step != "idea",
        # a new view's chosen starting template, in the project's language
        "template": (localized(data.template, project.language)[1]
                     if data.kind == "new_view" and data.template else None),
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


def mock_intent(payload: dict[str, Any], base: dict[str, Any], reply) -> dict[str, Any] | None:
    """Classify a free-text thought by keyword. Returns the whole answer for the cases that are not
    handled by the step (a thought for later, a new view, a question); otherwise sets base["intent"]."""
    text = payload["user_input"]["text"].casefold()
    current, step = payload.get("current_story"), payload["step"]
    park = reply("Jätka")
    if "hiljem" in text or "later" in text:
        return {**base, "intent": "later", "step": step, "message": "Panen selle hilisemaks kõrvale.",
                "idea": {"recommended": "park", "reason": "Sellest saab hiljem eraldi vaade või täpsustus."},
                "next_steps": [park]}
    if any(words in text for words in ("uus vaade", "uue vaate", "uut vaadet", "new view")):
        return {**base, "intent": "new_view", "step": step, "message": "See kõlab uue vaatena.",
                "idea": {"recommended": "new_view", "reason": "Kirjeldab vaadet, mida backlog'is veel ei ole."},
                "next_steps": [park]}
    if "täpsusta" in text:
        if current and step == "refinements":
            base["intent"] = "refinement"
            return None
        return {**base, "intent": "refinement", "step": step, "message": "See on täpsustus.",
                "idea": {"recommended": "refine" if current else "park",
                         "reason": "Kliendi täpsustus loo kohta." if current else "Valitud lugu pole veel."},
                "next_steps": [park]}
    if text.rstrip().endswith("?"):
        return {**base, "intent": "question", "step": step, "message": "Hea küsimus. Vastan selle põhjal, mis projektis on.",
                "next_steps": [park]}
    base["intent"] = "refinement" if current and step == "refinements" else "other"
    return None


def mock_turn(payload: dict[str, Any]) -> dict[str, Any]:
    """A plausible, deterministic walk through the first steps, driven by state."""
    data = payload["user_input"]
    reply = lambda label, step=None: {"label": label, "kind": "reply", "step": step}  # noqa: E731
    base = {"interpreted_answer": None, "noted_fact": None, "question": None, "roles": None,
            "stories": None, "priority": None, "proposal": None, "change": None, "new_view": None}
    if data["kind"] == "new_view":
        return {**base, "step": payload["step"], "message": "Pakun uue vaate koos loo ja kriteeriumidega.",
                "new_view": mock_new_view(payload),
                "next_steps": [reply("Kirjelda teistsugune vaade", payload["step"])]}
    if data["kind"] == "view_add":
        added = data["decision"] == "add"
        return {**base, "step": "refinements" if added else payload["step"],
                "message": "Uus vaade on backlog'is. Kui kliendil on märkusi, kirjuta need siia." if added
                           else "Uuest vaatest loobuti.",
                "next_steps": [reply("Järgmine lugu", "priorities"),
                               {"label": "Lõpetame kohtumise", "kind": "end_meeting", "step": None}]}
    answered = len(payload["clarifications"])
    if payload["open_question"] and data["kind"] == "text":
        base["interpreted_answer"] = data["text"][:300]
        answered += 1
        base["intent"] = "answer"
    elif payload.get("classify_text"):
        early = mock_intent(payload, base, reply)
        if early:
            return early

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


def _check_intent(turn: Turn, payload: dict[str, Any]) -> str | None:
    """A free-text thought is classified; what is not an answer or a plain refinement of the
    chosen story becomes an idea card the user decides on."""
    if not payload.get("classify_text"):
        return "An idea card is only for the user's free text after the idea step." if turn.idea else None
    intent = turn.intent
    if intent is None:
        return ("Set `intent` to what the user's text is: answer, refinement, new_view, later, "
                "question or other.")
    if intent == "answer" and not payload["open_question"]:
        return "intent is 'answer' but INPUT.open_question is null; classify the text as something else."
    if intent in ("answer", "question", "other"):
        return f"intent {intent!r} takes no idea card." if turn.idea else None
    current = payload.get("current_story")
    if intent == "refinement" and current and payload["step"] == "refinements":
        if turn.idea or not turn.change:
            return (f"The text is a refinement of the chosen story {current}: return it in `change`, "
                    "not as an idea card. If it does not concern that story at all, it is not a "
                    "refinement of it: classify it as new_view or later and return an idea card.")
        return None
    if turn.change:
        return f"`change` is only for a refinement of the chosen story at the refinements step, not intent {intent!r}."
    expected = {"later": "park", "new_view": "new_view",
                "refinement": "refine" if current else "park"}[intent]
    if not turn.idea:
        return f"The text is intent {intent!r}: return an `idea` card with recommended {expected!r}."
    if turn.idea.recommended != expected:
        return f"For intent {intent!r} the idea card recommends {expected!r}, not {turn.idea.recommended!r}."
    return None


def check_turn(turn: Turn, payload: dict[str, Any]) -> str | None:
    """Process rules that depend on the project's state, not only the answer's shape."""
    problem = _check_intent(turn, payload)
    if problem:
        return problem
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
    if payload["user_input"]["kind"] == "new_view" and not turn.new_view:
        return "The user described a new view: return it in `new_view` in this same turn."
    if turn.new_view:
        problem = _check_new_view(turn.new_view, payload)
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


def _mockup_base(conn: sqlite3.Connection, project_id: int, story: backlog.Story) -> dict[str, Any]:
    """The mockup a card was made for: its id and newest version (both None: the story has none)."""
    linked = [m for m in mockups.mockups(conn, project_id) if m.id in story.mockup_ids]
    return {"mockup_id": linked[0].id, "version": linked[0].version} if linked else {"mockup_id": None, "version": None}


def _stale_card() -> HTTPException:
    return HTTPException(409, {"code": "stale_card",
                               "message": "The story or its mockup changed after this suggestion was made. "
                                          "Ask for it again."})


def _stored_proposal(conn: sqlite3.Connection, project_id: int, proposal: Proposal) -> dict[str, Any]:
    data = _with_issues(proposal)
    story = next((s for s in backlog.stories(conn, project_id) if s.key == proposal.story_key), None)
    if story:
        data["base"] = _mockup_base(conn, project_id, story)
    return data


TEMPLATE_KEYS = set(TEMPLATES)


def _check_new_view(view: NewView, payload: dict[str, Any]) -> str | None:
    roles = {r["name"].casefold(): r["name"] for r in payload["roles"]}
    role = view.story.role_name.casefold()
    if view.new_role:
        if view.new_role.name.casefold() in roles:
            return (f"{view.new_role.name!r} is already a role; use it and leave new_role null.")
        if view.new_role.name.casefold() != role:
            return "The story's role_name must be the proposed new_role's name."
    elif roles and role not in roles:
        return (f"Role {view.story.role_name!r} is not in INPUT.roles; use one of {sorted(roles.values())} "
                "or propose it as new_role.")
    ids = mockups.component_ids(view.mockup)
    dangling = [c.component_id for c in view.criteria if c.component_id and c.component_id not in ids]
    if dangling:
        return f"Criteria refer to components that are not in the mockup: {dangling}. Use ids from {sorted(ids)}."
    if not any(c.component_id for c in view.criteria):
        return "No criterion refers to the mockup: set component_id on criteria about what the view shows."
    untestable = [testability.describe(c.text, issues) for c in view.criteria
                  if (issues := testability.check(c.text))]
    if untestable:
        return ("Some criteria cannot be answered with yes or no: " + " | ".join(untestable)
                + ". Rewrite each as one simple, checkable condition.")
    return None


def _stored_new_view(view: NewView) -> dict[str, Any]:
    data = view.model_dump()
    for criterion in data["criteria"]:
        criterion["issues"] = [i.model_dump() for i in testability.check(criterion["text"])]
    return data


def apply_new_view(conn: sqlite3.Connection, project_id: int, data: ViewAddInput) -> None:
    """Add (or discard) a new-view card: story, criteria and mockup together, then make the
    story the current one. Called inside the input's transaction; one undo removes it all."""
    message = projects.get_message(conn, project_id, data.message_id)
    view = message.content.get("new_view") if message.role == "assistant" else None
    if not view:
        raise HTTPException(400, "That message has no new view to decide on")
    if "decided" in view:
        raise HTTPException(409, "That new view was already decided on")
    if data.decision == "discard":
        view["decided"] = {"added": False}
        projects.update_message(conn, message.id, message.content)
        return

    offered = view["criteria"]
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

    parts = dict(view["story"])
    if data.wording:
        parts.update(data.wording.model_dump())
    backlog.record_undo(conn, project_id, "view_added", title=parts["action"][:60])
    story = backlog.add_stories(conn, project_id, [backlog.StoryParts(**parts)], origin="ai")[0]
    backlog.append_criteria(conn, story.id, kept)
    mockup = mockups.create(conn, project_id, mockups.Tree(**view["mockup"]), note=f"new_view:{message.id}",
                            story_id=story.id)
    if view.get("new_role"):
        current = projects.roles(conn, project_id)
        if view["new_role"]["name"].casefold() not in {r.name.casefold() for r in current}:
            projects.replace_roles(conn, project_id, [*current, projects.Role(**view["new_role"])])
    conn.execute("UPDATE projects SET current_story_id = ?, step = 'refinements' WHERE id = ?",
                 (story.id, project_id))
    view["decided"] = {"added": True, "key": story.key, "mockup_id": mockup.id}
    projects.update_message(conn, message.id, message.content)


def mock_new_view(payload: dict[str, Any]) -> dict[str, Any]:
    """A stand-in new view: the chosen template (or the detail page) with three criteria on it."""
    data = payload["user_input"]
    template = data.get("template") or "detail"
    tree = payload.get("template") or localized(template, payload["language"])[1]
    ids = sorted(mockups.component_ids(mockups.Tree(**tree)))
    role = (payload["roles"] or [{"name": "Külastaja"}])[0]["name"]
    heading = next((i for i in ids if "title" in i or "heading" in i), ids[0])
    return {"story": {"role_name": role, "role_phrase": f"{role}na",
                      "action": f"kasutada vaadet: {data['text'][:80].rstrip('.')}",
                      "benefit": "saaksin vajaliku teabe ühest kohast"},
            "new_role": None,
            "criteria": [{"text": "Vaates on pealkiri.", "component_id": heading},
                         {"text": "Vaates on põhitegevuse nupp.", "component_id": None},
                         {"text": "Vaade on avatav menüüst.", "component_id": None}],
            "mockup": tree}


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
        "version": linked[0].version if linked else None,
        "mockup": linked[0].tree.model_dump() if linked else None,
    }
    if change.wording:
        data["after_title"] = backlog.title(backlog.StoryParts(
            role_name=story.role_name, **change.wording.model_dump()), project.language)
    return data


def _refuse_stale_change(conn: sqlite3.Connection, project_id: int, story: backlog.Story,
                         before: dict[str, Any]) -> None:
    """A change card holds the full wording, criteria and mockup it proposes. If the story moved on
    since (a hand edit, another change, a mockup edit), applying it would overwrite that work."""
    if "version" not in before:
        return  # a card stored before cards remembered what they were made for
    now = _mockup_base(conn, project_id, story)
    wording = {"role_phrase": story.role_phrase, "action": story.action, "benefit": story.benefit}
    criteria = [{"text": c.text, "component_id": c.component_id} for c in story.criteria]
    if (now["mockup_id"], now["version"], wording, criteria) != (
            before["mockup_id"], before["version"], before["wording"], before["criteria"]):
        raise _stale_card()


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
    _refuse_stale_change(conn, project_id, story, change["before"])
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
    backlog.check_status(conn, project_id, story.id, None)
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
    if "base" in proposal and proposal["base"] != _mockup_base(conn, project_id, story):
        raise _stale_card()
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
    asked = data  # what the user did; the AI is asked about `data`, which an idea turns into a view or refinement
    data = _effective_input(conn, project_id, data)
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
    idea = _stored_idea(conn, project_id, asked, turn) if turn.idea and asked.kind == "text" else None
    message = projects.add_message(conn, project_id, "assistant", {
        "text": turn.message,
        "intent": turn.intent if asked.kind == "text" else None,
        "idea": idea,
        "step": turn.step,
        "question": turn.question.model_dump() if turn.question else None,
        "roles": [r.model_dump() for r in turn.roles] if turn.roles else None,
        "stories": [st.model_dump() for st in turn.stories] if turn.stories else None,
        "priority": turn.priority.model_dump() if turn.priority else None,
        "proposal": _stored_proposal(conn, project_id, turn.proposal) if turn.proposal else None,
        "change": _stored_change(conn, project_id, turn.change) if turn.change else None,
        "new_view": _stored_new_view(turn.new_view) if turn.new_view else None,
        "next_steps": [s.model_dump() for s in turn.next_steps],
    })
    if idea:
        with conn:
            ideas.attach_card(conn, idea["idea_id"], message.id)
    return projects.state(conn, project_id)


def _stored_idea(conn: sqlite3.Connection, project_id: int, asked: Any, turn: Turn) -> dict[str, Any]:
    """The idea card as stored. The thought itself is kept at once as an open idea, so it is not
    lost if the card is ignored; nothing in the backlog changes before the user chooses."""
    text = " ".join(asked.text.split())[:1000]
    with conn:
        idea_id = ideas.create(conn, project_id, text)
    project = projects.get(conn, project_id)
    return {"idea_id": idea_id, "text": text, **turn.idea.model_dump(), "story_key": _current_key(conn, project)}
