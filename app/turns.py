"""The conversation queue: inputs wait their turn, one project's turns run one at a time.

A turn is what `conversation.take_turn` does: apply the user's input, ask the AI,
store its answer. Posting an input only queues it (`POST /turns`, answered at once),
so the user can give the next instruction while the AI is still working on the
previous one. A worker per project takes the queued inputs in the order they were
sent and runs each against the database state the previous one left; different
projects never wait for each other.

The queue is persisted (`turns`: queued, running, failed; a finished turn is deleted,
the messages keep the history). A failed turn does not block the ones behind it.
After a restart a turn that was running is marked failed and the queued ones run.

`POST /turn` is the same turn run through the same queue, answered when it has run
(and failing as one request, as it always did): for scripts and tests.
"""
from __future__ import annotations

import asyncio
import json
import logging
import sqlite3
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import TypeAdapter

from . import conversation, db, projects
from .ai import AIError

log = logging.getLogger(__name__)

MAX_QUEUED = 10
INPUT = TypeAdapter(conversation.UserInput)


def _failure(exc: Exception) -> tuple[str, str]:
    """(code, message) for a turn that did not finish."""
    if isinstance(exc, AIError):
        return exc.code, str(exc)
    if isinstance(exc, HTTPException):
        detail = exc.detail
        if isinstance(detail, dict):
            return str(detail.get("code", "rejected")), str(detail.get("message", detail))
        return "rejected", str(detail)
    return "internal", "The turn failed unexpectedly."


class TurnQueue:
    """Lives on `app.state`, so every server start (and every test client) gets a fresh one."""

    def __init__(self) -> None:
        self._workers: dict[int, asyncio.Task] = {}
        self._waiters: dict[int, asyncio.Future] = {}
        self._locks: dict[int, asyncio.Lock] = {}

    def lock(self, project_id: int) -> asyncio.Lock:
        """What a project's turns hold while they run; the backlog review takes it too."""
        return self._locks.setdefault(project_id, asyncio.Lock())

    # --- queueing ---------------------------------------------------------

    def enqueue(self, conn: sqlite3.Connection, project_id: int, data: Any,
                wait: bool = False) -> tuple[int, asyncio.Future | None]:
        projects.get(conn, project_id)
        waiting = conn.execute("SELECT COUNT(*) FROM turns WHERE project_id = ? AND status = 'queued'",
                               (project_id,)).fetchone()[0]
        if waiting >= MAX_QUEUED:
            raise HTTPException(429, {"code": "queue_full",
                                      "message": "Too many inputs are waiting; let the AI catch up."})
        with conn:
            cur = conn.execute("INSERT INTO turns (project_id, input, created_at) VALUES (?, ?, ?)",
                               (project_id, json.dumps(data.model_dump(), ensure_ascii=False), db.now()))
        turn_id = cur.lastrowid
        future = None
        if wait:
            future = asyncio.get_running_loop().create_future()
            self._waiters[turn_id] = future
        self.kick(project_id)
        return turn_id, future

    def kick(self, project_id: int) -> None:
        worker = self._workers.get(project_id)
        if worker is None or worker.done():
            self._workers[project_id] = asyncio.create_task(self._drain(project_id))

    # --- running ----------------------------------------------------------

    async def _drain(self, project_id: int) -> None:
        while True:
            conn = db.connect()
            try:
                row = conn.execute("SELECT * FROM turns WHERE project_id = ? AND status = 'queued' "
                                   "ORDER BY id LIMIT 1", (project_id,)).fetchone()
                if row is None:
                    return
                async with self.lock(project_id):
                    await self._run(conn, project_id, row)
            finally:
                conn.close()

    async def _run(self, conn: sqlite3.Connection, project_id: int, row: sqlite3.Row) -> None:
        turn_id = row["id"]
        waiter = self._waiters.pop(turn_id, None)
        with conn:
            conn.execute("UPDATE turns SET status = 'running' WHERE id = ?", (turn_id,))
        failure: Exception | None = None
        try:
            await conversation.take_turn(conn, project_id, INPUT.validate_python(json.loads(row["input"])))
        except asyncio.CancelledError:
            raise  # shutting down: the next start marks this turn failed
        except Exception as exc:  # noqa: BLE001 - whatever went wrong belongs to this turn only
            failure = exc
            if not isinstance(exc, (AIError, HTTPException)):
                log.exception("Turn %s of project %s failed", turn_id, project_id)
        with conn:
            if failure is None or waiter is not None:
                # Done, or the caller of POST /turn gets the error as its response.
                conn.execute("DELETE FROM turns WHERE id = ?", (turn_id,))
            else:
                code, message = _failure(failure)
                conn.execute("UPDATE turns SET status = 'failed', error_code = ?, error_message = ? "
                             "WHERE id = ?", (code, message, turn_id))
        if waiter is not None and not waiter.cancelled():
            if failure is None:
                waiter.set_result(None)
            else:
                waiter.set_exception(failure)

    # --- start and stop ---------------------------------------------------

    def recover(self) -> None:
        """A turn that was running when the server stopped did not finish; queued ones still run."""
        conn = db.connect()
        try:
            with conn:
                conn.execute("UPDATE turns SET status = 'failed', error_code = 'interrupted', "
                             "error_message = 'The server restarted while this was running.' "
                             "WHERE status = 'running'")
            for (project_id,) in conn.execute("SELECT DISTINCT project_id FROM turns "
                                              "WHERE status = 'queued'").fetchall():
                self.kick(project_id)
        finally:
            conn.close()

    async def stop(self) -> None:
        workers = list(self._workers.values())
        for worker in workers:
            worker.cancel()
        await asyncio.gather(*workers, return_exceptions=True)


def queue_of(request: Request) -> TurnQueue:
    return request.app.state.turns


# --- API -----------------------------------------------------------------

router = APIRouter(prefix="/api/projects", tags=["conversation"])


@router.post("/{project_id}/turns", response_model=projects.ProjectState, status_code=202)
async def post_turns(project_id: int, data: conversation.UserInput, request: Request,
                     conn: sqlite3.Connection = Depends(db.get_db)):
    """Queue one input and answer at once; the result arrives in the project state."""
    queue_of(request).enqueue(conn, project_id, data)
    return projects.state(conn, project_id)


@router.post("/{project_id}/turn", response_model=projects.ProjectState)
async def post_turn(project_id: int, data: conversation.UserInput, request: Request,
                    conn: sqlite3.Connection = Depends(db.get_db)):
    """Queue one input and answer when it has run."""
    _, future = queue_of(request).enqueue(conn, project_id, data, wait=True)
    await future
    return projects.state(conn, project_id)


def _item(conn: sqlite3.Connection, project_id: int, turn_id: int) -> sqlite3.Row:
    row = conn.execute("SELECT * FROM turns WHERE id = ? AND project_id = ?", (turn_id, project_id)).fetchone()
    if row is None:
        raise HTTPException(404, "Queued input not found")
    return row


@router.delete("/{project_id}/turns/{turn_id}", response_model=projects.ProjectState)
def delete_turn(project_id: int, turn_id: int, conn: sqlite3.Connection = Depends(db.get_db)):
    """Remove an input that is waiting or has failed; one that is running cannot be taken back."""
    row = _item(conn, project_id, turn_id)
    if row["status"] == "running":
        raise HTTPException(409, {"code": "turn_running", "message": "That input is being answered now."})
    with conn:
        conn.execute("DELETE FROM turns WHERE id = ?", (turn_id,))
    return projects.state(conn, project_id)


@router.post("/{project_id}/turns/{turn_id}/retry", response_model=projects.ProjectState, status_code=202)
async def retry_turn(project_id: int, turn_id: int, request: Request,
                     conn: sqlite3.Connection = Depends(db.get_db)):
    """Ask the AI again after it failed. The user's input was already stored when it failed."""
    row = _item(conn, project_id, turn_id)
    if row["status"] != "failed" or not (row["error_code"] or "").startswith("ai_"):
        raise HTTPException(409, {"code": "not_retryable", "message": "Only an AI failure can be retried."})
    with conn:
        conn.execute("DELETE FROM turns WHERE id = ?", (turn_id,))
    queue_of(request).enqueue(conn, project_id, conversation.RetryInput(kind="retry"))
    return projects.state(conn, project_id)
