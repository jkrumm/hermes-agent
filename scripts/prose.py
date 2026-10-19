#!/usr/bin/env python3
"""Prose — run a draft through agent-gateway's `prose` job (lint → review → rewrite → gate).

Reads the draft from a file or stdin, POSTs `{"tool":"prose", ...}` to
`http://localhost:7705/api/jobs` (same submit/poll shape as project-narratives.py), polls to a
terminal status, and writes the final text to stdout (or `--out`). One summary line goes to
stderr: `prose: kept=<rewrite|original> [(<reason>)] cost=$<usd>`; `cost=n/a` when the gateway
reports no USD figure for the run. Exit 1 when the job fails, the wall-clock `--timeout`
(default 900 s) expires, the gateway is unreachable, or `--out` cannot be written; every such
message carries the job id. A kept original is a normal outcome (the gate judged the rewrite
worse): the original text is still written, exit 0.

`--out` is atomic: the text goes to a temp file in the target directory and is moved into place
only on success, so a failed run never leaves an empty or truncated file behind. Polling retries
transient GET failures (connection reset, 5xx, gateway restart) with backoff inside the
deadline; the POST submit is never retried (a retry could queue a second paid job).

Usage: prose.py [<file>|-] [--medium article|vault|docs|briefing|landing|ui|chat]
                [--language en|de] [--context <file>] [--no-verdict-first] [--out <file>]
                [--timeout <seconds>]

Source of truth: ~/SourceRoot/hermes-agent/scripts/prose.py
~/.hermes/scripts/ is itself a symlink to this directory (see make setup).
Skill: skills/prose/SKILL.md.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

DEFAULT_BASE = "http://localhost:7705"
BASE_ENV = "HERMES_PROSE_AGENT_GATEWAY_BASE"
MEDIUMS = ("article", "vault", "docs", "briefing", "landing", "ui", "chat")
POLL_INTERVAL = 3
MAX_BACKOFF = 30
DEFAULT_TIMEOUT = 900
PROGRESS_INTERVAL = 30
# agent-gateway JobStatus (server/jobs/types.ts): pending | running | done | failed | interrupted | cancelled
_TERMINAL_FAILURE_STATUSES = frozenset({"failed", "interrupted", "cancelled"})
_TRANSPORT_ERRORS = (OSError, ValueError)


class ProseError(Exception):
    pass


class TransientError(ProseError):
    """A failure worth retrying on a GET poll: transport error, bad body, or a 5xx."""


def _request(url: str, body: dict | None = None) -> dict:
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(
        url, data=data, headers={"content-type": "application/json"},
        method="POST" if body is not None else "GET",
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            parsed = json.loads(resp.read().decode())
    except urllib.error.HTTPError as err:
        detail = err.read().decode(errors="replace")[:300]
        failure = TransientError if err.code >= 500 else ProseError
        raise failure(f"gateway HTTP {err.code}: {detail}") from err
    except _TRANSPORT_ERRORS as err:
        raise TransientError(f"gateway unreachable: {err}") from err
    if not isinstance(parsed, dict):
        raise ProseError(f"gateway returned a non-object body: {json.dumps(parsed)[:300]}")
    return parsed


def _job_of(response: dict, what: str) -> dict:
    job = response.get("job")
    if not isinstance(job, dict):
        raise ProseError(f"{what}: {json.dumps(response)[:300]}")
    return job


def run_prose_job(
    base: str, params: dict, *, poll_interval: float = POLL_INTERVAL, timeout: float = DEFAULT_TIMEOUT,
) -> tuple[str, dict]:
    """Submit the job, poll until `done`, return `(job_id, result)`. Raises ProseError otherwise.

    The submit is never retried. Transient poll failures back off and retry until `timeout`
    seconds (wall clock) have passed since the submit; expiry raises with the job id.
    """
    submitted = _request(f"{base}/api/jobs", {"tool": "prose", "params": params})
    job_id = _job_of(submitted, "submit refused").get("id")
    if not isinstance(job_id, str) or not job_id:
        raise ProseError(f"submit refused: {json.dumps(submitted)[:300]}")

    started = time.monotonic()
    deadline = started + timeout
    last_report = started
    status: str | None = None
    last_error: ProseError | None = None
    failures = 0
    while True:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            detail = f"; last poll error: {last_error}" if last_error else ""
            raise ProseError(
                f"job {job_id} not finished after {int(timeout)}s (last status: {status or 'unknown'}"
                f"{detail}); it may still be running on the gateway"
            )
        time.sleep(min(min(poll_interval * 2 ** failures, MAX_BACKOFF), remaining))
        try:
            job = _job_of(_request(f"{base}/api/jobs/{job_id}"), "poll returned no job")
        except TransientError as err:
            failures += 1
            last_error = err
            continue
        except ProseError as err:
            raise ProseError(f"job {job_id}: {err}") from err
        failures = 0
        last_error = None
        status = job.get("status")
        if status == "done":
            result = job.get("result")
            if not isinstance(result, dict) or not isinstance(result.get("text"), str):
                raise ProseError(f"job {job_id} done without a text result")
            return job_id, result
        if status in _TERMINAL_FAILURE_STATUSES:
            raise ProseError(f"job {job_id} {status}: {job.get('error') or 'no detail'}")
        now = time.monotonic()
        if now - last_report >= PROGRESS_INTERVAL:
            last_report = now
            print(f"prose: job {job_id} {status or 'running'} ({int(now - started)}s)", file=sys.stderr)


def summary_line(result: dict) -> str:
    kept = result.get("kept", "?")
    reason = result.get("keptReason")
    cost = (result.get("usage") or {}).get("costUsd")
    cost_text = f"${cost:.3f}" if isinstance(cost, (int, float)) else "n/a"
    return f"prose: kept={kept}" + (f" ({reason})" if reason else "") + f" cost={cost_text}"


def write_atomic(path: Path, text: str) -> None:
    """Write `text` to `path` via a temp file in the same directory, so a failure leaves no partial file."""
    tmp = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    # 0o666 & ~umask, like a plain open(); mkstemp would force 0600 onto the target.
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o666)
    try:
        with os.fdopen(fd, "w") as handle:
            handle.write(text)
        os.replace(tmp, path)
    except BaseException:
        tmp.unlink(missing_ok=True)
        raise


def _read(path: str) -> str:
    return sys.stdin.read() if path == "-" else Path(path).expanduser().read_text()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run a draft through agent-gateway's prose job.")
    parser.add_argument("file", nargs="?", default="-", help="draft file, or - for stdin (default)")
    parser.add_argument("--medium", choices=MEDIUMS, default="vault")
    parser.add_argument("--language", choices=("en", "de"), help="default: auto-detect")
    parser.add_argument("--context", help="file with an outline/TLDR of the surrounding document")
    parser.add_argument("--no-verdict-first", action="store_true",
                        help="keep the author's order (criteria → candidates → verdict)")
    parser.add_argument("--out", help="write the final text here (atomically) instead of stdout")
    parser.add_argument("--timeout", type=float, default=DEFAULT_TIMEOUT,
                        help=f"give up polling after this many seconds (default {DEFAULT_TIMEOUT})")
    args = parser.parse_args(argv)

    try:
        text = _read(args.file)
        context = _read(args.context) if args.context else None
    except OSError as err:
        print(f"prose: cannot read input: {err}", file=sys.stderr)
        return 1
    if not text.strip():
        print("prose: empty input", file=sys.stderr)
        return 1

    params: dict = {"text": text, "medium": args.medium, "verdictFirst": not args.no_verdict_first}
    if args.language:
        params["language"] = args.language
    if context:
        params["context"] = context

    try:
        job_id, result = run_prose_job(
            os.environ.get(BASE_ENV, DEFAULT_BASE), params, timeout=args.timeout,
        )
    except ProseError as err:
        print(f"prose: {err}", file=sys.stderr)
        return 1

    if args.out:
        try:
            write_atomic(Path(args.out).expanduser(), result["text"])
        except OSError as err:
            print(f"prose: job {job_id} finished but cannot write {args.out}: {err}", file=sys.stderr)
            return 1
    else:
        sys.stdout.write(result["text"])
    print(summary_line(result), file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
