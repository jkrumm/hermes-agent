"""agw transport — the one place Hermes' scripts talk to the platform.

Shells out to the `agw` CLI (agent-workflows) with `--format json`; there is no credential
to resolve and no base URL. Every call carries `AGW_CALLER=hermes` so the platform
attributes usage to Hermes.

- `call(args)` — one command, returns the parsed JSON stdout (a read, or a run that ended
  inside the CLI's wait budget).
- `run(args)` — a workflow run to its end: on exit 10 (`pending`) it resumes with
  `agw run wait <runId>` until the run ends, the optional wall-clock `timeout` passes, or
  it fails. A progress line goes to stderr on every resume, which is what keeps a healthy
  long run alive under Hermes' idle-output cron watchdog.

Raises `AgwError` (carrying `run_id` when there is one) on every failure; callers decide
how to degrade.

Source of truth: ~/SourceRoot/hermes-agent/scripts/agw_run.py
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

CALLER = "hermes"
EXIT_PENDING = 10
# agw is `#!/usr/bin/env bun`: a cron-sanitized PATH may lack bun (Homebrew) and ~/.local/bin.
_PATH_PREFIX = f"{Path.home() / '.local' / 'bin'}:/opt/homebrew/bin:/usr/local/bin"


class AgwError(Exception):
    def __init__(self, message: str, *, run_id: str | None = None) -> None:
        super().__init__(message)
        self.run_id = run_id


def _env() -> dict[str, str]:
    env = os.environ.copy()
    env["AGW_CALLER"] = CALLER
    env["PATH"] = f"{_PATH_PREFIX}:{env.get('PATH', '/usr/bin:/bin')}"
    return env


def _exec(args: list[str], stdin: str | None) -> tuple[int, Any, str]:
    """Run `agw <args> --format json`; return (exit code, parsed stdout or None, stderr)."""
    try:
        proc = subprocess.run(
            ["agw", *args, "--format", "json"],
            input=stdin, capture_output=True, text=True, env=_env(),
        )
    except OSError as err:
        raise AgwError(f"agw not runnable: {err}") from err
    try:
        payload = json.loads(proc.stdout) if proc.stdout.strip() else None
    except ValueError:
        payload = None
    return proc.returncode, payload, proc.stderr


def _failure(args: list[str], rc: int, payload: Any, stderr: str) -> AgwError:
    run_id = payload.get("runId") if isinstance(payload, dict) else None
    detail = ""
    if isinstance(payload, dict):
        err = payload.get("error")
        if isinstance(err, dict):
            detail = err.get("message") or ""
        status = payload.get("status")
        if status and not detail:
            detail = f"run {status}"
    if not detail:
        try:
            err = json.loads(stderr).get("error") or {}
            detail = err.get("message") or ""
        except (ValueError, AttributeError):
            detail = stderr.strip()[:300]
    return AgwError(f"agw {args[0]} exit {rc}: {detail or 'no detail'}", run_id=run_id)


def call(args: list[str], *, stdin: str | None = None) -> Any:
    """One `agw` command that must exit 0; returns the parsed JSON stdout."""
    rc, payload, stderr = _exec(args, stdin)
    if rc != 0 or payload is None:
        raise _failure(args, rc, payload, stderr)
    return payload


def run(
    args: list[str], *, stdin: str | None = None, timeout: float | None = None, label: str = "agw",
) -> dict[str, Any]:
    """A workflow run to its end; returns the run record (`runId`, `status`, `output`, `cost`).

    `timeout` (seconds, wall clock from the submit) bounds the resume loop; None waits as long
    as the run takes. The submit is never repeated: only `agw run wait <runId>` resumes."""
    started = time.monotonic()
    rc, payload, stderr = _exec(args, stdin)
    while rc == EXIT_PENDING:
        run_id = payload.get("runId") if isinstance(payload, dict) else None
        if not run_id:
            raise _failure(args, rc, payload, stderr)
        waited = int(time.monotonic() - started)
        if timeout is not None and time.monotonic() - started >= timeout:
            raise AgwError(
                f"run {run_id} not finished after {int(timeout)}s (status: {payload.get('status') or 'unknown'}); "
                f"it may still be running — resume with `agw run wait {run_id}`",
                run_id=run_id,
            )
        print(f"{label}: run {run_id} still {payload.get('status') or 'running'} ({waited}s)", file=sys.stderr)
        rc, payload, stderr = _exec(["run", "wait", run_id], None)
    if rc != 0 or not isinstance(payload, dict):
        raise _failure(args, rc, payload, stderr)
    if payload.get("status") != "done":
        raise _failure(args, rc, payload, stderr)
    return payload
