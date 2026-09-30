"""AI providers: the Codex CLI on a ChatGPT subscription, a local mock, or off.

The Codex provider is ported from acupoint (verified there against codex-cli
0.154.0 on a ChatGPT plan). What shapes it:

- `codex exec` waits for stdin even when given a prompt another way, so the
  prompt is written to stdin and the pipe closed; otherwise it hangs.
- `--ignore-user-config` still authenticates from CODEX_HOME, so a server call
  keeps the login without inheriting the developer's own Codex settings.
- `--output-schema` makes the model return JSON and `-o` writes only the final
  message, so nothing here parses prose.

The subprocess gets no shell, a throwaway working directory, a read-only
sandbox, a minimal environment and a hard timeout that kills its process group.
"""
from __future__ import annotations

import asyncio
import json
import os
import signal
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Protocol

from .. import config


class AIError(Exception):
    """An AI call failed in a way the user should be told about.

    `code` lets the frontend pick a message; `str(exc)` is the English detail.
    """

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


@dataclass
class AIRequest:
    prompt: str
    schema: dict[str, Any]
    mock_answer: Callable[[], Any]


class Provider(Protocol):
    name: str

    async def run(self, request: AIRequest) -> Any: ...


class MockProvider:
    """Answers from the task's own fixture, without leaving the machine."""

    name = "mock"

    async def run(self, request: AIRequest) -> Any:
        return request.mock_answer()


class CodexProvider:
    name = "codex"

    async def run(self, request: AIRequest) -> Any:
        binary = config.codex_binary()
        if not binary:
            raise AIError("ai_unavailable",
                          "The Codex CLI was not found. Install it or set CODEX_BIN.")
        with tempfile.TemporaryDirectory(prefix="mockup-maker-ai-") as work:
            work_dir = Path(work)
            schema_path = work_dir / "schema.json"
            out_path = work_dir / "out.json"
            schema_path.write_text(json.dumps(request.schema), encoding="utf-8")
            stderr = await _exec(_argv(binary, schema_path, out_path), request.prompt, work_dir)
            text = out_path.read_text(encoding="utf-8").strip() if out_path.exists() else ""
            if not text:
                raise AIError("ai_unavailable", f"Codex returned nothing. {_tail(stderr)}".strip())
            try:
                return json.loads(text)
            except ValueError as exc:
                raise AIError("ai_invalid_answer",
                              f"Codex returned text that is not JSON: {exc}") from exc


def _argv(binary: str, schema_path: Path, out_path: Path) -> list[str]:
    return [
        binary, "exec",
        "--ephemeral",              # no session files left behind
        "--ignore-user-config",     # the developer's config is not the server's
        "--skip-git-repo-check",    # the working directory is a temp dir
        "-s", "read-only",
        "--output-schema", str(schema_path),
        "-o", str(out_path),
        "-m", config.ai_model(),
        "-c", f"model_reasoning_effort={config.ai_reasoning()}",
        "-",                        # prompt arrives on stdin
    ]


def _environment() -> dict[str, str]:
    """The little the CLI needs. Nothing about this application is passed on."""
    env = {"PATH": os.environ.get("PATH", "/usr/bin:/bin"),
           "HOME": os.environ.get("HOME", ""),
           "LANG": os.environ.get("LANG", "en_US.UTF-8")}
    codex_home = config.codex_home()
    if codex_home:
        env["CODEX_HOME"] = codex_home
    return env


async def _exec(argv: list[str], prompt: str, work_dir: Path) -> str:
    try:
        process = await asyncio.create_subprocess_exec(
            *argv, cwd=str(work_dir), env=_environment(),
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            start_new_session=True)      # so a timeout can kill the whole group
    except OSError as exc:
        raise AIError("ai_unavailable", f"Could not start the Codex CLI: {exc}") from exc
    timeout = config.ai_timeout()
    try:
        _, err = await asyncio.wait_for(process.communicate(prompt.encode("utf-8")),
                                        timeout=timeout)
    except asyncio.TimeoutError as exc:
        _kill(process)
        await process.wait()
        raise AIError("ai_timeout", f"Codex did not answer within {timeout} seconds.") from exc
    if process.returncode != 0:
        raise AIError("ai_unavailable",
                      f"Codex exited with status {process.returncode}. "
                      f"{_tail(err.decode('utf-8', 'replace'))}".strip())
    return err.decode("utf-8", "replace")


def _kill(process) -> None:
    try:
        os.killpg(os.getpgid(process.pid), signal.SIGKILL)
    except (ProcessLookupError, PermissionError):
        process.kill()


def _tail(text: str, limit: int = 400) -> str:
    """The end of the CLI's stderr, which is where it says what went wrong."""
    return " ".join((text or "").split())[-limit:]


def get(name: str | None = None) -> Provider:
    chosen = name or config.ai_provider()
    if chosen == "off":
        raise AIError("ai_disabled", "AI is turned off on this server.")
    if chosen == "codex":
        return CodexProvider()
    return MockProvider()
