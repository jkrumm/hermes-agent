#!/usr/bin/env python3
"""Regression check for the gateway's API-server routing name in `.env.tpl`.

argo sends `model: "hermes"` to the `:8642` API server. The server only routes
that name to the brain when `API_SERVER_MODEL_NAME=hermes` resolves at startup,
so the line must exist once, as a literal (a routing label, not a secret — an
op:// ref here would fail closed and silently fall back to gpt-6-luna).

Run against the live tree:

    ~/.hermes/hermes-agent/venv/bin/python3 tests/test_env_tpl.py

Exit status is 0 only when every case matches.
"""

from __future__ import annotations

import sys
from pathlib import Path

ENV_TPL = Path(__file__).resolve().parent.parent / ".env.tpl"

failures: list[str] = []


def check(name: str, cond: bool) -> None:
    if cond:
        print(f"  ok   {name}")
    else:
        failures.append(name)
        print(f"  FAIL {name}")


lines = [ln.split("#", 1)[0].strip() for ln in ENV_TPL.read_text().splitlines()]
assignments = [ln for ln in lines if ln.startswith("API_SERVER_MODEL_NAME=")]

print("1. .env.tpl — API_SERVER_MODEL_NAME")
check("declared exactly once", len(assignments) == 1)
check("value is the literal hermes", assignments == ["API_SERVER_MODEL_NAME=hermes"])
check("not an op:// reference", not any("op://" in a for a in assignments))

print()
if failures:
    print(f"{len(failures)} failure(s):")
    for f in failures:
        print(f"  - {f}")
    sys.exit(1)
print("all cases as expected")
