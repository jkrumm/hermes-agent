#!/usr/bin/env python3
"""Prose — run a draft through agent-gateway's `prose` job (lint → review → rewrite → gate).

Reads the draft from a file or stdin, POSTs `{"tool":"prose", ...}` to
`http://localhost:7705/api/jobs` (same submit/poll shape as project-narratives.py), polls to a
terminal status, and writes the final text to stdout (or `--out`). One summary line goes to
stderr: `prose: kept=<rewrite|original> [(<reason>)] cost=$<usd>`. Exit 1 when the job fails
or the gateway is unreachable. A kept original is a normal outcome (the gate judged the
rewrite worse): the original text is still written, exit 0.

Usage: prose.py [<file>|-] [--medium article|vault|docs|briefing|landing|ui|chat]
                [--language en|de] [--context <file>] [--no-verdict-first] [--out <file>]

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
_TERMINAL_FAILURE_STATUSES = frozenset({"failed", "interrupted", "cancelled"})
_TRANSPORT_ERRORS = (urllib.error.URLError, json.JSONDecodeError, TimeoutError, OSError)


class ProseError(Exception):
    pass


def _request(url: str, body: dict | None = None) -> dict:
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(
        url, data=data, headers={"content-type": "application/json"},
        method="POST" if body is not None else "GET",
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return json.loads(resp.read().decode())
    except urllib.error.HTTPError as err:
        detail = err.read().decode(errors="replace")[:300]
        raise ProseError(f"gateway HTTP {err.code}: {detail}") from err
    except _TRANSPORT_ERRORS as err:
        raise ProseError(f"gateway unreachable: {err}") from err


def run_prose_job(base: str, params: dict, *, poll_interval: float = POLL_INTERVAL) -> dict:
    """Submit the job, poll until `done`, return its `result`. Raises ProseError otherwise."""
    submitted = _request(f"{base}/api/jobs", {"tool": "prose", "params": params})
    job_id = (
        submitted.get("jobId") or submitted.get("id")
        or (submitted.get("job") or {}).get("id")
    )
    if not job_id:
        raise ProseError(f"submit refused: {json.dumps(submitted)[:300]}")

    started = time.monotonic()
    while True:
        time.sleep(poll_interval)
        polled = _request(f"{base}/api/jobs/{job_id}")
        job = polled.get("job") or polled
        status = job.get("status")
        if status == "done":
            result = job.get("result")
            if not isinstance(result, dict) or not isinstance(result.get("text"), str):
                raise ProseError(f"job {job_id} done without a text result")
            return result
        if status in _TERMINAL_FAILURE_STATUSES:
            raise ProseError(f"job {job_id} {status}: {job.get('error') or 'no detail'}")
        elapsed = int(time.monotonic() - started)
        if elapsed and elapsed % 30 < poll_interval:
            print(f"prose: job {job_id} {status or 'running'} ({elapsed}s)", file=sys.stderr)


def summary_line(result: dict) -> str:
    kept = result.get("kept", "?")
    reason = result.get("keptReason")
    cost = (result.get("usage") or {}).get("costUsd")
    cost_text = f"${cost:.3f}" if isinstance(cost, (int, float)) else "n/a"
    return f"prose: kept={kept}" + (f" ({reason})" if reason else "") + f" cost={cost_text}"


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
    parser.add_argument("--out", help="write the final text here instead of stdout")
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
        result = run_prose_job(os.environ.get(BASE_ENV, DEFAULT_BASE), params)
    except ProseError as err:
        print(f"prose: {err}", file=sys.stderr)
        return 1

    if args.out:
        Path(args.out).expanduser().write_text(result["text"])
    else:
        sys.stdout.write(result["text"])
    print(summary_line(result), file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
