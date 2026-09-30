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

Planned (see GitHub issues): AI via Codex CLI on a ChatGPT subscription (acupoint pattern,
`mock` provider for tests), mockups as a validated component-JSON tree rendered by the app
(never AI HTML), one-way push to the Agile Tracker (`../urmas-agiilne-tracker`).

## Commands

- Tests: `.venv/bin/pytest` (no network, server or credentials needed)
- Run app: `./start.sh` (port 8010; the Agile Tracker uses 8000), `./start.sh stop` / `status`

## Conventions

- README and docs/ are in Estonian; issues, code and commits in English
- Workflow rules (issues, branching, testing, merging) come from the global CLAUDE.md
