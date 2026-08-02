"""Regression suite for `scripts/hermes-cc.sh` — the sole path through which the
Hermes agent may hand a bounded Claude Code episode to one repo.

Covers the security properties that make it safe to hand an LLM a bounded verb
dispatcher instead of a raw `terminal` tool: the closed verb set (no fallthrough
to a shell), argument bounding against each slot's fixed/live list or shape,
repo resolution (repos are DISCOVERED under a policy root rather than
enumerated — a denied name refuses, a name the policy claims to have but
doesn't is its own distinct precondition failure, and a traversal/symlink
attempt is confined against the resolved real path), tier gating (a repo's
policy-resolved ceiling wins over the request and is never silently
downgraded), the write-tier gate
(`implement` demands --why, and without --confirm prints its plan and changes
nothing; it carries its own tighter daily ceiling), artifact plumbing (the
issue/PR URL reaches both the --json top level and its own column),
the brief-is-data rule (never taken from argv, always from stdin or
`--brief-file`, transmitted verbatim into the sideclaw job body — never
expanded, never re-parsed by a shell), the `--json` contract (exactly one
parseable object per invocation, success or failure alike), the audit log (one
line per call, `mode=` distinguishing refused/dry-run/opened, secrets
redacted), the daily dispatch budget (a structural ceiling on unattended Max
spend), the recursion guard (a dispatched episode may never dispatch), and the
dispatch record lifecycle (`reported_at` is the delivery debt — a `--wait` that
reaches a terminal status settles it, a bare `status` poll does not).

Every case here runs against a stubbed `curl` and `secrets-run` on PATH, an
isolated fake `$HOME`, a from-scratch `dispatch-repos.json` policy fixture, and a fresh
SQLite dispatch DB per case (unless a case deliberately shares one to exercise
continuity) — no real network call ever reaches sideclaw, no real 1Password
read, no real dispatches DB or audit log touched, ever. Safe to run repeatedly
on the live Mac mini.

Run:

    ~/.hermes/hermes-agent/venv/bin/python3 tests/test_hermes_cc.py

Exit status is 0 only when every case matches.
"""

import json
import re
import shutil
import sqlite3
import stat
import subprocess
import sys
import tempfile
import datetime as dt
from pathlib import Path

import os

REPO_ROOT = Path(__file__).resolve().parent.parent
CC_SCRIPT = REPO_ROOT / "scripts" / "hermes-cc.sh"

# --- stub programs -----------------------------------------------------------

# Logs {"argv": [...], "stdin": <body-or-null>} as one JSON object per line to
# $CC_TEST_CURL_LOG. `stdin` is only populated for calls that carry
# --data-binary (the POST submit) — that is how a test reads out the exact
# job body hermes-cc.sh assembled, to prove a brief was transmitted verbatim.
FAKE_CURL = """#!/usr/bin/env python3
import json, os, sys

argv = sys.argv[1:]
stdin_data = None
# The GitHub path sends the auth header as a curl config on stdin (-K -) and the
# request body as a file (--data-binary @path); the sideclaw path still sends its
# body on stdin (--data-binary @-). Drain stdin whenever -K is present so the
# caller's printf never takes a SIGPIPE, and resolve @path bodies from disk.
if "-K" in argv:
    sys.stdin.read()
if "--data-binary" in argv:
    ref = argv[argv.index("--data-binary") + 1]
    if ref == "@-":
        stdin_data = sys.stdin.read()
    elif ref.startswith("@"):
        with open(ref[1:]) as fh:
            stdin_data = fh.read()

method = argv[argv.index("-X") + 1] if "-X" in argv else "GET"

log = os.environ.get("CC_TEST_CURL_LOG")
if log:
    with open(log, "a") as f:
        f.write(json.dumps({"argv": argv, "stdin": stdin_data}) + "\\n")

exit_code = int(os.environ.get("CC_TEST_CURL_EXIT", "0"))
if exit_code != 0:
    sys.exit(exit_code)

status = os.environ.get("CC_TEST_CURL_STATUS", "200")
url = argv[-1] if argv else ""
job_id = "test-job-0001"

# --- fake GitHub -------------------------------------------------------------
# Only the `merge` verb talks to GitHub. Every response is driven by env so a
# case can pose exactly one bad condition (a fork head, a blocked state, a CI
# path) and prove the refusal is that one and not an accident of another field.
GH = os.environ.get("CC_TEST_GH_API", "")
if GH and url.startswith(GH):
    path = url[len(GH):]
    pr_defaults = {
        "state": "open", "merged": False, "draft": True,
        "node_id": "PR_kwstub", "title": "stub pr title",
        "base": {"ref": "master"},
        "head": {"ref": "dispatch/stub-branch", "sha": "deadbeef" * 5,
                 "repo": {"full_name": "jkrumm/gamma"}},
        "changed_files": 2, "additions": 4, "deletions": 4,
        "mergeable": True, "mergeable_state": "clean",
    }
    pr = json.loads(os.environ.get("CC_TEST_PR_JSON", "{}"))
    pr_defaults.update(pr)
    repo_obj = json.loads(os.environ.get("CC_TEST_REPO_JSON", "{}"))
    repo_defaults = {"default_branch": "master", "allow_squash_merge": True,
                     "allow_rebase_merge": True, "allow_merge_commit": True}
    repo_defaults.update(repo_obj)
    files = json.loads(os.environ.get("CC_TEST_PR_FILES", '[{"filename": "src/a.ts"}]'))

    if path == "/graphql":
        body, status = os.environ.get("CC_TEST_GRAPHQL", '{"data": {}}'), "200"
    elif path.endswith("/merge") and method == "PUT":
        status = os.environ.get("CC_TEST_MERGE_STATUS", "200")
        body = json.dumps({"sha": "mergedsha001", "merged": True})
    elif "/git/refs/heads/" in path:
        body, status = "", "204"
    elif "/files" in path:
        body = json.dumps(files)
    elif "/pulls/" in path:
        body = json.dumps(pr_defaults)
    else:
        body = json.dumps(repo_defaults)
    sys.stdout.write(body + "\\n" + status)
    sys.exit(0)

default_result = json.dumps({
    "verdict": "stub verdict text",
    "confidence": 0.9,
    "evidence": ["stub evidence line"],
    "recommendation": "stub recommendation",
    "nextAction": "none",
    "summary": "stub summary",
})

if url.rstrip("/").endswith("/api/jobs"):
    body = json.dumps({"ok": True, "job": {"id": job_id, "status": "running"}})
elif "/api/jobs/" in url:
    job_status = os.environ.get("CC_TEST_JOB_STATUS", "done")
    result_raw = os.environ.get("CC_TEST_JOB_RESULT", default_result)
    job_obj = {
        "id": url.rsplit("/", 1)[-1],
        "status": job_status,
        "elapsedMs": 1234,
        "result": json.loads(result_raw),
    }
    if job_status in ("failed", "interrupted"):
        job_obj["error"] = "stub job failure"
    body = json.dumps({"ok": True, "job": job_obj})
else:
    body = json.dumps({"ok": False, "error": "unrecognized url in stub: " + url})

sys.stdout.write(body + "\\n" + status)
sys.exit(0)
"""

# secrets-run is only checked for executability by require_backend() — no
# implemented verb actually invokes it today, so the stub needs no behavior.
# ...except for `merge`, which reads the GitHub credential through it. A token
# shaped like a real one, so the audit-log redactor is exercised on it too.
FAKE_SECRETS_RUN = """#!/usr/bin/env python3
import sys
if len(sys.argv) > 2 and sys.argv[1] == "read":
    print("github_pat_STUB0000000000000000000000000000")
sys.exit(0)
"""


def _write_exec(path: Path, content: str) -> None:
    path.write_text(content)
    mode = path.stat().st_mode
    path.chmod(mode | stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH)


class Harness:
    """One isolated stub PATH + fake $HOME + repo fixture, reused across the run."""

    def __init__(self) -> None:
        self.root = Path(tempfile.mkdtemp(prefix="hermes-cc-test-"))
        self.bin = self.root / "bin"
        self.bin.mkdir()
        _write_exec(self.bin / "curl", FAKE_CURL)

        self.home = self.root / "home"
        (self.home / ".local" / "bin").mkdir(parents=True)
        _write_exec(self.home / ".local" / "bin" / "secrets-run", FAKE_SECRETS_RUN)

        self.backend_file = self.root / "backend"
        self.backend_file.write_text("cache\n")

        # Dispatch POLICY fixture (not an inventory): repos are DISCOVERED under
        # `root`, and `deny`/`tiers` only ever narrow or redirect what discovery
        # finds — absence from either is neither permission nor denial. Fixture
        # repos exercise every resolution outcome:
        #   - alpha: a real checkout with no entry anywhere in the policy — proves
        #     plain discovery works and falls through to `defaultTier` (set to
        #     "author" here, matching production).
        #   - beta: a real checkout named in `tiers.investigate` — an explicit
        #     ceiling below the default.
        #   - gamma: a real checkout named in `tiers.implement` — the only
        #     fixture repo whose ceiling admits a write tier. Keeping it separate
        #     from beta is what lets a single test prove BOTH halves of a
        #     ceiling: gamma accepts `implement`, beta (capped at investigate)
        #     refuses the identical request.
        #   - denied: a real checkout that ALSO appears in `deny` — proves deny
        #     wins over having a perfectly good checkout on disk; discovery alone
        #     would have let it through.
        #   - ghost: named in `tiers` but never created on disk — the policy
        #     claims this machine has a checkout it does not, which is its own
        #     distinct precondition failure (exit 2), not a typo (exit 64).
        #   - any name never written here at all (e.g. "not-a-listed-repo")
        #     exercises the plain-typo path: no checkout AND no entry in `tiers`,
        #     so it is exit 64 with the dispatchable list, not exit 2.
        self.repos_root = self.root / "repos"
        self.repos_root.mkdir()
        self.alpha = self.repos_root / "alpha"
        self.beta = self.repos_root / "beta"
        self.gamma = self.repos_root / "gamma"
        self.denied = self.repos_root / "denied"
        for d in (self.alpha, self.beta, self.gamma, self.denied):
            (d / ".git").mkdir(parents=True)
        self.ghost = self.repos_root / "ghost"  # named in `tiers`, deliberately never created

        self.repos_json = self.root / "dispatch-repos.json"
        self.repos_json.write_text(json.dumps({
            "root": str(self.repos_root),
            "defaultTier": "author",
            "deny": ["denied"],
            "tiers": {
                "investigate": ["beta", "ghost"],
                "implement": ["gamma"],
            },
        }))

        # Merge eligibility is derived from this file, not from a list in the
        # dispatch policy. The fixture names a repo that is NOT one of ours, so
        # the default path is "allowed"; the case that proves the refusal points
        # HERMES_CC_PR_REQUIRED_JSON at its own file naming `gamma`.
        self.pr_required_json = self.root / "pr-required-repos.json"
        self.pr_required_json.write_text(json.dumps(
            {"repos": ["some-other-repo"], "directToMain": []}))
        self.pr_required_gamma = self.root / "pr-required-gamma.json"
        self.pr_required_gamma.write_text(json.dumps({"repos": ["gamma"]}))

        self.log_dir = self.root / "logs"
        self.log_dir.mkdir()
        self.db_dir = self.root / "dbs"
        self.db_dir.mkdir()
        self._counter = 0

    def cleanup(self) -> None:
        shutil.rmtree(self.root, ignore_errors=True)

    def new_log(self, prefix: str) -> Path:
        self._counter += 1
        return self.log_dir / f"{prefix}-{self._counter}.log"

    def new_db(self) -> Path:
        self._counter += 1
        return self.db_dir / f"db-{self._counter}.sqlite"

    def run(self, args, *, env_extra=None, audit_log=None, timeout=20, stdin=None):
        env = dict(os.environ)
        env["PATH"] = f"{self.bin}:{env.get('PATH', '')}"
        env["HOME"] = str(self.home)
        env["SECRETS_BACKEND_FILE"] = str(self.backend_file)
        env["HERMES_CC_SIDECLAW_BASE"] = "http://127.0.0.1:1"
        env["HERMES_CC_REPOS_JSON"] = str(self.repos_json)
        env["HERMES_CC_DB"] = str(self.new_db())
        env["HERMES_CC_LOG"] = str(audit_log or self.new_log("audit"))
        env["HERMES_CC_GH_API"] = "http://gh.invalid"
        env["CC_TEST_GH_API"] = "http://gh.invalid"
        env["HERMES_CC_PR_REQUIRED_JSON"] = str(self.pr_required_json)
        env.pop("OP_SERVICE_ACCOUNT_TOKEN", None)
        # The suite itself runs inside a Claude Code session; every case must
        # start clean of the recursion-guard markers, or every dispatch would
        # refuse with exit 4 regardless of what the test is trying to check.
        for marker in ("CLAUDECODE", "CLAUDE_CODE_SESSION", "CLAUDE_SESSION_ID",
                       "CLAUDE_ENTRYPOINT"):
            env.pop(marker, None)
        if env_extra:
            env.update(env_extra)
        try:
            return subprocess.run(
                ["bash", str(CC_SCRIPT), *args],
                env=env,
                capture_output=True,
                text=True,
                input=stdin if stdin is not None else "",
                timeout=timeout,
            )
        except subprocess.TimeoutExpired:
            return subprocess.CompletedProcess(
                args, returncode=-1, stdout="", stderr="<subprocess timed out>"
            )


def _log_text(path: Path) -> str:
    return path.read_text() if path.exists() else ""


def _curl_lines(path: Path):
    if not path.exists():
        return []
    return [json.loads(ln) for ln in path.read_text().splitlines() if ln.strip()]


VALID_BRIEF = "Investigate the failing check job."


# =============================================================================
# 1. Closed verb set — no fallthrough to a shell, ever.
# =============================================================================

def test_closed_verb_set(h: Harness):
    failures = []
    total = passed = 0

    for verb in ["totally-bogus-verb", "; rm -rf /tmp/x", "$(whoami)"]:
        total += 1
        curl_log = h.new_log("curl")
        proc = h.run([verb], env_extra={"CC_TEST_CURL_LOG": str(curl_log)})
        ok = (proc.returncode == 64
              and "unknown verb" in (proc.stdout + proc.stderr)
              and not _curl_lines(curl_log))
        if ok:
            passed += 1
        else:
            failures.append(f"verb={verb!r}: expected a clean usage error, got "
                             f"rc={proc.returncode} stdout={proc.stdout[:200]!r} "
                             f"stderr={proc.stderr[:200]!r}")

    total += 1
    proc = h.run(["help"])
    ok = proc.returncode == 0 and "VERBS" in proc.stdout
    if ok:
        passed += 1
    else:
        failures.append(f"help: expected exit 0 with usage text, got "
                         f"rc={proc.returncode} stdout={proc.stdout[:200]!r}")

    total += 1
    proc = h.run([])
    ok = proc.returncode == 0 and "VERBS" in proc.stdout
    if ok:
        passed += 1
    else:
        failures.append(f"bare invocation: expected exit 0 with usage text, got "
                         f"rc={proc.returncode} stdout={proc.stdout[:200]!r}")

    return total, passed, failures


# =============================================================================
# 2. Argument bounding — every slot rejects a shell-meta/newline/leading-dash/
#    empty payload at exit 64, before ever reaching curl.
#
#    Two deliberate, verified exceptions to the blanket "reject 'unknown'"
#    expectation, both because the script performs no live-list cross-check at
#    that point:
#      - status:job-id — valid_job_id() checks charset only; a shape-valid but
#        nonexistent job id is not rejected, it reaches sideclaw (the stub
#        answers 200 unconditionally, same as the real server would for any
#        id it has never heard of — existence is sideclaw's problem, not this
#        script's).
#      - list:scope / dispatch:tier / dispatch:origin-{channel,thread,event} —
#        all read as `${VAR:-default}` in bash, which substitutes the default
#        for an EXPLICIT empty string exactly as it would for an unset
#        variable. Passing e.g. `--tier ''` therefore silently becomes
#        `--tier investigate`, not a usage error. This is intentional bash
#        semantics, not a gap in the allowlist: nothing unsanitized reaches
#        curl or the repo path either way.
# =============================================================================

ARG_SLOTS = [
    dict(name="dispatch:repo", build=lambda p: ["dispatch", p],
         unknown="not-a-real-repo-xyz", shell_meta="alpha;whoami",
         newline="alpha\nwhoami", empty_ok=False),
    dict(name="status:job-id", build=lambda p: ["status", p],
         unknown="not-a-real-job-id-000", shell_meta="job;whoami",
         newline="job\nwhoami", empty_ok=False, unknown_passthrough=True),
    dict(name="list:scope", build=lambda p: ["list", p],
         unknown="not-a-real-scope", shell_meta="today;whoami",
         newline="today\nwhoami", empty_ok=True),
    dict(name="dispatch:tier", build=lambda p: ["dispatch", "alpha", "--tier", p],
         unknown="not-a-real-tier", shell_meta="investigate;whoami",
         newline="investigate\nwhoami", empty_ok=True),
    dict(name="dispatch:origin-channel",
         build=lambda p: ["dispatch", "alpha", "--origin-channel", p],
         unknown="not-a-real-channel", shell_meta="C123;whoami",
         newline="C123\nwhoami", empty_ok=True),
    dict(name="dispatch:origin-thread",
         build=lambda p: ["dispatch", "alpha", "--origin-channel", "C0123456789",
                           "--origin-thread", p],
         unknown="not.a.real.thread", shell_meta="1234;whoami",
         newline="1234\nwhoami", empty_ok=True),
    dict(name="dispatch:origin-event",
         build=lambda p: ["dispatch", "alpha", "--origin-event", p],
         unknown="not-a-real-event", shell_meta="42;whoami",
         newline="42\nwhoami", empty_ok=True),
]


def test_argument_bounding(h: Harness):
    failures = []
    total = passed = 0

    for slot in ARG_SLOTS:
        cases = {
            "unknown": slot["unknown"],
            "shell_meta": slot["shell_meta"],
            "newline": slot["newline"],
            "leading_dash": "-rf",
            "empty": "",
        }
        for case_name, payload in cases.items():
            label = f"{slot['name']}/{case_name}"
            args = slot["build"](payload)
            total += 1
            curl_log = h.new_log("curl")

            if case_name == "unknown" and slot.get("unknown_passthrough"):
                proc = h.run(args, env_extra={"CC_TEST_CURL_LOG": str(curl_log)})
                if proc.returncode == 0 and _curl_lines(curl_log):
                    passed += 1
                else:
                    failures.append(
                        f"{label}: expected the opaque-but-shape-valid job id to "
                        f"pass validation and reach curl (sideclaw is the sole "
                        f"arbiter of job existence), got rc={proc.returncode} "
                        f"curl={_curl_lines(curl_log)!r}")
                continue

            if case_name == "empty" and slot.get("empty_ok"):
                dr_args = list(args)
                if "dispatch" in dr_args:
                    dr_args = dr_args + ["--dry-run"]
                proc = h.run(dr_args, env_extra={"CC_TEST_CURL_LOG": str(curl_log)},
                             stdin=VALID_BRIEF)
                ok = proc.returncode == 0 and not _curl_lines(curl_log)
                if ok:
                    passed += 1
                else:
                    failures.append(
                        f"{label}: expected the empty value to silently fall "
                        f"back to its default (bash's ${{VAR:-default}} treats "
                        f"an explicit empty string the same as unset), got "
                        f"rc={proc.returncode} stdout={proc.stdout[:200]!r}")
                continue

            proc = h.run(args, env_extra={"CC_TEST_CURL_LOG": str(curl_log)})
            if proc.returncode != 64:
                failures.append(
                    f"{label}: expected exit 64, got {proc.returncode} "
                    f"(stdout={proc.stdout[:200]!r} stderr={proc.stderr[:200]!r})")
                continue
            if _curl_lines(curl_log):
                failures.append(f"{label}: rejected value still reached curl: "
                                 f"{_curl_lines(curl_log)!r}")
                continue
            passed += 1

    return total, passed, failures


# =============================================================================
# 3. Repo resolution — repos are DISCOVERED under the policy root rather than
#    enumerated; a denied name refuses, an absent name refuses with the
#    dispatchable list, and a name the policy claims but has no checkout for
#    is its own distinct precondition failure.
# =============================================================================

def test_repo_resolution(h: Harness):
    failures = []
    total = passed = 0

    total += 1
    proc = h.run(["dispatch", "alpha", "--dry-run", "--json"], stdin=VALID_BRIEF)
    ok = False
    try:
        data = json.loads(proc.stdout.strip())
        ok = (proc.returncode == 0 and data.get("ok") is True
              and data.get("repo") == "alpha")
    except json.JSONDecodeError:
        pass
    if ok:
        passed += 1
    else:
        failures.append(f"a plainly discovered repo did not resolve: "
                         f"rc={proc.returncode} stdout={proc.stdout[:300]!r}")

    total += 1
    curl_log = h.new_log("curl")
    proc = h.run(["dispatch", "denied"],
                  env_extra={"CC_TEST_CURL_LOG": str(curl_log)})
    text = proc.stdout + proc.stderr
    ok = (proc.returncode == 64 and "not dispatchable" in text
          and not _curl_lines(curl_log))
    if ok:
        passed += 1
    else:
        failures.append(f"a real checkout that is also in `deny` did not "
                         f"refuse cleanly (deny must win over having a "
                         f"perfectly good checkout on disk): rc={proc.returncode} "
                         f"stdout={proc.stdout[:300]!r} stderr={proc.stderr[:300]!r}")

    total += 1
    curl_log = h.new_log("curl")
    proc = h.run(["dispatch", "not-a-listed-repo"],
                  env_extra={"CC_TEST_CURL_LOG": str(curl_log)})
    text = proc.stdout + proc.stderr
    ok = (proc.returncode == 64 and "dispatchable:" in text
          and "alpha" in text and not _curl_lines(curl_log))
    if ok:
        passed += 1
    else:
        failures.append(f"a name absent from the policy entirely did not "
                         f"refuse cleanly with the dispatchable list: "
                         f"rc={proc.returncode} stdout={proc.stdout[:300]!r} "
                         f"stderr={proc.stderr[:300]!r}")

    total += 1
    proc = h.run(["dispatch", "ghost"])
    ok = (proc.returncode == 2
          and "policy names a repo this machine does not have" in
          (proc.stdout + proc.stderr))
    if ok:
        passed += 1
    else:
        failures.append(f"repo named in `tiers` but with no checkout on disk "
                         f"did not exit 2 (this is a machine that lacks what "
                         f"the policy claims, not a typo): rc={proc.returncode} "
                         f"stdout={proc.stdout[:300]!r} stderr={proc.stderr[:300]!r}")

    return total, passed, failures


# =============================================================================
# 3b. Repo name confinement — traversal-shaped names are rejected by shape
#     before ever touching the filesystem, and a symlink planted INSIDE the
#     policy root that points OUTSIDE it is caught by the realpath-parent
#     check, not the character class (a symlink's own name is a perfectly
#     ordinary single segment and can still escape).
# =============================================================================

def test_repo_name_confinement(h: Harness):
    failures = []
    total = passed = 0

    for name in (".", "..", ".git", "../etc", "foo/bar"):
        total += 1
        curl_log = h.new_log("curl")
        proc = h.run(["dispatch", name],
                      env_extra={"CC_TEST_CURL_LOG": str(curl_log)})
        text = proc.stdout + proc.stderr
        ok = (proc.returncode == 64 and "not a repo name" in text
              and not _curl_lines(curl_log))
        if ok:
            passed += 1
        else:
            failures.append(f"repo name {name!r}: expected exit 64 'not a repo "
                             f"name' with nothing submitted, got "
                             f"rc={proc.returncode} stdout={proc.stdout[:300]!r} "
                             f"stderr={proc.stderr[:300]!r}")

    # A checkout that lives entirely outside the dispatch root, reached only
    # via a symlink planted inside it, must still refuse. The character-class
    # check can't catch this — the symlink's own name ("escape") passes it
    # cleanly. Confinement has to be enforced against the REAL, resolved path,
    # which is what `resolve_repo`'s dirname-must-equal-root check does; without
    # it this is a live escape hatch out of the dispatch root.
    total += 1
    outside = h.root / "outside-checkout"
    (outside / ".git").mkdir(parents=True)
    escape_link = h.repos_root / "escape"
    escape_link.symlink_to(outside)
    curl_log = h.new_log("curl")
    proc = h.run(["dispatch", "escape"],
                  env_extra={"CC_TEST_CURL_LOG": str(curl_log)})
    text = proc.stdout + proc.stderr
    ok = (proc.returncode == 64 and "not dispatchable" in text
          and not _curl_lines(curl_log))
    if ok:
        passed += 1
    else:
        failures.append(f"a symlink inside the root pointing outside it: "
                         f"expected exit 64 'not dispatchable' with nothing "
                         f"submitted, got rc={proc.returncode} "
                         f"stdout={proc.stdout[:300]!r} "
                         f"stderr={proc.stderr[:300]!r}")

    return total, passed, failures


# =============================================================================
# 4. Tier gating — the per-repo ceiling resolved from the dispatch policy
#    (either an explicit `tiers` override or the fallback `defaultTier`) wins
#    over the request, and an invalid tier name is a usage error.
#
#    Now that all three tiers are built, the ceiling is the live gate rather
#    than the documented no-op it was while author/implement were unbuilt: a
#    repo capped at investigate must refuse an author/implement request at exit
#    4 WITHOUT submitting anything, and a repo capped at implement must accept
#    the identical request. Both directions are checked, because a ceiling that
#    only ever says no is indistinguishable from a broken tier.
# =============================================================================

def test_tier_gating(h: Harness):
    failures = []
    total = passed = 0

    # beta carries an explicit `tiers.investigate` override — the request is
    # well-formed and the tier is built; only the ceiling stops it.
    for tier in ("author", "implement"):
        total += 1
        curl_log = h.new_log("curl")
        args = ["dispatch", "beta", "--tier", tier]
        if tier == "implement":
            args += ["--why", "checking the ceiling", "--confirm"]
        proc = h.run(args, env_extra={"CC_TEST_CURL_LOG": str(curl_log)},
                      stdin=VALID_BRIEF)
        text = proc.stdout + proc.stderr
        ok = (proc.returncode == 4 and "capped at tier" in text
              and not _curl_lines(curl_log))
        if ok:
            passed += 1
        else:
            failures.append(f"--tier {tier} into a repo capped at investigate: "
                             f"expected a clean ceiling refusal (4) with nothing "
                             f"submitted, got rc={proc.returncode} "
                             f"stdout={proc.stdout[:300]!r} "
                             f"curl={_curl_lines(curl_log)!r}")

    # gamma's ceiling is implement, so author must pass through and reach curl
    # carrying the tier it was asked for — never a silently downgraded one.
    total += 1
    curl_log = h.new_log("curl")
    proc = h.run(["dispatch", "gamma", "--tier", "author", "--json"],
                  env_extra={"CC_TEST_CURL_LOG": str(curl_log)}, stdin=VALID_BRIEF)
    submits = [c for c in _curl_lines(curl_log) if c.get("stdin")]
    ok = False
    if proc.returncode == 0 and len(submits) == 1:
        body = json.loads(submits[0]["stdin"])
        ok = body["params"]["tier"] == "author"
    if ok:
        passed += 1
    else:
        failures.append(f"--tier author into a repo capped at implement: expected "
                         f"a submit carrying tier=author, got rc={proc.returncode} "
                         f"curl={submits!r}")

    total += 1
    proc = h.run(["dispatch", "alpha", "--tier", "godmode"])
    ok = proc.returncode == 64 and "unknown tier" in (proc.stdout + proc.stderr)
    if ok:
        passed += 1
    else:
        failures.append(f"--tier godmode: expected exit 64 'unknown tier', got "
                         f"rc={proc.returncode} stdout={proc.stdout[:300]!r}")

    # No --tier flag hardcodes the REQUESTED tier to "investigate" regardless
    # of the repo's resolved ceiling — that default lives in cmd_dispatch, not
    # in the policy, and stays the safe read-only floor even for alpha, whose
    # ceiling (`repoMaxTier`, resolved from `defaultTier`) is "author".
    total += 1
    proc = h.run(["dispatch", "alpha", "--dry-run", "--json"], stdin=VALID_BRIEF)
    try:
        data = json.loads(proc.stdout.strip())
        ok = (proc.returncode == 0 and data.get("tier") == "investigate"
              and data.get("repoMaxTier") == "author")
    except json.JSONDecodeError:
        ok = False
    if ok:
        passed += 1
    else:
        failures.append(f"default requested tier: expected 'investigate' with "
                         f"repoMaxTier 'author' and no --tier flag on a "
                         f"plainly discovered repo, got rc={proc.returncode} "
                         f"stdout={proc.stdout[:300]!r}")

    total += 1
    proc = h.run(["dispatch", "beta", "--tier", "investigate", "--dry-run", "--json"],
                  stdin=VALID_BRIEF)
    try:
        data = json.loads(proc.stdout.strip())
        ok = proc.returncode == 0 and data.get("ok") is True
    except json.JSONDecodeError:
        ok = False
    if ok:
        passed += 1
    else:
        failures.append(f"repo capped at its own tier ceiling: expected a "
                         f"request at exactly that ceiling to succeed, got "
                         f"rc={proc.returncode} stdout={proc.stdout[:300]!r}")

    return total, passed, failures


# =============================================================================
# 5. The brief is data, never argv — --brief is refused by name, oversized/
#    empty briefs are refused, --brief-file and stdin both work, and a brief
#    containing shell metacharacters reaches the job body byte-for-byte.
# =============================================================================

def test_brief_is_data(h: Harness):
    failures = []
    total = passed = 0

    for label, args in [
        ("--brief flag", ["dispatch", "alpha", "--brief", "x"]),
        ("--brief= flag", ["dispatch", "alpha", "--brief=x"]),
    ]:
        total += 1
        proc = h.run(args)
        text = proc.stdout + proc.stderr
        ok = proc.returncode == 64 and "brief-file" in text
        if ok:
            passed += 1
        else:
            failures.append(f"{label}: expected exit 64 naming --brief-file/stdin, "
                             f"got rc={proc.returncode} stdout={proc.stdout[:300]!r} "
                             f"stderr={proc.stderr[:300]!r}")

    total += 1
    proc = h.run(["dispatch", "alpha"], stdin="x" * 8001)
    ok = proc.returncode == 64 and "limit" in (proc.stdout + proc.stderr)
    if ok:
        passed += 1
    else:
        failures.append(f"oversized brief: expected exit 64 'limit', got "
                         f"rc={proc.returncode} stdout={proc.stdout[:200]!r}")

    total += 1
    proc = h.run(["dispatch", "alpha"], stdin="   \n\t  ")
    ok = proc.returncode == 64 and "brief is empty" in (proc.stdout + proc.stderr)
    if ok:
        passed += 1
    else:
        failures.append(f"whitespace-only brief: expected exit 64 'brief is "
                         f"empty', got rc={proc.returncode} "
                         f"stdout={proc.stdout[:200]!r}")

    total += 1
    proc = h.run(["dispatch", "alpha", "--brief-file", "/no/such/path/brief.txt"])
    ok = proc.returncode == 64 and "--brief-file not found" in (proc.stdout + proc.stderr)
    if ok:
        passed += 1
    else:
        failures.append(f"missing --brief-file: expected exit 64, got "
                         f"rc={proc.returncode} stdout={proc.stdout[:200]!r}")

    total += 1
    brief_path = h.root / "valid-brief.txt"
    brief_path.write_text("Investigate the recurring check failure.")
    proc = h.run(["dispatch", "alpha", "--brief-file", str(brief_path),
                  "--dry-run", "--json"])
    try:
        data = json.loads(proc.stdout.strip())
        ok = proc.returncode == 0 and data.get("ok") is True
    except json.JSONDecodeError:
        ok = False
    if ok:
        passed += 1
    else:
        failures.append(f"valid --brief-file: expected a clean dry run, got "
                         f"rc={proc.returncode} stdout={proc.stdout[:300]!r}")

    total += 1
    proc = h.run(["dispatch", "alpha", "--dry-run", "--json"], stdin=VALID_BRIEF)
    try:
        data = json.loads(proc.stdout.strip())
        ok = proc.returncode == 0 and data.get("ok") is True
    except json.JSONDecodeError:
        ok = False
    if ok:
        passed += 1
    else:
        failures.append(f"valid stdin brief: expected a clean dry run, got "
                         f"rc={proc.returncode} stdout={proc.stdout[:300]!r}")

    total += 1
    injection_brief = "check `whoami` results and $(id) before replying"
    curl_log = h.new_log("curl")
    proc = h.run(["dispatch", "alpha", "--json"],
                  env_extra={"CC_TEST_CURL_LOG": str(curl_log)}, stdin=injection_brief)
    entries = _curl_lines(curl_log)
    posts = [e for e in entries if e.get("stdin")]
    ok = proc.returncode == 0 and len(posts) == 1
    if ok:
        body = json.loads(posts[0]["stdin"])
        ok = body.get("params", {}).get("brief") == injection_brief
    if ok:
        passed += 1
    else:
        failures.append(f"brief with $(...)/backticks was not transmitted "
                         f"verbatim: entries={entries!r} "
                         f"stdout={proc.stdout[:300]!r}")

    return total, passed, failures


# =============================================================================
# 6. --json contract — exactly one parseable object per invocation, success
#    and failure paths alike, exit code preserved.
# =============================================================================

def test_json_contract(h: Harness):
    failures = []
    total = passed = 0

    cases = [
        ("clean dry-run", ["dispatch", "alpha", "--dry-run", "--json"],
         VALID_BRIEF, {}, 0, True),
        ("unknown repo", ["dispatch", "not-a-listed-repo", "--json"],
         None, {}, 64, False),
        ("unknown verb", ["totally-bogus-verb", "--json"], None, {}, 64, False),
        ("tier refusal", ["dispatch", "beta", "--tier", "author", "--json"],
         None, {}, 4, False),
        ("http 500", ["dispatch", "alpha", "--json"],
         VALID_BRIEF, {"CC_TEST_CURL_STATUS": "500"}, 3, False),
        ("network failure", ["dispatch", "alpha", "--json"],
         VALID_BRIEF, {"CC_TEST_CURL_EXIT": "7"}, 3, False),
    ]
    for label, args, stdin, env_extra, expect_rc, expect_ok in cases:
        total += 1
        proc = h.run(args, stdin=stdin, env_extra=env_extra)
        try:
            data = json.loads(proc.stdout.strip())
        except json.JSONDecodeError as exc:
            failures.append(f"{label}: stdout is not exactly one JSON object: "
                             f"{exc} (stdout={proc.stdout!r})")
            continue
        ok = isinstance(data, dict) and proc.returncode == expect_rc
        if "exitCode" in data and data["exitCode"] != proc.returncode:
            ok = False
        if data.get("ok") is not expect_ok:
            ok = False
        if ok:
            passed += 1
        else:
            failures.append(f"{label}: rc={proc.returncode} (want {expect_rc}), "
                             f"ok={data.get('ok')!r} (want {expect_ok}), "
                             f"data={data!r}")
    return total, passed, failures


# =============================================================================
# 7. Audit log — one line per invocation, expected fields, mode reflects what
#    actually happened (refused/dry-run/opened), --why redacted when token-
#    shaped.
# =============================================================================

def test_audit_log(h: Harness):
    failures = []
    total = passed = 0
    fields = ["verb=", "mode=", "tier=", "args=", "target=", "rc=", "dur=", "why="]

    total += 1
    audit_log = h.new_log("audit-refused")
    proc = h.run(["dispatch", "beta", "--tier", "author"], audit_log=audit_log)
    lines = _log_text(audit_log).splitlines()
    ok = len(lines) == 1 and all(f in lines[0] for f in fields) and "mode=refused" in lines[0]
    if ok:
        passed += 1
    else:
        failures.append(f"refusal: expected exactly 1 audit line with all "
                         f"fields and mode=refused, got {lines!r} "
                         f"(rc={proc.returncode})")

    total += 1
    audit_log = h.new_log("audit-dryrun")
    proc = h.run(["dispatch", "alpha", "--dry-run"], audit_log=audit_log,
                  stdin=VALID_BRIEF)
    lines = _log_text(audit_log).splitlines()
    ok = len(lines) == 1 and "mode=dry-run" in lines[0]
    if ok:
        passed += 1
    else:
        failures.append(f"dry-run: expected 1 audit line with mode=dry-run, "
                         f"got {lines!r} (rc={proc.returncode})")

    total += 1
    audit_log = h.new_log("audit-opened")
    proc = h.run(["dispatch", "alpha", "--json"], audit_log=audit_log,
                  stdin=VALID_BRIEF)
    lines = _log_text(audit_log).splitlines()
    ok = proc.returncode == 0 and len(lines) == 1 and "mode=opened" in lines[0]
    if ok:
        passed += 1
    else:
        failures.append(f"successful dispatch: expected 1 audit line with "
                         f"mode=opened, got {lines!r} (rc={proc.returncode})")

    total += 1
    secret_like = "XyZ9aB8cD7eF6gH5iJ4kL3mN2"  # shape of a token, not a real one
    audit_log = h.new_log("audit-redact")
    h.run(["cancel", "test-job-0001", "--why", secret_like], audit_log=audit_log)
    text = _log_text(audit_log)
    ok = secret_like not in text and "<redacted>" in text
    if ok:
        passed += 1
    else:
        failures.append(f"a token-shaped --why value was not redacted in the "
                         f"audit log: {text!r}")

    return total, passed, failures


# =============================================================================
# 8. Daily budget — a structural ceiling on unattended Max spend. Exhausted
#    budget refuses at exit 4 before ever reaching curl, and still audits.
#
#    The rest of this section is about the ceiling being LEGIBLE, which is a
#    separate property from it being correct. A bound that is invisible until it
#    refuses reads as an arbitrary breakage: the caller cannot see one coming,
#    and the refusal is the first and only signal. So every reporting path
#    carries the standing counts of BOTH ceilings, a near-ceiling adds a warning,
#    and both the warning and the refusal name the env var that raises them —
#    an escape hatch only discoverable by reading the script is not one.
# =============================================================================

def _preseed(h: Harness, db_path, n: int, tier: str = "investigate") -> None:
    """Insert n dispatch rows dated today, so a budget count sees them."""
    # Let the script create the schema idempotently before inserting directly.
    h.run(["list"], env_extra={"HERMES_CC_DB": str(db_path)})
    now = dt.datetime.now(dt.timezone.utc).isoformat()
    conn = sqlite3.connect(db_path)
    for i in range(n):
        conn.execute(
            "INSERT INTO dispatches(job_id,tier,repo,brief,status,created_at) "
            "VALUES(?,?,?,?,?,?)",
            (f"preseeded-{tier}-{i}", tier, "alpha", "preseeded", "done", now),
        )
    conn.commit()
    conn.close()


def test_daily_budget(h: Harness):
    failures = []
    total = passed = 0

    db_path = h.new_db()
    _preseed(h, db_path, 2)

    total += 1
    curl_log = h.new_log("curl")
    audit_log = h.new_log("audit-budget")
    proc = h.run(["dispatch", "alpha", "--json"],
                  env_extra={"HERMES_CC_DB": str(db_path),
                             "HERMES_CC_DAILY_BUDGET": "2",
                             "CC_TEST_CURL_LOG": str(curl_log)},
                  audit_log=audit_log, stdin=VALID_BRIEF)
    ok = proc.returncode == 4 and "budget" in (proc.stdout + proc.stderr)
    if ok and _curl_lines(curl_log):
        ok = False
    if ok:
        passed += 1
    else:
        failures.append(f"over-budget dispatch: expected exit 4 'budget' with "
                         f"no job submitted, got rc={proc.returncode} "
                         f"stdout={proc.stdout[:300]!r} "
                         f"curl={_curl_lines(curl_log)!r}")

    total += 1
    lines = _log_text(audit_log).splitlines()
    ok = len(lines) == 1 and "mode=refused" in lines[0] and "rc=4" in lines[0]
    if ok:
        passed += 1
    else:
        failures.append(f"over-budget dispatch did not write a clean audit "
                         f"line: {lines!r}")

    # The refusal has to say how to proceed. Naming the ceiling without naming
    # the way past it is what makes a budget feel like a bug.
    total += 1
    text = proc.stdout + proc.stderr
    ok = "HERMES_CC_DAILY_BUDGET" in text and "2/2" in text
    if ok:
        passed += 1
    else:
        failures.append(f"budget refusal named neither the count nor the env "
                         f"var that raises it: {text[:400]!r}")

    # (a) an ordinary dispatch reports both ceilings, counting itself. A count
    # that excluded the dispatch just made would always be one behind the one
    # the next refusal uses.
    total += 1
    db_a = h.new_db()
    proc = h.run(["dispatch", "alpha", "--json"],
                  env_extra={"HERMES_CC_DB": str(db_a)}, stdin=VALID_BRIEF)
    try:
        budget = json.loads(proc.stdout.strip()).get("budget")
    except json.JSONDecodeError:
        budget = None
    ok = budget == {"usedToday": 1, "max": 20, "remaining": 19,
                    "implementToday": 0, "implementMax": 5,
                    "implementRemaining": 5}
    if ok:
        passed += 1
    else:
        failures.append(f"dispatch did not report both ceilings counting "
                         f"itself: {budget!r}")

    # (b) the rehearsal reports the standing counts and consumes nothing. The
    # plan is where the decision to spend a slot is actually made, so it is the
    # one place the remaining slots most need to be legible.
    total += 1
    db_b = h.new_db()
    _preseed(h, db_b, 3)
    proc = h.run(["dispatch", "alpha", "--dry-run", "--json"],
                  env_extra={"HERMES_CC_DB": str(db_b)}, stdin=VALID_BRIEF)
    try:
        data = json.loads(proc.stdout.strip())
    except json.JSONDecodeError:
        data = {}
    after = h.run(["list", "today", "--json"], env_extra={"HERMES_CC_DB": str(db_b)})
    try:
        listed = json.loads(after.stdout.strip())
    except json.JSONDecodeError:
        listed = {}
    ok = (data.get("budget", {}).get("usedToday") == 3
          and data.get("dryRun") is True
          and listed.get("count") == 3
          and listed.get("budget", {}).get("usedToday") == 3)
    if ok:
        passed += 1
    else:
        failures.append(f"dry-run budget: expected usedToday=3 reported and "
                         f"nothing consumed, got plan={data.get('budget')!r} "
                         f"list={listed.get('count')!r}/{listed.get('budget')!r}")

    # (c) approaching the shared ceiling warns at exit 0 rather than only
    # refusing at exit 4 one dispatch later.
    total += 1
    db_c = h.new_db()
    _preseed(h, db_c, 2)
    proc = h.run(["dispatch", "alpha", "--json"],
                  env_extra={"HERMES_CC_DB": str(db_c),
                             "HERMES_CC_DAILY_BUDGET": "4"}, stdin=VALID_BRIEF)
    try:
        budget = json.loads(proc.stdout.strip()).get("budget", {})
    except json.JSONDecodeError:
        budget = {}
    ok = (proc.returncode == 0 and budget.get("remaining") == 1
          and "HERMES_CC_DAILY_BUDGET" in budget.get("warning", ""))
    if ok:
        passed += 1
    else:
        failures.append(f"near the shared ceiling: expected a warning naming "
                         f"HERMES_CC_DAILY_BUDGET at rc=0, got "
                         f"rc={proc.returncode} budget={budget!r}")

    # (d) the implement ceiling warns on its own terms, and is counted even
    # from a read-only episode — a caller planning a write needs to see the
    # write allowance before it asks for one.
    total += 1
    db_d = h.new_db()
    _preseed(h, db_d, 4, tier="implement")
    proc = h.run(["dispatch", "alpha", "--json"],
                  env_extra={"HERMES_CC_DB": str(db_d)}, stdin=VALID_BRIEF)
    try:
        budget = json.loads(proc.stdout.strip()).get("budget", {})
    except json.JSONDecodeError:
        budget = {}
    ok = (proc.returncode == 0 and budget.get("implementToday") == 4
          and budget.get("implementRemaining") == 1
          and "HERMES_CC_IMPLEMENT_BUDGET" in budget.get("warning", "")
          and "HERMES_CC_DAILY_BUDGET" not in budget.get("warning", ""))
    if ok:
        passed += 1
    else:
        failures.append(f"near the implement ceiling from a read-only "
                         f"episode: expected an implement-only warning, got "
                         f"rc={proc.returncode} budget={budget!r}")

    return total, passed, failures


# =============================================================================
# 9. Recursion guard — a dispatched episode may never dispatch, whichever
#    marker Claude Code (or an injected brief) sets.
# =============================================================================

def test_recursion_guard(h: Harness):
    failures = []
    total = passed = 0
    markers = [
        {"CLAUDECODE": "1"},
        {"CLAUDE_CODE_SESSION": "x"},
        {"CLAUDE_SESSION_ID": "x"},
        {"CLAUDE_ENTRYPOINT": "worker"},
    ]
    for marker in markers:
        total += 1
        curl_log = h.new_log("curl")
        env_extra = dict(marker)
        env_extra["CC_TEST_CURL_LOG"] = str(curl_log)
        proc = h.run(["dispatch", "alpha"], env_extra=env_extra, stdin=VALID_BRIEF)
        text = (proc.stdout + proc.stderr).lower()
        ok = proc.returncode == 4 and "dispatch" in text and not _curl_lines(curl_log)
        if ok:
            passed += 1
        else:
            failures.append(f"{marker}: expected exit 4 refusing to run inside "
                             f"a session, got rc={proc.returncode} "
                             f"stdout={proc.stdout[:300]!r} "
                             f"stderr={proc.stderr[:300]!r}")
    return total, passed, failures


# =============================================================================
# 10. Dispatch record — one row per successful dispatch with the right
#     fields; reported_at is the delivery debt, settled only by --wait
#     reaching a terminal status, never by a bare `status` poll.
# =============================================================================

def _fetch_row(db_path, job_id):
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    row = conn.execute("SELECT * FROM dispatches WHERE job_id=?", (job_id,)).fetchone()
    conn.close()
    return dict(row) if row else None


def test_dispatch_record(h: Harness):
    failures = []
    total = passed = 0

    # (a) a successful, non-waiting dispatch inserts exactly one correct row
    # and leaves reported_at NULL — the sweeper still owes that delivery.
    total += 1
    db_path = h.new_db()
    proc = h.run(["dispatch", "alpha", "--origin-channel", "C0123456789",
                  "--origin-thread", "1234567890.123456", "--origin-event", "42",
                  "--json"],
                  env_extra={"HERMES_CC_DB": str(db_path)}, stdin=VALID_BRIEF)
    try:
        data = json.loads(proc.stdout.strip())
        job_id = data["jobId"]
    except (json.JSONDecodeError, KeyError):
        job_id = None
    row = _fetch_row(db_path, job_id) if job_id else None
    ok = (proc.returncode == 0 and row is not None
          and row["tier"] == "investigate" and row["repo"] == "alpha"
          and row["status"] == "queued"
          and row["origin_channel"] == "C0123456789"
          and row["origin_thread_ts"] == "1234567890.123456"
          and row["origin_event_id"] == 42
          and row["reported_at"] is None)
    if ok:
        passed += 1
    else:
        failures.append(f"dispatch record: expected one correct queued row "
                         f"with reported_at NULL, got job_id={job_id!r} "
                         f"row={row!r} rc={proc.returncode}")

    # (b) --wait that reaches a terminal status stamps reported_at.
    total += 1
    db_path2 = h.new_db()
    proc = h.run(["dispatch", "alpha", "--wait", "--json"],
                  env_extra={"HERMES_CC_DB": str(db_path2),
                             "CC_TEST_JOB_STATUS": "done"}, stdin=VALID_BRIEF)
    try:
        data = json.loads(proc.stdout.strip())
        job_id2 = data["jobId"]
    except (json.JSONDecodeError, KeyError):
        job_id2 = None
    row2 = _fetch_row(db_path2, job_id2) if job_id2 else None
    ok = (proc.returncode == 0 and row2 is not None
          and row2["status"] == "done" and row2["reported_at"] is not None)
    if ok:
        passed += 1
    else:
        failures.append(f"--wait to a terminal job: expected reported_at "
                         f"stamped, got job_id={job_id2!r} row={row2!r} "
                         f"rc={proc.returncode}")

    # (c) a bare `status <job-id>` on a terminal job updates status/verdict but
    # leaves reported_at NULL — that debt still belongs to the sweeper.
    total += 1
    db_path3 = h.new_db()
    proc = h.run(["dispatch", "alpha", "--json"],
                  env_extra={"HERMES_CC_DB": str(db_path3)}, stdin=VALID_BRIEF)
    try:
        data = json.loads(proc.stdout.strip())
        job_id3 = data["jobId"]
    except (json.JSONDecodeError, KeyError):
        job_id3 = None
    row_before = _fetch_row(db_path3, job_id3) if job_id3 else None
    status_proc = None
    if job_id3:
        status_proc = h.run(["status", job_id3, "--json"],
                             env_extra={"HERMES_CC_DB": str(db_path3),
                                        "CC_TEST_JOB_STATUS": "done"})
    row_after = _fetch_row(db_path3, job_id3) if job_id3 else None
    ok = (job_id3 is not None and status_proc is not None
          and status_proc.returncode == 0
          and row_before is not None and row_before["status"] == "queued"
          and row_after is not None and row_after["status"] == "done"
          and row_after["reported_at"] is None
          and row_after["verdict_json"] is not None)
    if ok:
        passed += 1
    else:
        failures.append(f"status poll on a terminal job: expected status/"
                         f"verdict updated but reported_at left NULL, got "
                         f"before={row_before!r} after={row_after!r}")

    return total, passed, failures


# =============================================================================
# 12. Write-tier gate — `implement` is the only tier that mutates anything
#     outside this machine, and it may not do so on an agent's own judgement.
#     --why is mandatory (it is the audit record); without --confirm the verb
#     prints its plan and changes nothing at exit 0; the implement tier carries
#     its own tighter daily ceiling; and the audit log distinguishes a plan
#     awaiting a human from a refusal and from a rehearsal.
# =============================================================================

def test_write_tier_gate(h: Harness):
    failures = []
    total = passed = 0

    # (a) no --why: refused as a usage error, nothing submitted.
    total += 1
    curl_log = h.new_log("curl")
    proc = h.run(["dispatch", "gamma", "--tier", "implement", "--confirm"],
                  env_extra={"CC_TEST_CURL_LOG": str(curl_log)}, stdin=VALID_BRIEF)
    ok = (proc.returncode == 64 and "--why" in (proc.stdout + proc.stderr)
          and not _curl_lines(curl_log))
    if ok:
        passed += 1
    else:
        failures.append(f"implement without --why: expected exit 64 demanding "
                         f"--why with nothing submitted, got rc={proc.returncode} "
                         f"stdout={proc.stdout[:300]!r} "
                         f"curl={_curl_lines(curl_log)!r}")

    # (b) --why but no --confirm: the plan, exit 0, nothing submitted, and the
    #     JSON says needsConfirm so the agent cannot read it as a completed run.
    total += 1
    curl_log = h.new_log("curl")
    audit_log = h.new_log("audit-planned")
    proc = h.run(["dispatch", "gamma", "--tier", "implement", "--why",
                  "the check job has failed the same way four times", "--json"],
                  env_extra={"CC_TEST_CURL_LOG": str(curl_log)},
                  audit_log=audit_log, stdin=VALID_BRIEF)
    ok = False
    if proc.returncode == 0 and not _curl_lines(curl_log):
        try:
            data = json.loads(proc.stdout.strip())
            ok = (data.get("needsConfirm") is True
                  and data.get("dryRun") is True
                  and data.get("tier") == "implement"
                  and isinstance(data.get("wouldDo"), list)
                  # The plan must state what CANNOT happen, not only what will:
                  # that is the half a human needs in order to answer "yes".
                  and any("default branch" in s for s in data.get("wouldNeverDo", [])))
        except json.JSONDecodeError:
            ok = False
    if ok:
        passed += 1
    else:
        failures.append(f"implement without --confirm: expected an exit-0 plan "
                         f"with needsConfirm=true and nothing submitted, got "
                         f"rc={proc.returncode} stdout={proc.stdout[:400]!r} "
                         f"curl={_curl_lines(curl_log)!r}")

    # (c) that same unconfirmed run audits as `planned` — not `refused` (no
    #     guard said no) and not `dry-run` (the caller did not ask for one).
    total += 1
    lines = _log_text(audit_log).splitlines()
    ok = len(lines) == 1 and "mode=planned" in lines[0] and "tier=implement" in lines[0]
    if ok:
        passed += 1
    else:
        failures.append(f"unconfirmed implement should audit as mode=planned, "
                         f"got {lines!r}")

    # (d) an explicit --dry-run stays `dry-run` even on a gated tier — the
    #     caller asked for a rehearsal, which is a different fact to record.
    total += 1
    audit_log = h.new_log("audit-dryrun-gated")
    h.run(["dispatch", "gamma", "--tier", "implement", "--why", "rehearsing",
           "--confirm", "--dry-run"], audit_log=audit_log, stdin=VALID_BRIEF)
    lines = _log_text(audit_log).splitlines()
    ok = len(lines) == 1 and "mode=dry-run" in lines[0]
    if ok:
        passed += 1
    else:
        failures.append(f"explicit --dry-run on a gated tier should audit as "
                         f"mode=dry-run, got {lines!r}")

    # (e) --why AND --confirm: the episode is actually opened, carrying the tier
    #     it asked for, and the audit line records the reason.
    total += 1
    curl_log = h.new_log("curl")
    audit_log = h.new_log("audit-opened-implement")
    proc = h.run(["dispatch", "gamma", "--tier", "implement", "--why",
                  "approved in thread", "--confirm", "--json"],
                  env_extra={"CC_TEST_CURL_LOG": str(curl_log)},
                  audit_log=audit_log, stdin=VALID_BRIEF)
    submits = [c for c in _curl_lines(curl_log) if c.get("stdin")]
    ok = False
    if proc.returncode == 0 and len(submits) == 1:
        body = json.loads(submits[0]["stdin"])
        audit = _log_text(audit_log)
        ok = (body["params"]["tier"] == "implement"
              and body["params"]["brief"] == VALID_BRIEF
              and "mode=opened" in audit and "why=approved in thread" in audit)
    if ok:
        passed += 1
    else:
        failures.append(f"confirmed implement: expected one submit at "
                         f"tier=implement and mode=opened with the reason "
                         f"audited, got rc={proc.returncode} curl={submits!r} "
                         f"audit={_log_text(audit_log)!r}")

    # (f) the implement tier has its OWN daily ceiling, independent of the
    #     overall one — an exhausted implement budget refuses while the shared
    #     budget still has room, and nothing is submitted.
    total += 1
    db_path = h.new_db()
    h.run(["list"], env_extra={"HERMES_CC_DB": str(db_path)})
    now = dt.datetime.now(dt.timezone.utc).isoformat()
    conn = sqlite3.connect(db_path)
    conn.execute(
        "INSERT INTO dispatches(job_id,tier,repo,brief,status,created_at) "
        "VALUES(?,?,?,?,?,?)",
        ("preseeded-impl", "implement", "gamma", "preseeded", "done", now),
    )
    conn.commit()
    conn.close()
    curl_log = h.new_log("curl")
    proc = h.run(["dispatch", "gamma", "--tier", "implement", "--why", "second one",
                  "--confirm", "--json"],
                  env_extra={"HERMES_CC_DB": str(db_path),
                             "HERMES_CC_DAILY_BUDGET": "20",
                             "HERMES_CC_IMPLEMENT_BUDGET": "1",
                             "CC_TEST_CURL_LOG": str(curl_log)},
                  stdin=VALID_BRIEF)
    # The refusal must also say which ceiling was hit and how to raise THAT one:
    # a caller told only "budget exhausted" would reach for the shared knob and
    # still be refused, or worse, raise the wrong ceiling.
    ok = (proc.returncode == 4
          and "implement budget" in (proc.stdout + proc.stderr)
          and "HERMES_CC_IMPLEMENT_BUDGET" in (proc.stdout + proc.stderr)
          and not _curl_lines(curl_log))
    if ok:
        passed += 1
    else:
        failures.append(f"implement over its own ceiling while the shared budget "
                         f"has room: expected exit 4 naming HERMES_CC_IMPLEMENT_BUDGET "
                         f"with nothing submitted, got "
                         f"rc={proc.returncode} stdout={proc.stdout[:300]!r} "
                         f"curl={_curl_lines(curl_log)!r}")

    # (g-pre) A malformed dispatch policy must FAIL CLOSED, always at exit 2 —
    #     a policy that does not parse, or contradicts itself, must never be
    #     read as a permissive one. Four distinct ways it can be wrong, each
    #     its own case: an unknown tier KEY would otherwise be silently
    #     ignored, which — with defaultTier=author — quietly PROMOTES every
    #     repo listed under it to a write tier; a name in both `deny` and
    #     `tiers` is a contradiction, not a precedence question, and picking a
    #     winner would hide which reading of the file is wrong; an
    #     unrecognized `defaultTier` has the same silently-permissive failure
    #     mode as the tier-key case, just at the top level; and JSON that
    #     doesn't parse at all must not fall back to any default. Caught by
    #     adversarial review; reproduced before it was fixed.
    malformed_cases = [
        ("unknown tier key", {
            "root": str(h.repos_root), "defaultTier": "author",
            "tiers": {"implment": ["gamma"]},
        }, "unknown tier"),
        ("name in both deny and tiers", {
            "root": str(h.repos_root), "defaultTier": "author",
            "deny": ["gamma"], "tiers": {"implement": ["gamma"]},
        }, "named in both"),
        ("invalid defaultTier", {
            "root": str(h.repos_root), "defaultTier": "godmode",
        }, "unrecognized defaultTier"),
    ]
    for i, (label, policy, expect_text) in enumerate(malformed_cases):
        total += 1
        bad_json = h.root / f"repos-bad-{i}.json"
        bad_json.write_text(json.dumps(policy))
        curl_log = h.new_log("curl")
        proc = h.run(["dispatch", "gamma", "--tier", "implement", "--why",
                      "malformed probe", "--confirm", "--json"],
                      env_extra={"HERMES_CC_REPOS_JSON": str(bad_json),
                                 "CC_TEST_CURL_LOG": str(curl_log)},
                      stdin=VALID_BRIEF)
        text = proc.stdout + proc.stderr
        ok = proc.returncode == 2 and expect_text in text and not _curl_lines(curl_log)
        if ok:
            passed += 1
        else:
            failures.append(f"malformed policy ({label}) must fail closed at "
                             f"exit 2, got rc={proc.returncode} "
                             f"stdout={proc.stdout[:300]!r} "
                             f"curl={_curl_lines(curl_log)!r}")

    total += 1
    bad_json = h.root / "repos-bad-unparseable.json"
    bad_json.write_text("{not valid json")
    curl_log = h.new_log("curl")
    proc = h.run(["dispatch", "gamma", "--tier", "implement", "--why",
                  "malformed probe", "--confirm", "--json"],
                  env_extra={"HERMES_CC_REPOS_JSON": str(bad_json),
                             "CC_TEST_CURL_LOG": str(curl_log)},
                  stdin=VALID_BRIEF)
    ok = proc.returncode == 2 and not _curl_lines(curl_log)
    if ok:
        passed += 1
    else:
        failures.append(f"unparseable policy JSON must fail closed at exit 2, "
                         f"got rc={proc.returncode} stdout={proc.stdout[:300]!r} "
                         f"curl={_curl_lines(curl_log)!r}")

    # (g) `author` is deliberately NOT gated — no --why, no --confirm, and it
    #     still opens. A gate on every tier would make the implement gate
    #     routine, which is exactly how an approval prompt stops being read.
    total += 1
    curl_log = h.new_log("curl")
    proc = h.run(["dispatch", "gamma", "--tier", "author", "--json"],
                  env_extra={"CC_TEST_CURL_LOG": str(curl_log)}, stdin=VALID_BRIEF)
    submits = [c for c in _curl_lines(curl_log) if c.get("stdin")]
    ok = proc.returncode == 0 and len(submits) == 1
    if ok:
        passed += 1
    else:
        failures.append(f"author tier should need no --why/--confirm, got "
                         f"rc={proc.returncode} curl={submits!r}")

    return total, passed, failures


# =============================================================================
# 13. Artifact plumbing — an author/implement episode returns a URL, and that
#     URL is the one field a caller acts on. It must reach both the --json
#     payload's top level and its own `artifact_url` column, so the GitHub
#     projection is a column read rather than a JSON parse.
# =============================================================================

def test_artifact_plumbing(h: Harness):
    failures = []
    total = passed = 0

    pr_url = "https://github.com/jkrumm/dispatch-scratch/pull/7"
    verdict = json.dumps({
        "verdict": "stub verdict text",
        "confidence": "high",
        "evidence": [],
        "recommendation": "stub recommendation",
        "nextAction": "none",
        "summary": "stub summary",
        "artifactUrl": pr_url,
        "branch": "dispatch/stub-abcd1234",
    })

    total += 1
    db_path = h.new_db()
    proc = h.run(["dispatch", "gamma", "--tier", "implement", "--why", "artifact test",
                  "--confirm", "--wait", "--json"],
                  env_extra={"HERMES_CC_DB": str(db_path),
                             "CC_TEST_JOB_RESULT": verdict},
                  stdin=VALID_BRIEF)
    ok = False
    job_id = None
    try:
        data = json.loads(proc.stdout.strip())
        job_id = data.get("jobId")
        ok = (data.get("artifactUrl") == pr_url
              and data.get("branch") == "dispatch/stub-abcd1234")
    except json.JSONDecodeError:
        ok = False
    if ok:
        passed += 1
    else:
        failures.append(f"--wait result should hoist artifactUrl/branch to the "
                         f"top level, got {proc.stdout[:400]!r}")

    total += 1
    row = _fetch_row(db_path, job_id) if job_id else None
    ok = row is not None and row["artifact_url"] == pr_url
    if ok:
        passed += 1
    else:
        failures.append(f"the dispatch row should carry artifact_url in its own "
                         f"column, got {row!r}")

    # A verdict with no artifact must leave the column NULL rather than storing
    # an empty string — "produced nothing" and "produced something empty" are
    # different states, and the briefing filters on IS NOT NULL.
    total += 1
    db_path = h.new_db()
    proc = h.run(["dispatch", "gamma", "--tier", "author", "--wait", "--json"],
                  env_extra={"HERMES_CC_DB": str(db_path)}, stdin=VALID_BRIEF)
    try:
        job_id = json.loads(proc.stdout.strip()).get("jobId")
    except json.JSONDecodeError:
        job_id = None
    row = _fetch_row(db_path, job_id) if job_id else None
    ok = row is not None and row["artifact_url"] is None
    if ok:
        passed += 1
    else:
        failures.append(f"a verdict carrying no artifactUrl should leave the "
                         f"column NULL, got {row!r}")

    return total, passed, failures


# =============================================================================
# 11. No free-form surface — static grep for a passthrough/eval shape.
# =============================================================================

# =============================================================================
# 14. Merge — the only verb that changes what RUNS. It merges a PR this bridge
#     opened, addressed by JOB ID so no caller input ever names a pull request,
#     only where a human review is not required, and only while every bound the
#     episode was held to still holds against the current head. Each refusal case
#     below poses exactly ONE bad condition, so a pass proves that specific guard
#     fired and not some neighbouring accident.
# =============================================================================

MERGE_JOB = "merge-job-0001"
PR_URL = "https://github.com/jkrumm/gamma/pull/7"
GOOD_HEAD = {"ref": "dispatch/stub-branch", "sha": "deadbeef" * 5,
             "repo": {"full_name": "jkrumm/gamma"}}


def _seed_pr_dispatch(h: Harness, db_path, *, tier="implement", repo="gamma",
                      status="done", artifact=PR_URL, job_id=MERGE_JOB) -> None:
    # `list` first so the script creates the schema AND applies the additive
    # merged_at migration before anything is inserted.
    h.run(["list"], env_extra={"HERMES_CC_DB": str(db_path)})
    now = dt.datetime.now(dt.timezone.utc).isoformat()
    conn = sqlite3.connect(db_path)
    conn.execute(
        "INSERT INTO dispatches(job_id,tier,repo,brief,status,artifact_url,created_at) "
        "VALUES(?,?,?,?,?,?,?)",
        (job_id, tier, repo, "seed brief", status, artifact, now),
    )
    conn.commit()
    conn.close()


def _merged_at(db_path, job_id=MERGE_JOB):
    conn = sqlite3.connect(db_path)
    row = conn.execute("SELECT merged_at FROM dispatches WHERE job_id=?", (job_id,)).fetchone()
    conn.close()
    return row[0] if row else None


def test_merge_verb(h: Harness):
    failures = []
    total = passed = 0

    def pr(**over):
        base = {"state": "open", "merged": False, "draft": True,
                "node_id": "PR_kwstub", "title": "stub pr title",
                "base": {"ref": "master"}, "head": GOOD_HEAD,
                "changed_files": 2, "additions": 4, "deletions": 4,
                "mergeable": True, "mergeable_state": "clean"}
        base.update(over)
        return json.dumps(base)

    # (a) every refusal, each with one thing wrong and nothing else.
    refusals = [
        ("unknown job id", {"job_id": "some-other-job"}, {}, 2, "no dispatch recorded"),
        ("read-only tier", {"tier": "investigate"}, {}, 4, "produces no pull request"),
        ("episode failed", {"status": "failed"}, {}, 4, "not 'done'"),
        ("no artifact", {"artifact": None}, {}, 4, "no artifact URL"),
        ("issue url, not a pr", {"artifact": "https://github.com/jkrumm/gamma/issues/7"},
         {}, 4, "not a pull request URL"),
        ("foreign owner", {"artifact": "https://github.com/someone-else/gamma/pull/7"},
         {}, 4, "belongs to"),
        ("record disagrees with itself",
         {"artifact": "https://github.com/jkrumm/alpha/pull/7"}, {}, 4, "disagrees with itself"),
        ("repo ceiling now below implement",
         {"repo": "beta", "artifact": "https://github.com/jkrumm/beta/pull/7"},
         {}, 4, "ceiling is now"),
        ("repo requires human review", {},
         {"HERMES_CC_PR_REQUIRED_JSON": "GAMMA"}, 4, "human pull-request review"),
        ("pull request closed", {}, {"CC_TEST_PR_JSON": pr(state="closed")}, 4, "not open"),
        ("already merged on github", {}, {"CC_TEST_PR_JSON": pr(merged=True)}, 4, "already merged"),
        ("base retargeted", {}, {"CC_TEST_PR_JSON": pr(base={"ref": "release"})},
         4, "not the default branch"),
        ("head is not a dispatch branch", {},
         {"CC_TEST_PR_JSON": pr(head={"ref": "feature/x", "sha": "a" * 40,
                                      "repo": {"full_name": "jkrumm/gamma"}})},
         4, "not a dispatch"),
        ("head is a fork", {},
         {"CC_TEST_PR_JSON": pr(head={"ref": "dispatch/x", "sha": "a" * 40,
                                      "repo": {"full_name": "someone-else/gamma"}})},
         4, "fork"),
        ("over the file ceiling", {}, {"CC_TEST_PR_JSON": pr(changed_files=99)},
         4, "over the"),
        ("over the line ceiling", {}, {"CC_TEST_PR_JSON": pr(additions=4000)},
         4, "over the"),
        ("touches CI definitions", {},
         {"CC_TEST_PR_FILES": json.dumps([{"filename": ".github/workflows/ci.yml"}])},
         4, "CI definitions"),
        ("no merge method allowed", {},
         {"CC_TEST_REPO_JSON": json.dumps({"default_branch": "master",
                                           "allow_squash_merge": False,
                                           "allow_rebase_merge": False,
                                           "allow_merge_commit": False})},
         4, "no merge method"),
    ]

    for label, seed, env, want_rc, want_text in refusals:
        total += 1
        db_path = h.new_db()
        job_id = seed.pop("job_id", None)
        _seed_pr_dispatch(h, db_path, **seed)
        env_extra = {"HERMES_CC_DB": str(db_path)}
        curl_log = h.new_log("curl")
        env_extra["CC_TEST_CURL_LOG"] = str(curl_log)
        for k, v in env.items():
            env_extra[k] = str(h.pr_required_gamma) if v == "GAMMA" else v
        proc = h.run(["merge", job_id or MERGE_JOB, "--why", "test", "--confirm", "--json"],
                      env_extra=env_extra)
        text = proc.stdout + proc.stderr
        # A refusal must also be inert: nothing un-drafted, nothing merged.
        touched = [c for c in _curl_lines(curl_log)
                   if "/graphql" in c["argv"][-1] or c["argv"][-1].endswith("/merge")]
        ok = proc.returncode == want_rc and want_text in text and not touched
        if ok:
            passed += 1
        else:
            failures.append(f"merge refusal [{label}]: expected rc={want_rc} "
                             f"containing {want_text!r} with no graphql/merge call, got "
                             f"rc={proc.returncode} touched={touched!r} text={text[:300]!r}")

    # (b) --why is mandatory: it is the audit record for landing code unattended.
    total += 1
    db_path = h.new_db()
    _seed_pr_dispatch(h, db_path)
    proc = h.run(["merge", MERGE_JOB, "--confirm", "--json"],
                  env_extra={"HERMES_CC_DB": str(db_path)})
    ok = proc.returncode == 64 and "--why" in (proc.stdout + proc.stderr)
    if ok:
        passed += 1
    else:
        failures.append(f"merge without --why: expected exit 64, got "
                         f"rc={proc.returncode} {proc.stdout[:200]!r}")

    # (c) without --confirm it prints the plan, exits 0, and — the part that
    #     matters — has NOT un-drafted the pull request. Un-drafting is the one
    #     irreversible-looking step before the merge, so it must not happen as a
    #     side effect of asking what would happen.
    total += 1
    db_path = h.new_db()
    _seed_pr_dispatch(h, db_path)
    curl_log = h.new_log("curl")
    audit_log = h.new_log("audit-merge-plan")
    proc = h.run(["merge", MERGE_JOB, "--why", "test", "--json"],
                  env_extra={"HERMES_CC_DB": str(db_path),
                             "CC_TEST_CURL_LOG": str(curl_log)},
                  audit_log=audit_log)
    try:
        data = json.loads(proc.stdout.strip())
    except json.JSONDecodeError:
        data = {}
    mutating = [c for c in _curl_lines(curl_log)
                if "/graphql" in c["argv"][-1] or c["argv"][-1].endswith("/merge")]
    lines = _log_text(audit_log).splitlines()
    ok = (proc.returncode == 0 and data.get("dryRun") is True
          and data.get("needsConfirm") is True
          and data.get("mergeMethod") == "squash"
          and not mutating and _merged_at(db_path) is None
          and len(lines) == 1 and "mode=planned" in lines[0])
    if ok:
        passed += 1
    else:
        failures.append(f"merge without --confirm: expected an inert plan at rc=0 "
                         f"audited as planned, got rc={proc.returncode} "
                         f"data={data!r} mutating={mutating!r} audit={lines!r}")

    # (d) mergeable_state is checked AFTER the un-draft, so this case proves the
    #     merge still does not happen once it is too late to refuse earlier.
    total += 1
    db_path = h.new_db()
    _seed_pr_dispatch(h, db_path)
    curl_log = h.new_log("curl")
    proc = h.run(["merge", MERGE_JOB, "--why", "test", "--confirm", "--json"],
                  env_extra={"HERMES_CC_DB": str(db_path),
                             "CC_TEST_CURL_LOG": str(curl_log),
                             "CC_TEST_PR_JSON": pr(mergeable_state="blocked")})
    merged_calls = [c for c in _curl_lines(curl_log) if c["argv"][-1].endswith("/merge")]
    text = proc.stdout + proc.stderr
    ok = (proc.returncode == 4 and "blocked" in text and not merged_calls
          and _merged_at(db_path) is None)
    if ok:
        passed += 1
    else:
        failures.append(f"blocked mergeable_state: expected exit 4 with nothing "
                         f"merged, got rc={proc.returncode} merged={merged_calls!r} "
                         f"text={text[:300]!r}")

    # (e) the happy path: ready-for-review, merge with the head SHA PINNED,
    #     branch deleted, record stamped, audited as `merged` and not `opened`.
    total += 1
    db_path = h.new_db()
    _seed_pr_dispatch(h, db_path)
    curl_log = h.new_log("curl")
    audit_log = h.new_log("audit-merge")
    proc = h.run(["merge", MERGE_JOB, "--why", "landing the fix", "--confirm", "--json"],
                  env_extra={"HERMES_CC_DB": str(db_path),
                             "CC_TEST_CURL_LOG": str(curl_log)},
                  audit_log=audit_log)
    try:
        data = json.loads(proc.stdout.strip())
    except json.JSONDecodeError:
        data = {}
    calls = _curl_lines(curl_log)
    put = [c for c in calls if c["argv"][-1].endswith("/merge")]
    graphql = [c for c in calls if "/graphql" in c["argv"][-1]]
    deleted = [c for c in calls if "/git/refs/heads/" in c["argv"][-1]]
    body = json.loads(put[0]["stdin"]) if put and put[0]["stdin"] else {}
    lines = _log_text(audit_log).splitlines()
    ok = (proc.returncode == 0 and data.get("merged") is True
          and data.get("mergeMethod") == "squash"
          and data.get("mergeCommit") == "mergedsha001"
          and data.get("branchDeleted") is True
          and len(graphql) == 1 and len(put) == 1 and len(deleted) == 1
          and body.get("sha") == "deadbeef" * 5
          and body.get("merge_method") == "squash"
          and _merged_at(db_path) is not None
          and len(lines) == 1 and "mode=merged" in lines[0] and "rc=0" in lines[0])
    if ok:
        passed += 1
    else:
        failures.append(f"merge happy path: expected a pinned-SHA squash merge "
                         f"recorded and audited as merged, got rc={proc.returncode} "
                         f"data={data!r} body={body!r} audit={lines!r}")

    # (f) the credential never reaches argv. This machine runs triage that reads
    #     `ps` output, so a token in the process table is a real leak path.
    total += 1
    flat = " ".join(" ".join(c["argv"]) for c in calls)
    ok = "github_pat_" not in flat and "Authorization" not in flat
    if ok:
        passed += 1
    else:
        failures.append("the GitHub token or its header reached curl's argv")

    # (g) merging twice is not a retry.
    total += 1
    proc = h.run(["merge", MERGE_JOB, "--why", "again", "--confirm", "--json"],
                  env_extra={"HERMES_CC_DB": str(db_path)})
    ok = proc.returncode == 4 and "already merged" in (proc.stdout + proc.stderr)
    if ok:
        passed += 1
    else:
        failures.append(f"second merge of the same job: expected exit 4, got "
                         f"rc={proc.returncode} {proc.stdout[:200]!r}")

    # (h) the merge ceiling is its own, tighter than implement's, and its refusal
    #     names the var that raises it.
    total += 1
    db_path = h.new_db()
    _seed_pr_dispatch(h, db_path)
    now = dt.datetime.now(dt.timezone.utc).isoformat()
    conn = sqlite3.connect(db_path)
    conn.execute(
        "INSERT INTO dispatches(job_id,tier,repo,brief,status,created_at,merged_at) "
        "VALUES(?,?,?,?,?,?,?)",
        ("already-merged-today", "implement", "gamma", "b", "done", now, now),
    )
    conn.commit()
    conn.close()
    curl_log = h.new_log("curl")
    proc = h.run(["merge", MERGE_JOB, "--why", "over ceiling", "--confirm", "--json"],
                  env_extra={"HERMES_CC_DB": str(db_path),
                             "HERMES_CC_MERGE_BUDGET": "1",
                             "CC_TEST_CURL_LOG": str(curl_log)})
    text = proc.stdout + proc.stderr
    ok = (proc.returncode == 4 and "HERMES_CC_MERGE_BUDGET" in text
          and not [c for c in _curl_lines(curl_log) if c["argv"][-1].endswith("/merge")])
    if ok:
        passed += 1
    else:
        failures.append(f"merge over its daily ceiling: expected exit 4 naming "
                         f"HERMES_CC_MERGE_BUDGET, got rc={proc.returncode} "
                         f"{text[:300]!r}")

    return total, passed, failures


def test_no_freeform_surface():
    failures = []
    src = CC_SCRIPT.read_text()

    # No eval anywhere in this script (unlike hermes-ops.sh's one reviewed
    # run_plan() invocation) — the allowlist is deliberately empty, so any hit
    # fails loudly.
    known_eval = set()
    eval_lines = [ln.strip() for ln in src.splitlines() if re.search(r"\beval\b", ln)]
    if set(eval_lines) - known_eval:
        failures.append(f"unexpected `eval` usage — expected none, found: {eval_lines}")

    # No `bash -c "$...` / `sh -c "$...` free-form-shell shape either.
    known_bash_c = set()
    bash_c_lines = [ln.strip() for ln in src.splitlines()
                    if re.search(r'(bash|sh)\s+-c\s+"\$', ln)]
    if set(bash_c_lines) - known_bash_c:
        failures.append('unexpected `bash -c "$...` / `sh -c "$...` '
                         f"free-form-shell shape: {bash_c_lines}")

    # Unquoted $@ reaching curl — never allowlisted; this script has none (the
    # $@ instances that exist are `_err "$@"` argument forwarding and
    # in_list()'s membership loop, neither of which touches curl).
    for lineno, ln in enumerate(src.splitlines(), start=1):
        if "curl" in ln and re.search(r'(?<!")\$@(?!")', ln):
            failures.append(f"line {lineno}: unquoted $@ reaching curl: {ln.strip()}")

    total = 3
    passed = total if not failures else 0
    return total, passed, failures


# =============================================================================

def main() -> int:
    h = Harness()
    try:
        groups = [
            ("1. closed verb set", test_closed_verb_set(h)),
            ("2. argument bounding", test_argument_bounding(h)),
            ("3. repo resolution", test_repo_resolution(h)),
            ("3b. repo name confinement", test_repo_name_confinement(h)),
            ("4. tier gating", test_tier_gating(h)),
            ("5. brief is data", test_brief_is_data(h)),
            ("6. --json contract", test_json_contract(h)),
            ("7. audit log", test_audit_log(h)),
            ("8. daily budget", test_daily_budget(h)),
            ("9. recursion guard", test_recursion_guard(h)),
            ("10. dispatch record", test_dispatch_record(h)),
            ("11. no free-form surface", test_no_freeform_surface()),
            ("12. write-tier gate", test_write_tier_gate(h)),
            ("13. artifact plumbing", test_artifact_plumbing(h)),
            ("14. merge verb", test_merge_verb(h)),
        ]
    finally:
        h.cleanup()

    all_failures = []
    grand_total = grand_passed = 0
    for name, (total, passed, failures) in groups:
        grand_total += total
        grand_passed += passed
        print(f"{name:<38} {passed}/{total}")
        all_failures.extend(f"[{name}] {msg}" for msg in failures)

    if all_failures:
        print("\nFAILURES:")
        for msg in all_failures:
            print(f"  {msg}")
        print(f"\n{grand_passed}/{grand_total} passed, "
              f"{grand_total - grand_passed} failed")
        return 1

    print(f"\nall {grand_total} cases as expected")
    return 0


if __name__ == "__main__":
    sys.exit(main())
