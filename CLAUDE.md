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
  in place (upsert, never delete-and-reinsert) so links to surviving stories are kept
- `app/conversation.py`: guided conversation, one `POST /turn` per user input. User decisions
  (answers, roles, notes) are stored before the AI call; the AI payload is built from DB state;
  `check_turn` holds state-aware rules (question minimum/cap) retried via `run_task(check=...)`
- `app/mockups.py` + `app/mockup_templates.py`: mockups are a component tree (one node shape,
  per-type rules in `check_tree`), stored as versions, linked to stories. Never HTML: the browser
  renders trees in `public/js/mockup/render.js` via `h()` with `data-component-id` on every element
- `app/testability.py`: the one rule-based criteria check (evaluative / multiple / vague, ET+EN);
  the frontend never re-implements it, it calls `POST /api/criteria/check`
- `app/ai/`: AI layer. `providers.py` runs `codex exec` on a ChatGPT subscription (ported
  from acupoint) or `mock`/`off`; `schema.py` turns a Pydantic model into a strict
  `--output-schema`; `tasks.py` `run_task()` validates every answer and retries once.
  New AI features define a `Task` (instructions, response model, mock answer).

Frontend: ES modules in `public/js/` (`app.js` hash router, `views/`, `api.js`, `i18n.js`
`t()` strings). Build DOM only through `dom.js` `h()`, which inserts text as text nodes:
never assign data or AI output to `innerHTML`.

Planned (see GitHub issues): mockups as a validated component-JSON tree rendered by the app
(never AI HTML), one-way push to the Agile Tracker (`../urmas-agiilne-tracker`).

## Commands

- Tests: `.venv/bin/pytest` (no network, server or credentials needed)
- Run app: `./start.sh` (port 8010; the Agile Tracker uses 8000), `./start.sh stop` / `status`

## Conventions

- README and docs/ are in Estonian; issues, code and commits in English
- Workflow rules (issues, branching, testing, merging) come from the global CLAUDE.md
