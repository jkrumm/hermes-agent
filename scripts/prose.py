#!/usr/bin/env python3
"""Prose — run a draft through the `agw prose-polish` workflow (lint → review → rewrite → gate).

Reads the draft from a file or stdin, pipes it to `agw prose-polish` (agent-workflows; shelled
out through `agw_run.py`, caller `hermes`), resumes with `agw run wait` on exit 10 until the
run ends, and writes the final text to stdout (or `--out`). One summary line goes to stderr:
`prose: kept=<rewrite|original> [(<reason>)] cost=$<usd>`; `cost=n/a` when the run reports no
USD figure. Exit 1 when the run fails, the wall-clock `--timeout` (default 900 s) expires, agw
is unreachable, or `--out` cannot be written; every such message carries the run id when there
is one. A kept original is a normal outcome (the gate judged the rewrite worse): the original
text is still written, exit 0.

`--out` is atomic: the text goes to a temp file in the target directory and is moved into place
only on success, so a failed run never leaves an empty or truncated file behind. The submit is
never repeated (a retry could queue a second paid run); only `agw run wait <runId>` resumes.

Usage: prose.py [<file>|-] [--medium article|vault|docs|briefing|landing|ui|chat]
                [--language en|de] [--context <file>] [--no-verdict-first] [--out <file>]
                [--timeout <seconds>]

Source of truth: ~/SourceRoot/hermes-agent/scripts/prose.py
~/.hermes/scripts/ is itself a symlink to this directory (see make setup).
Skill: skills/prose/SKILL.md.
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import agw_run  # noqa: E402

MEDIUMS = ("article", "vault", "docs", "briefing", "landing", "ui", "chat")
DEFAULT_TIMEOUT = 900


class ProseError(Exception):
    pass


def run_prose(args: list[str], text: str, *, timeout: float = DEFAULT_TIMEOUT) -> tuple[str, dict]:
    """Run `agw prose-polish` to its end; return `(run_id, output)`. Raises ProseError otherwise."""
    try:
        record = agw_run.run(["prose-polish", *args], stdin=text, timeout=timeout, label="prose")
    except agw_run.AgwError as err:
        where = f"run {err.run_id}: " if err.run_id else ""
        raise ProseError(f"{where}{err}") from err
    run_id = record.get("runId") or "?"
    output = record.get("output")
    if not isinstance(output, dict) or not isinstance(output.get("text"), str):
        raise ProseError(f"run {run_id} done without a text result")
    return run_id, output


def summary_line(result: dict) -> str:
    kept = result.get("kept", "?")
    reason = result.get("reason")
    cost = result.get("cost")
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
    parser = argparse.ArgumentParser(description="Run a draft through the agw prose-polish workflow.")
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

    agw_args = ["--medium", args.medium]
    if args.no_verdict_first:
        agw_args.append("--no-verdict-first")
    if args.language:
        agw_args += ["--language", args.language]
    if context:
        agw_args += ["--context", context]

    try:
        run_id, result = run_prose(agw_args, text, timeout=args.timeout)
    except ProseError as err:
        print(f"prose: {err}", file=sys.stderr)
        return 1

    if args.out:
        try:
            write_atomic(Path(args.out).expanduser(), result["text"])
        except OSError as err:
            print(f"prose: run {run_id} finished but cannot write {args.out}: {err}", file=sys.stderr)
            return 1
    else:
        sys.stdout.write(result["text"])
    print(summary_line(result), file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
