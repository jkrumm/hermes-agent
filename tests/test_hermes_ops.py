#!/usr/bin/env python3
"""Regression suite for `scripts/hermes-ops.sh` — the sole infrastructure-
mutation path the Hermes agent can invoke.

Covers the security properties that make it safe to hand an LLM a bounded
verb dispatcher instead of a raw `terminal` tool: argument bounding against
each verb's fixed or live list, the absence of any free-form SQL/shell/URL
escape hatch, Tier B's double gate (`--why` AND `--confirm`, default
dry-run), the closed verb set (no fallthrough to a shell), the `--json`
contract (exactly one parseable object per invocation, success or failure),
the audit log (one line per call, secrets redacted), the `launchd-repair`
label allowlist (`ai.hermes.gateway` excluded — Hermes cannot restart its
own gateway), and the `uk-sync` -> `env-check` hard gate that makes the
2026-08-01 uptime-kuma corruption unreachable through this script.

Every case here runs against a stubbed `ssh`/`curl`/`launchctl`/`make` on
PATH and an isolated fake `$HOME` (own `secrets-run` stub, own
`devhost-health-check.sh`, own launchd plist) — no real network call, no
real 1Password read, no real ssh to homelab/vps, no real launchd mutation,
ever. Safe to run repeatedly on the live Mac mini.

Run:

    ~/.hermes/hermes-agent/venv/bin/python3 tests/test_hermes_ops.py

Exit status is 0 only when every case matches.
"""

import json
import os
import re
import shutil
import stat
import subprocess
import sys
import tempfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
OPS_SCRIPT = REPO_ROOT / "scripts" / "hermes-ops.sh"

# --- stub programs -----------------------------------------------------------
# Each records its argv (one JSON array per line) to the log path named by its
# own env var, so a test can assert on *what would have been run* without any
# of it actually reaching a network, a real host, or real launchd.

FAKE_SSH = """#!/usr/bin/env python3
import json, os, sys

argv = sys.argv[1:]
log = os.environ.get("OPS_TEST_SSH_LOG")
if log:
    with open(log, "a") as f:
        f.write(json.dumps(argv) + "\\n")

host = argv[-2] if len(argv) >= 2 else ""
key = host.upper().replace("-", "_") or "DEFAULT"

exit_code = int(os.environ.get(
    f"OPS_TEST_SSH_EXIT_{key}", os.environ.get("OPS_TEST_SSH_EXIT", "0")))
output = os.environ.get(
    f"OPS_TEST_SSH_OUTPUT_{key}", os.environ.get("OPS_TEST_SSH_OUTPUT", ""))

if output:
    sys.stdout.write(output)
sys.exit(exit_code)
"""

FAKE_CURL = """#!/usr/bin/env python3
import json, os, sys

argv = sys.argv[1:]
log = os.environ.get("OPS_TEST_CURL_LOG")
if log:
    with open(log, "a") as f:
        f.write(json.dumps(argv) + "\\n")

url = ""
for a in reversed(argv):
    if a.startswith("http"):
        url = a
        break

containers = json.loads(os.environ.get(
    "OPS_TEST_CONTAINERS",
    '[{"name": "known-container", "state": "running", '
    '"health": "healthy", "restartCount": 0}]'))

body = "{}"
if "/containers" in url:
    body = json.dumps(containers)
elif "/logs/" in url:
    body = json.dumps({"lines": ["line one", "line two"]})
elif "/uptime-kuma/status" in url:
    body = json.dumps({"down": 0, "up": 3, "total": 3, "status": "UP"})
elif "/uptime-kuma/monitors" in url:
    body = json.dumps({"monitors": []})
elif "/summary" in url:
    body = json.dumps({"uptimeKuma": {}, "dockerHomelab": {"counts": {}},
                        "dockerVps": {"counts": {}}})
elif "/slack/channels/" in url:
    body = json.dumps({"messages": [], "has_more": False})

status = os.environ.get("OPS_TEST_CURL_STATUS", "200")
sys.stdout.write(body + "\\n" + status)
sys.exit(0)
"""

FAKE_LAUNCHCTL = """#!/usr/bin/env python3
import json, os, sys

argv = sys.argv[1:]
log = os.environ.get("OPS_TEST_LAUNCHCTL_LOG")
if log:
    with open(log, "a") as f:
        f.write(json.dumps(argv) + "\\n")

if argv and argv[0] == "print":
    # Always report "not registered in the domain" so the plan-print path is
    # deterministic regardless of this Mac's real launchd state right now —
    # this suite never inspects or touches real launchd.
    sys.stderr.write("Could not find service in domain for port\\n")
    sys.exit(1)

sys.exit(0)
"""

FAKE_MAKE = """#!/usr/bin/env python3
import json, os, sys

log = os.environ.get("OPS_TEST_MAKE_LOG")
if log:
    with open(log, "a") as f:
        f.write(json.dumps(sys.argv[1:]) + "\\n")
sys.exit(0)
"""

FAKE_SECRETS_RUN = """#!/usr/bin/env python3
import sys

args = sys.argv[1:]
if args and args[0] == "read":
    print("test-fake-api-key-value")
    sys.exit(0)
sys.exit(1)
"""

FAKE_PLIST = """<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" \
"http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key>
  <string>com.jkrumm.sideclaw</string>
</dict>
</plist>
"""


def _write_exec(path: Path, content: str) -> None:
    path.write_text(content)
    mode = path.stat().st_mode
    path.chmod(mode | stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH)


class Harness:
    """One isolated stub PATH + fake $HOME, reused across the whole run."""

    def __init__(self) -> None:
        self.root = Path(tempfile.mkdtemp(prefix="hermes-ops-test-"))
        self.bin = self.root / "bin"
        self.bin.mkdir()
        _write_exec(self.bin / "ssh", FAKE_SSH)
        _write_exec(self.bin / "curl", FAKE_CURL)
        _write_exec(self.bin / "launchctl", FAKE_LAUNCHCTL)
        _write_exec(self.bin / "make", FAKE_MAKE)

        self.home = self.root / "home"
        (self.home / ".local" / "bin").mkdir(parents=True)
        _write_exec(self.home / ".local" / "bin" / "secrets-run", FAKE_SECRETS_RUN)

        # devhost-health's script-existence precondition is a hardcoded
        # $HOME-relative path. Give it a harmless stand-in so the property
        # under test (Tier B gating) is what actually gets exercised.
        devhost_script = (
            self.home / "SourceRoot" / "dotfiles" / "scripts"
            / "devhost-health-check.sh"
        )
        devhost_script.parent.mkdir(parents=True)
        _write_exec(devhost_script, "#!/usr/bin/env bash\necho ok\n")

        # launchd-repair's plist-existence + plutil-lint precondition, for
        # the one allowlisted label this suite dry-runs.
        launch_agents = self.home / "Library" / "LaunchAgents"
        launch_agents.mkdir(parents=True)
        (launch_agents / "com.jkrumm.sideclaw.plist").write_text(FAKE_PLIST)

        self.backend_file = self.root / "backend"
        self.backend_file.write_text("cache\n")

        self.log_dir = self.root / "logs"
        self.log_dir.mkdir()
        self._counter = 0

    def cleanup(self) -> None:
        shutil.rmtree(self.root, ignore_errors=True)

    def new_log(self, prefix: str) -> Path:
        self._counter += 1
        return self.log_dir / f"{prefix}-{self._counter}.log"

    def run(self, args, *, env_extra=None, audit_log=None, timeout=20):
        env = dict(os.environ)
        env["PATH"] = f"{self.bin}:{env.get('PATH', '')}"
        env["HOME"] = str(self.home)
        env["SECRETS_BACKEND_FILE"] = str(self.backend_file)
        env["HERMES_OPS_LOG"] = str(audit_log or self.new_log("audit"))
        env.pop("OP_SERVICE_ACCOUNT_TOKEN", None)
        if env_extra:
            env.update(env_extra)
        try:
            return subprocess.run(
                ["bash", str(OPS_SCRIPT), *args],
                env=env,
                capture_output=True,
                text=True,
                timeout=timeout,
            )
        except subprocess.TimeoutExpired:
            return subprocess.CompletedProcess(
                args, returncode=-1, stdout="", stderr="<subprocess timed out>"
            )


def _log_text(path: Path) -> str:
    return path.read_text() if path.exists() else ""


# =============================================================================
# 1. Argument bounding — every verb taking a host/container/stack/job/label/
#    preset must reject anything off its fixed or live list, exit 64, and
#    never reach a mutating remote (ssh). A live-list check (valid_container)
#    is expected to consult argo (curl, read-only) for a shape-valid-but-
#    unknown value — everything else must not touch curl either.
# =============================================================================

ARG_SLOTS = [
    dict(name="containers:host", build=lambda p: ["containers", p],
         shell_meta="homelab; whoami", newline="homelab\nwhoami",
         curl_on_unknown=False),
    dict(name="logs:host", build=lambda p: ["logs", p, "known-container"],
         shell_meta="homelab; whoami", newline="homelab\nwhoami",
         curl_on_unknown=False),
    dict(name="logs:container", build=lambda p: ["logs", "homelab", p],
         shell_meta="caddy $(whoami)", newline="caddy\nwhoami",
         curl_on_unknown=True),
    dict(name="restart:host",
         build=lambda p: ["restart", p, "known-container", "--why", "test"],
         shell_meta="homelab; whoami", newline="homelab\nwhoami",
         curl_on_unknown=False),
    dict(name="restart:container",
         build=lambda p: ["restart", "homelab", p, "--why", "test"],
         shell_meta="caddy $(whoami)", newline="caddy\nwhoami",
         curl_on_unknown=True),
    dict(name="redeploy:host",
         build=lambda p: ["redeploy", p, "homelab", "--why", "test"],
         shell_meta="homelab; whoami", newline="homelab\nwhoami",
         curl_on_unknown=False),
    dict(name="redeploy:stack",
         build=lambda p: ["redeploy", "homelab", p, "--why", "test"],
         shell_meta="homelab; whoami", newline="homelab\nwhoami",
         curl_on_unknown=False),
    dict(name="cron-rerun:job",
         build=lambda p: ["cron-rerun", p, "--why", "test"],
         shell_meta="vpn-watchdog; rm -rf /tmp/x",
         newline="vpn-watchdog\nrm -rf /tmp/x", curl_on_unknown=False),
    dict(name="launchd-repair:label",
         build=lambda p: ["launchd-repair", p, "--why", "test"],
         shell_meta="com.jkrumm.sideclaw; whoami",
         newline="com.jkrumm.sideclaw\nwhoami", curl_on_unknown=False),
    dict(name="kuma-db:preset", build=lambda p: ["kuma-db", p],
         shell_meta="monitor-config; DROP TABLE monitor",
         newline="monitor-config\nDROP TABLE monitor", curl_on_unknown=False),
]


def test_argument_bounding(h: Harness):
    failures = []
    total = passed = 0
    for slot in ARG_SLOTS:
        cases = {
            "unknown": "not-a-real-value",
            "shell_meta": slot["shell_meta"],
            "newline": slot["newline"],
            "leading_dash": "-rf",
            "empty": "",
        }
        for case_name, payload in cases.items():
            total += 1
            label = f"{slot['name']}/{case_name}"
            args = slot["build"](payload)
            ssh_log = h.new_log("ssh")
            curl_log = h.new_log("curl")
            proc = h.run(args, env_extra={
                "OPS_TEST_SSH_LOG": str(ssh_log),
                "OPS_TEST_CURL_LOG": str(curl_log),
            })

            if proc.returncode != 64:
                failures.append(
                    f"{label}: expected exit 64, got {proc.returncode} "
                    f"(stdout={proc.stdout[:200]!r} stderr={proc.stderr[:200]!r})")
                continue
            if _log_text(ssh_log).strip():
                failures.append(f"{label}: rejected value still reached ssh: "
                                 f"{_log_text(ssh_log)!r}")
                continue
            expect_curl = case_name == "unknown" and slot["curl_on_unknown"]
            has_curl = bool(_log_text(curl_log).strip())
            if expect_curl and not has_curl:
                failures.append(
                    f"{label}: expected the live-list check to consult argo "
                    "and it did not")
                continue
            if not expect_curl and has_curl:
                failures.append(f"{label}: rejected value still reached curl: "
                                 f"{_log_text(curl_log)!r}")
                continue
            passed += 1
    return total, passed, failures


# =============================================================================
# 2. No free-form surface — static grep for a passthrough/eval shape.
# =============================================================================

def test_no_freeform_surface():
    failures = []
    src = OPS_SCRIPT.read_text()

    # `eval` — allowlist the one reviewed run_plan() invocation, which only
    # ever evals a PLAN[] entry built from validated/fixed strings. Any other
    # eval, or a change to that one's shape, is the failure this guards.
    eval_lines = [ln.strip() for ln in src.splitlines() if re.search(r"\beval\b", ln)]
    known_eval = {'out=$(eval "$i" 2>&1)'}
    if len(eval_lines) != 1 or set(eval_lines) - known_eval:
        failures.append(f"unexpected `eval` usage — expected exactly the "
                         f"reviewed run_plan() invocation, found: {eval_lines}")

    # `bash -c "$...` / `sh -c "$...` — allowlist sync-drift's reviewed
    # drift_probe_cmd() invocation. Its argument is a fixed template string
    # built only from a hardcoded 3-entry repo list (never user input), and
    # its own comment documents why the quoting is deliberate. Any other
    # instance, or a change to this one's shape, is the failure this guards.
    known_bash_c = {
        'out=$(timeout "$GIT_TIMEOUT" bash -c "$(drift_probe_cmd "$local_path")" 2>&1); rc=$?'
    }
    bash_c_lines = [ln.strip() for ln in src.splitlines()
                    if re.search(r'(bash|sh)\s+-c\s+"\$', ln)]
    if set(bash_c_lines) - known_bash_c:
        failures.append('unexpected `bash -c "$...` / `sh -c "$...` '
                         f"free-form-shell shape: {bash_c_lines}")

    # unquoted $@ reaching ssh — never allowlisted, this script has none.
    for lineno, ln in enumerate(src.splitlines(), start=1):
        if "ssh" in ln and re.search(r'(?<!")\$@(?!")', ln):
            failures.append(f"line {lineno}: unquoted $@ reaching ssh: {ln.strip()}")

    total = 3
    passed = total if not failures else 0
    return total, passed, failures


# =============================================================================
# 3. Tier B double gate — refuse without --why (exit 64), default to
#    dry-run without --confirm (prints the plan, executes nothing).
# =============================================================================

TIER_B_VERBS = [
    dict(name="uk-sync", no_why=["uk-sync"], why_args=["uk-sync"],
         mutating_substr="sync.py"),
    dict(name="restart-kuma", no_why=["restart-kuma"], why_args=["restart-kuma"],
         mutating_substr="docker restart uptime-kuma"),
    dict(name="restart",
         no_why=["restart", "homelab", "known-container"],
         why_args=["restart", "homelab", "known-container"],
         mutating_substr="docker restart known-container"),
    dict(name="redeploy",
         no_why=["redeploy", "homelab", "homelab"],
         why_args=["redeploy", "homelab", "homelab"],
         mutating_substr="docker compose up"),
    dict(name="cron-rerun",
         no_why=["cron-rerun", "vpn-watchdog"],
         why_args=["cron-rerun", "vpn-watchdog"],
         mutating_substr="vpn-watchdog.sh"),
    dict(name="devhost-health", no_why=["devhost-health"],
         why_args=["devhost-health"], mutating_substr="devhost-health-check.sh"),
    dict(name="launchd-repair",
         no_why=["launchd-repair", "com.jkrumm.sideclaw"],
         why_args=["launchd-repair", "com.jkrumm.sideclaw"],
         mutating_substr="launchctl bootstrap"),
]


def test_tier_b_double_gate(h: Harness):
    failures = []
    total = passed = 0

    for spec in TIER_B_VERBS:
        name = spec["name"]

        # (a) refuse without --why, before ever touching a remote.
        total += 1
        ssh_log, curl_log, lc_log = h.new_log("ssh"), h.new_log("curl"), h.new_log("lc")
        proc = h.run(spec["no_why"], env_extra={
            "OPS_TEST_SSH_LOG": str(ssh_log),
            "OPS_TEST_CURL_LOG": str(curl_log),
            "OPS_TEST_LAUNCHCTL_LOG": str(lc_log),
        })
        ok = proc.returncode == 64 and "--why" in (proc.stdout + proc.stderr)
        for log in (ssh_log, curl_log, lc_log):
            if _log_text(log).strip():
                ok = False
        if ok:
            passed += 1
        else:
            failures.append(
                f"{name}: missing --why did not cleanly refuse before any "
                f"remote call (rc={proc.returncode}, stdout={proc.stdout[:200]!r})")

        args = spec["why_args"] + ["--why", "regression test"]

        # (b) default dry-run, human mode: prints the plan, runs nothing.
        total += 1
        ssh_log, curl_log, lc_log = h.new_log("ssh"), h.new_log("curl"), h.new_log("lc")
        proc = h.run(args, env_extra={
            "OPS_TEST_SSH_LOG": str(ssh_log),
            "OPS_TEST_CURL_LOG": str(curl_log),
            "OPS_TEST_LAUNCHCTL_LOG": str(lc_log),
        })
        ok = (proc.returncode == 0 and "DRY RUN" in proc.stdout
              and spec["mutating_substr"] in proc.stdout)
        for log in (ssh_log, curl_log, lc_log):
            if spec["mutating_substr"] in _log_text(log):
                ok = False
        if ok:
            passed += 1
        else:
            failures.append(
                f"{name}: human dry-run did not print-and-not-run cleanly "
                f"(rc={proc.returncode}, stdout={proc.stdout[:300]!r})")

        # (b) default dry-run, --json mode: same guarantee, structured.
        total += 1
        ssh_log, curl_log, lc_log = h.new_log("ssh"), h.new_log("curl"), h.new_log("lc")
        proc = h.run(args + ["--json"], env_extra={
            "OPS_TEST_SSH_LOG": str(ssh_log),
            "OPS_TEST_CURL_LOG": str(curl_log),
            "OPS_TEST_LAUNCHCTL_LOG": str(lc_log),
        })
        ok = proc.returncode == 0
        try:
            data = json.loads(proc.stdout.strip())
        except json.JSONDecodeError as exc:
            ok = False
            data = None
            failures.append(f"{name}: dry-run --json is not one parseable "
                             f"object: {exc}")
        if data is not None:
            if not (data.get("dryRun") is True and data.get("confirmed") is False):
                ok = False
            if spec["mutating_substr"] not in json.dumps(data.get("commands", [])):
                ok = False
        for log in (ssh_log, curl_log, lc_log):
            if spec["mutating_substr"] in _log_text(log):
                ok = False
        if ok:
            passed += 1
        else:
            failures.append(
                f"{name}: --json dry-run contract violated "
                f"(rc={proc.returncode}, stdout={proc.stdout[:300]!r})")

    return total, passed, failures


# =============================================================================
# 4. Unknown verb -> exit 64, no fallthrough to a shell.
# =============================================================================

def test_unknown_verb(h: Harness):
    failures = []
    total = passed = 0
    for verb in ["totally-bogus-verb", "; rm -rf /tmp/x", "$(whoami)"]:
        total += 1
        ssh_log, curl_log = h.new_log("ssh"), h.new_log("curl")
        proc = h.run([verb], env_extra={
            "OPS_TEST_SSH_LOG": str(ssh_log), "OPS_TEST_CURL_LOG": str(curl_log)})
        ok = proc.returncode == 64 and "unknown verb" in (proc.stdout + proc.stderr)
        if _log_text(ssh_log).strip() or _log_text(curl_log).strip():
            ok = False
        if ok:
            passed += 1
        else:
            failures.append(f"verb={verb!r}: expected a clean usage error, got "
                             f"rc={proc.returncode} stdout={proc.stdout[:200]!r}")
    return total, passed, failures


# =============================================================================
# 5. --json contract: exactly one parseable object, success and failure
#    paths alike, exit code preserved.
# =============================================================================

def test_json_contract(h: Harness):
    failures = []
    total = passed = 0

    cases = [
        (["containers", "homelab", "--json"], {}, 0, True),
        (["containers", "bogus-host", "--json"], {}, 64, False),
        (["bogus-verb-xyz", "--json"], {}, 64, False),
        (["uk-sync", "--why", "test", "--json"], {
            "OPS_TEST_SSH_EXIT_HOMELAB": "1",
            "OPS_TEST_SSH_OUTPUT_HOMELAB":
                "could not find item some-item in vault XXXX\n",
        }, 2, False),
    ]
    for args, env_extra, expect_rc, expect_ok in cases:
        total += 1
        proc = h.run(args, env_extra=env_extra)
        try:
            data = json.loads(proc.stdout.strip())
        except json.JSONDecodeError as exc:
            failures.append(f"{args}: stdout is not exactly one JSON object: "
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
            failures.append(
                f"{args}: rc={proc.returncode} (want {expect_rc}), "
                f"ok={data.get('ok')!r} (want {expect_ok}), data={data!r}")
    return total, passed, failures


# =============================================================================
# 6. Audit log — exactly one line per invocation, expected fields, secrets
#    never land in it unredacted.
# =============================================================================

def test_audit_log(h: Harness):
    failures = []
    total = passed = 0

    total += 1
    audit_log = h.new_log("audit-single")
    proc = h.run(["status"], audit_log=audit_log)
    lines = _log_text(audit_log).splitlines()
    fields = ["verb=", "mode=", "args=", "target=", "rc=", "dur=", "why="]
    if len(lines) == 1 and all(f in lines[0] for f in fields):
        passed += 1
    else:
        failures.append(f"expected exactly 1 audit line with all fields, got "
                         f"{lines!r} (rc={proc.returncode})")

    total += 1
    secret_like = "XyZ9aB8cD7eF6gH5iJ4kL3mN2"  # shape of a token, not a real one
    audit_log = h.new_log("audit-redact")
    h.run(["restart-kuma", "--why", secret_like], audit_log=audit_log)
    text = _log_text(audit_log)
    if secret_like not in text and "<redacted>" in text:
        passed += 1
    else:
        failures.append("a token-shaped --why value was not redacted in the "
                         f"audit log: {text!r}")

    return total, passed, failures


# =============================================================================
# 7. launchd-repair label allowlist — ai.hermes.gateway (and anything else
#    off the fixed list) is rejected before real launchctl is ever consulted.
# =============================================================================

def test_launchd_label_allowlist(h: Harness):
    failures = []
    total = passed = 0
    for label in ["ai.hermes.gateway", "com.jkrumm.totally-bogus-label"]:
        total += 1
        lc_log = h.new_log("lc")
        proc = h.run(["launchd-repair", label, "--why", "test"],
                      env_extra={"OPS_TEST_LAUNCHCTL_LOG": str(lc_log)})
        ok = proc.returncode == 64 and not _log_text(lc_log).strip()
        if ok:
            passed += 1
        else:
            failures.append(f"label={label!r}: expected exit 64 with no "
                             f"launchctl call, got rc={proc.returncode} "
                             f"launchctl_log={_log_text(lc_log)!r}")
    return total, passed, failures


# =============================================================================
# 8. uk-sync refuses when env-check fails — the property that makes the
#    2026-08-01 corruption unreachable through this script. Verified by
#    forcing the env-check failure path via the stubbed ssh, never by
#    touching the real environment.
# =============================================================================

def test_uk_sync_env_check_gate(h: Harness):
    failures = []
    total = passed = 0

    # Control: a healthy env-check reaches the dry-run print.
    total += 1
    ssh_log = h.new_log("ssh")
    proc = h.run(["uk-sync", "--why", "control"],
                  env_extra={"OPS_TEST_SSH_LOG": str(ssh_log)})
    if proc.returncode == 0 and "sync.py" in proc.stdout:
        passed += 1
    else:
        failures.append("control: uk-sync with a healthy env-check did not "
                         f"reach the dry-run print (rc={proc.returncode}, "
                         f"stdout={proc.stdout[:300]!r})")

    # The property under test: env-check fails -> uk-sync refuses, and the
    # mutating sync.py command is never sent to ssh.
    total += 1
    ssh_log = h.new_log("ssh")
    proc = h.run(
        ["uk-sync", "--why", "test regression"],
        env_extra={
            "OPS_TEST_SSH_LOG": str(ssh_log),
            "OPS_TEST_SSH_EXIT_HOMELAB": "1",
            "OPS_TEST_SSH_OUTPUT_HOMELAB":
                "could not find item op-dangling-item in vault XXXX\n",
        },
    )
    ok = proc.returncode == 2 and "env-check failed" in (proc.stdout + proc.stderr)
    if ok:
        for line in _log_text(ssh_log).splitlines():
            argv = json.loads(line)
            if argv and "sync.py" in argv[-1]:
                ok = False
    if ok:
        passed += 1
    else:
        failures.append("uk-sync did not refuse cleanly on a failed env-check "
                         f"(rc={proc.returncode}, stdout={proc.stdout[:300]!r})")

    return total, passed, failures


# =============================================================================

def main() -> int:
    h = Harness()
    try:
        groups = [
            ("1. argument bounding", test_argument_bounding(h)),
            ("2. no free-form surface", test_no_freeform_surface()),
            ("3. Tier B double gate", test_tier_b_double_gate(h)),
            ("4. unknown verb", test_unknown_verb(h)),
            ("5. --json contract", test_json_contract(h)),
            ("6. audit log", test_audit_log(h)),
            ("7. launchd-repair label allowlist", test_launchd_label_allowlist(h)),
            ("8. uk-sync env-check gate", test_uk_sync_env_check_gate(h)),
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
