#!/usr/bin/env python3
"""Regression suite for `scripts/ntfy-publish.sh`.

Stub `curl` (records argv + body) and stub `secrets-run` in a tmp dir; no network,
no 1Password. Asserts the URL, the headers, the 4096-byte clip on a line boundary,
and the loud failures (missing token, failing curl, missing base URL).

Run:

    ~/.hermes/hermes-agent/venv/bin/python3 tests/test_ntfy_publish.py
"""

import os
import subprocess
import sys
import tempfile
from pathlib import Path

SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "ntfy-publish.sh"
failures: list[str] = []


def check(name, got, want):
    if got == want:
        print(f"  ok   {name}")
    else:
        failures.append(name)
        print(f"  FAIL {name}: got {got!r}, want {want!r}")


def setup(tmp: Path, token="tok-123", curl_rc=0):
    sr = tmp / "secrets-run"
    sr.write_text(f'#!/bin/sh\n[ "$1" = read ] && [ "$2" = op://common/ntfy/TOKEN ] || exit 2\n'
                  + (f"echo {token}\n" if token else "exit 1\n"))
    curl = tmp / "curl"
    curl.write_text(f'#!/bin/sh\nprintf "%s\\n" "$@" > "{tmp}/argv"\n'
                    f'for a in "$@"; do last="$a"; done\n'
                    f'printf "%s" "$last" > "{tmp}/body"\n'
                    + ("" if curl_rc == 0 else 'echo "boom" >&2\n') + f"exit {curl_rc}\n")
    for p in (sr, curl):
        p.chmod(0o755)
    return {"PATH": os.environ["PATH"], "HOME": str(tmp), "SECRETS_RUN_BIN": str(sr),
            "CURL_BIN": str(curl), "NTFY_URL": "http://ntfy.invalid",
            "NTFY_CONFIG": str(tmp / "absent.yml")}


def run(env, args, stdin=""):
    return subprocess.run(["/bin/bash", str(SCRIPT), *args], env=env, input=stdin,
                          capture_output=True, text=True, timeout=30)


print("publish")
with tempfile.TemporaryDirectory() as d:
    tmp = Path(d)
    env = setup(tmp)
    r = run(env, ["updates", "--title", "Usage weekly", "--priority", "high", "--tags", "a,b"], "hello\nworld\n")
    argv = (tmp / "argv").read_text().splitlines()
    check("exit 0", r.returncode, 0)
    check("url", "http://ntfy.invalid/updates" in argv, True)
    check("bearer", "Authorization: Bearer tok-123" in argv, True)
    check("title header", "Title: Usage weekly" in argv, True)
    check("priority header", "Priority: high" in argv, True)
    check("tags header", "Tags: a,b" in argv, True)
    check("markdown header", "Markdown: yes" in argv, True)
    check("body from stdin", (tmp / "body").read_text(), "hello\nworld")

    run(env, ["models", "last-arg body"])
    check("body from last arg", (tmp / "body").read_text(), "last-arg body")

print("clip")
with tempfile.TemporaryDirectory() as d:
    tmp = Path(d)
    env = setup(tmp)
    big = "".join(f"line {i:04d} " + "x" * 80 + "\n" for i in range(200))
    r = run(env, ["updates"], big)
    sent = (tmp / "body").read_text()
    check("clip: exit 0", r.returncode, 0)
    check("clip: under the ntfy cap", len(sent.encode()) < 4096, True)
    check("clip: notice present", "full text is in the job's cron output" in sent, True)
    kept = sent.split("\n\n(clipped")[0].splitlines()
    check("clip: whole lines only", all(l.startswith("line ") and l.endswith("x" * 80) for l in kept), True)
    run(env, ["updates"], "short\n")
    check("no clip when short", (tmp / "body").read_text(), "short")

print("failures")
with tempfile.TemporaryDirectory() as d:
    tmp = Path(d)
    r = run(setup(tmp, token=""), ["updates", "x"])
    check("missing token: non-zero", r.returncode != 0, True)
    check("missing token: one stderr line", len(r.stderr.strip().splitlines()), 1)
    check("missing token: never called curl", (tmp / "argv").exists(), False)

with tempfile.TemporaryDirectory() as d:
    tmp = Path(d)
    r = run(setup(tmp, curl_rc=22), ["updates", "x"])
    check("curl failure: non-zero", r.returncode != 0, True)
    check("curl failure: one stderr line", len(r.stderr.strip().splitlines()), 1)

with tempfile.TemporaryDirectory() as d:
    tmp = Path(d)
    env = setup(tmp)
    del env["NTFY_URL"]
    r = run(env, ["updates", "x"])
    check("no base url: non-zero", r.returncode != 0, True)
    (tmp / "server.yml").write_text('base-url: "http://cfg.invalid"\n')
    env["NTFY_CONFIG"] = str(tmp / "server.yml")
    run(env, ["updates", "x"])
    check("base url from config", "http://cfg.invalid/updates" in (tmp / "argv").read_text().splitlines(), True)
    r = run(env, ["updates", "--priority", "loud", "x"])
    check("bad priority: non-zero", r.returncode != 0, True)

print()
if failures:
    print(f"{len(failures)} failed: {failures}")
    sys.exit(1)
print("all passed")
