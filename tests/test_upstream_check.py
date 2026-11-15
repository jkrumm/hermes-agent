#!/usr/bin/env python3
"""scripts/upstream-check.sh: exit 0 current, 1 behind, 2 undecidable; only plain stable tags count.

Builds a throwaway upstream repo + clone and a fake `hermes` CLI, so it never touches the live checkout.
"""

import os
import subprocess
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCRIPT = os.path.join(ROOT, "scripts", "upstream-check.sh")
GIT_ENV = {
    **os.environ,
    "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@example.com",
    "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@example.com",
}


def git(cwd, *args):
    subprocess.run(["git", "-C", cwd, *args], check=True, capture_output=True, env=GIT_ENV)


def commit_tag(cwd, tag):
    git(cwd, "commit", "--allow-empty", "-m", tag)
    git(cwd, "tag", tag)


def run(src, version_out):
    fake = os.path.join(os.path.dirname(src), "hermes")
    with open(fake, "w") as f:
        f.write(f"#!/bin/sh\necho '{version_out}'\n")
    os.chmod(fake, 0o755)
    r = subprocess.run(
        [SCRIPT], capture_output=True, text=True,
        env={**os.environ, "HERMES_SRC": src, "HERMES_BIN": fake},
    )
    return r.returncode, r.stdout + r.stderr


failures = []


def expect(name, got, want, out=""):
    if got != want:
        failures.append(f"{name}: exit {got}, want {want}\n{out}")
    print(f"  {'✓' if got == want else '✗'} {name}")


with tempfile.TemporaryDirectory() as tmp:
    origin = os.path.join(tmp, "origin")
    src = os.path.join(tmp, "src", "hermes-agent")
    os.makedirs(origin)
    git(origin, "init", "-q", "-b", "main")
    commit_tag(origin, "v0.22.7")
    commit_tag(origin, "v0.23.1")
    subprocess.run(["git", "clone", "-q", origin, src], check=True, env=GIT_ENV)
    git(src, "checkout", "-q", "--detach", "v0.23.1")

    code, out = run(src, "Hermes Agent v0.23.1 (2026.9.24) · stable · local abc")
    expect("current -> 0", code, 0, out)

    # noise tags upstream publishes must not count as a newer release
    for noise in ("v0.23.2+canary.20261116T064406Z", "rc.1-v0.23.2", "abandoned-rc.1-v0.23.2", "v2026.12.1"):
        commit_tag(origin, noise)
    code, out = run(src, "Hermes Agent v0.23.1 (2026.9.24) · stable")
    expect("canary/rc/abandoned/date tags ignored -> 0", code, 0, out)

    commit_tag(origin, "v0.23.2")
    code, out = run(src, "Hermes Agent v0.23.1 (2026.9.24) · stable")
    expect("behind a new stable tag -> 1", code, 1, out)
    if "/hermes-update" not in out.splitlines()[-1]:
        failures.append(f"last line must name /hermes-update:\n{out}")

    code, out = run(src, "Hermes Agent v0.23.2 (2026.9.24) · stable")
    expect("installed == latest -> 0", code, 0, out)

    code, out = run(src, "no version here")
    expect("unreadable version -> 2", code, 2, out)

if failures:
    print("\n".join(failures))
    sys.exit(1)
