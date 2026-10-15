# Mockup Maker: Project Facts

School assignment: guided AI conversation that turns a vague client idea into user stories,
acceptance criteria and wireframe mockups. The AI leads, the human decides: no AI proposal
reaches the backlog or changes a story without user confirmation.

## Architecture

FastAPI monolith (Python 3.12, Pydantic v2): REST API under `/api/*` and the vanilla
HTML/CSS/JS frontend from `public/` (no build tools). Storage is SQLite; schema changes are
append-only entries in `app/db.py` `MIGRATIONS`, tracked with `PRAGMA user_version`.

- `app/main.py`: app setup, lifespan (runs migrations), static mounting
- `app/config.py`: env config; `.env` is loaded without overriding the real environment
- `app/db.py`: connections and migrations
- `app/projects.py`: projects, conversation messages, current step and the resume
  suggestion (deterministic from step and history, so it works with AI off)
- `app/backlog.py`: stories. Connextra parts stored separately (`role_name`, `role_phrase` =
  Estonian essive as the title starts, `action`, `benefit`); the title is always composed, never stored.
  Every backlog change calls `record_undo()` first in the same transaction; `undo()` restores rows
  in place (upsert, never delete-and-reinsert) so links to surviving stories are kept. Definition of Ready
  lives in `readiness()`; every change that can affect it calls `check_status()` in its transaction
- `app/conversation.py`: guided conversation, one `POST /turn` per user input. User decisions
  (answers, roles, notes) are stored before the AI call; the AI payload is built from DB state;
  `check_turn` holds state-aware rules (question minimum/cap) retried via `run_task(check=...)`.
  Cards: question, roles, stories, priority, proposal (criteria + mockup), change (refinement),
  new_view (story + criteria + mockup from a description). Resume actions offered by
  `projects.RESUME_ACTIONS` must each have a handler in `public/js/views/chat.js` `RESUME` and
  labels in both languages (tests/test_resume_actions.py)
- `app/mockups.py` + `app/mockup_templates.py`: mockups are a component tree (one node shape,
  per-type rules in `check_tree`), stored as versions, linked to stories. Never HTML: the browser
  renders trees in `public/js/mockup/render.js` via `h()` with `data-component-id` on every element.
  Device frames (`public/js/mockup/frame.js`, browser around desktop, phone around mobile) are
  presentation only, never part of the tree; the PNG gets a browser frame with `frame=true`, its
  address from `mockup_png.site_address()` (frame.js `siteAddress()` must match it)
- `app/mockup_chat.py`: AI chat beside a mockup, its own task (not a turn). An instruction plus the
  `base_version` it was made on returns the full new tree and the full criteria of every linked
  story that must follow; applied at once in one transaction (`record_undo` first, new version with
  note `ai`, criteria, `check_status`, chat rows in `mockup_messages`). A stale `base_version` is a
  409; an unchanged tree is a reply without a version. Backlog `undo()` flags the rolled-back
  messages `undone`. Frontend: `public/js/mockup/chat.js` inside the viewer
- `app/review.py`: AI backlog review, its own task (not a turn). Findings carry one proposal
  each; `uncovered()` fills rule-known problems the model missed; applying reuses backlog
  split/merge/update so it is checked and undoable
- `app/testability.py`: the one rule-based criteria check (evaluative / multiple / vague, ET+EN);
  the frontend never re-implements it, it calls `POST /api/criteria/check`
- `app/tracker.py` + `app/mockup_png.py`: one-way push to the Agile Tracker through its API only
  (it forbids unknown fields; `tracker_links` makes re-pushes update). Mockups go as PNG from a
  small Pillow layout engine; tests use `FakeTracker` in tests/test_tracker.py, never a live tracker
- `app/export.py`: backlog export to Markdown and CSV (UTF-8 with BOM)
- `app/templates.py`: built-in and user-saved project templates
- `app/ai/`: AI layer. `providers.py` runs `codex exec` on a ChatGPT subscription (ported
  from acupoint) or `mock`/`off`; `schema.py` turns a Pydantic model into a strict
  `--output-schema`; `tasks.py` `run_task()` validates every answer and retries once.
  New AI features define a `Task` (instructions, response model, mock answer).

Frontend: ES modules in `public/js/` (`app.js` hash router, `views/`, `api.js`, `i18n.js`).
The header and every page share `--page-width` in `styles.css`, so their edges line up.
UI strings: `t()` in the viewer's language (every key in both `et` and `en`). A project's content
language (`projects.language`) is separate: story sentences use `storyTitle()`/`contentText()`
with it, never `t()`. Build DOM only through `dom.js` `h()`, which inserts text as text nodes:
never assign data or AI output to `innerHTML`.

## Commands

- Tests: `.venv/bin/pytest` (no network, server or credentials needed; `tests/conftest.py` resets
  AI and tracker settings so a developer `.env` never reaches a test)
- Run app: `./start.sh` (port from `.env`, default 8010; the Agile Tracker uses 8000),
  `./start.sh stop` / `status`

## Conventions

- README and docs/ are in Estonian; issues, code and commits in English
- Workflow rules (issues, branching, testing, merging) come from the global CLAUDE.md
