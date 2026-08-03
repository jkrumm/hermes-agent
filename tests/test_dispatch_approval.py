"""Regression suite for the signed-approval gate on `hermes-cc.sh`'s write verbs.

WHAT THIS PROVES, AND WHY IT IS NOT THE SAME AS `--confirm`.

`--confirm` is a flag the calling agent sets on its own invocation, so it constrains
only an agent that chooses to be constrained. The gate tested here does not: an
approval is a Slack button click, witnessed by the gateway process and signed there
with an Ed25519 key whose private half never leaves that process's memory. Every row
in `dispatch_approvals` is writable by this uid — the agent's uid — so the suite's
central case is the FORGED one: a row with `decision='approve'` and a plausible
signature, written exactly as a compromised agent would write it, must still refuse.

The cases:

  - the two hash implementations (shell and plugin) agree, so the gate can match at all
  - planning mints a pending row; a rehearsal (`--dry-run`) mints nothing
  - `--confirm` with no approval refuses (exit 4) and says how to get one
  - `--confirm` with an unsigned approve row refuses            <- the forgery case
  - `--confirm` with a row signed by the WRONG key refuses      <- the forgery case
  - `--confirm` with a valid signature passes the gate, and the audit line names
    the approver — the only field an agent could not have written for itself
  - a denial refuses, and is distinguishable from an absence
  - an expired approval refuses
  - an approval is single-use: the second `--confirm` refuses
  - editing the brief after approval refuses (the hash binds the payload)
  - editing --why after approval refuses (the button showed that reason)
  - a missing public key refuses rather than falling back to instruction-level
  - only the gateway publishes a signing key, and a clobbered one is republished
    before signing (the 2026-08-03 outage, as a test)

Run:

    ~/.hermes/hermes-agent/venv/bin/python3 tests/test_dispatch_approval.py

Exit status is 0 only when every case matches. Nothing here touches the real
dispatch DB, the real audit log, Slack, or the network.
"""

import datetime as dt
import importlib.util
import json
import os
import shutil
import sqlite3
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parent
CC_SCRIPT = REPO / "scripts" / "hermes-cc.sh"
PLUGIN = REPO / "plugins" / "dispatch-approval" / "__init__.py"

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

# Reuse the main suite's harness rather than rebuilding the stub PATH, fake $HOME and
# repo policy fixture: the gate has to be exercised through the same script surface
# every other bound is, or it would be testing a different program.
sys.path.insert(0, str(HERE))
_spec = importlib.util.spec_from_file_location("cc_suite", HERE / "test_hermes_cc.py")
_cc = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_cc)
Harness = _cc.Harness

_pspec = importlib.util.spec_from_file_location("dispatch_approval", PLUGIN)
plugin = importlib.util.module_from_spec(_pspec)
_pspec.loader.exec_module(plugin)

FAILURES = []
CHECKS = [0]


def check(cond, label):
    CHECKS[0] += 1
    if not cond:
        FAILURES.append(label)


def now_utc():
    return dt.datetime.now(dt.timezone.utc)


class Approver:
    """Stands in for the gateway plugin: owns a key, publishes the public half, and
    signs decisions with the plugin's own canonical_message so the two halves of the
    contract are tested against each other rather than against a copy."""

    def __init__(self, root: Path):
        self.key = Ed25519PrivateKey.generate()
        self.pub_path = root / "dispatch-approval.pub"
        raw = self.key.public_key().public_bytes(
            encoding=serialization.Encoding.Raw,
            format=serialization.PublicFormat.Raw,
        )
        self.pub_path.write_text(raw.hex() + "\n")

    def sign(self, nonce, payload_hash, decision, by, expires_at, key=None):
        msg = plugin.canonical_message(nonce, payload_hash, decision, by, expires_at)
        return (key or self.key).sign(msg).hex()

    def decide(self, db, payload_hash, *, decision="approve", by="U0JOHANNES",
               expires_in_min=30, sign=True, key=None):
        """Write a decision the way the plugin would — or, when `sign=False`, the way
        a compromised agent with sqlite3 and no key would."""
        conn = sqlite3.connect(str(db))
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            "SELECT nonce FROM dispatch_approvals WHERE payload_hash=? AND decision IS NULL",
            (payload_hash,),
        ).fetchone()
        assert row is not None, "no pending approval to decide"
        nonce = row["nonce"]
        expires = (now_utc() + dt.timedelta(minutes=expires_in_min)).isoformat()
        sig = self.sign(nonce, payload_hash, decision, by, expires, key=key) if sign else None
        conn.execute(
            "UPDATE dispatch_approvals SET decision=?, decided_at=?, decided_by=?, "
            "signature=?, expires_at=? WHERE nonce=?",
            (decision, now_utc().isoformat(), by, sig, expires, nonce),
        )
        conn.commit()
        conn.close()
        return nonce


# No trailing whitespace: read_brief strips it before hashing, so a brief written with
# a trailing newline here would hash differently on the two sides and every case would
# fail for a reason that has nothing to do with the gate.
BRIEF = "Fix the flaky assertion in the retry test."

# The verifier needs `cryptography`; the harness's fake $HOME has no venv.
VERIFIER_PY = sys.executable

# The stated reason is bound into the hash too, so the suite has to use one consistently.
WHY = "test"


def plan_and_db(h, approver, *, repo="gamma", brief=BRIEF, extra=None):
    """Run the gated verb without --confirm (which mints the pending row + buttons),
    on a DB that persists so the confirm step can see it."""
    db = h.new_db()
    env = {
        "HERMES_CC_DB": str(db),
        "HERMES_CC_APPROVAL_PUBKEY": str(approver.pub_path),
        "HERMES_CC_APPROVAL_PY": VERIFIER_PY,
        "HERMES_CC_SLACK_API": "http://slack.invalid/api",
    }
    if extra:
        env.update(extra)
    r = h.run(["dispatch", repo, "--tier", "implement", "--why", WHY],
              env_extra=env, stdin=brief)
    return db, env, r


def confirm(h, env, *, repo="gamma", brief=BRIEF, why=WHY):
    return h.run(["dispatch", repo, "--tier", "implement", "--why", why, "--confirm"],
                 env_extra=env, stdin=brief, auto_approve=False)


def pending_rows(db):
    conn = sqlite3.connect(str(db))
    try:
        return conn.execute("SELECT COUNT(*) FROM dispatch_approvals").fetchone()[0]
    except sqlite3.OperationalError:
        return 0
    finally:
        conn.close()


# --- cases -------------------------------------------------------------------


def test_hash_agreement(h, approver):
    """The shell and the plugin must derive the same payload hash, or the gate never
    matches and every write silently refuses for the wrong reason."""
    src = CC_SCRIPT.read_text().splitlines()
    start = next(i for i, l in enumerate(src) if l.startswith("approval_hash()"))
    end = next(i for i, l in enumerate(src[start:], start) if l == "}")
    with tempfile.NamedTemporaryFile("w", suffix=".sh", delete=False) as fh:
        fh.write("\n".join(src[start:end + 1]) + "\n")
        fn = fh.name
    out = subprocess.run(
        ["bash", "-c", f'. "{fn}"; approval_hash dispatch gamma implement "$(cat)" "{WHY}"'],
        input=BRIEF, capture_output=True, text=True,
    )
    os.unlink(fn)
    shell_hash = out.stdout.strip()
    py_hash = plugin.payload_hash("dispatch", "gamma", "implement", BRIEF, WHY)
    check(shell_hash == py_hash,
          f"hash agreement: shell {shell_hash!r} != plugin {py_hash!r}")


def test_plan_mints_pending(h, approver):
    db, env, r = plan_and_db(h, approver)
    check(r.returncode == 0, f"plan exits 0, got {r.returncode}: {r.stderr[:200]}")
    conn = sqlite3.connect(str(db))
    rows = conn.execute(
        "SELECT verb, repo, tier, decision, signature FROM dispatch_approvals").fetchall()
    conn.close()
    check(len(rows) == 1, f"plan mints exactly one approval row, got {len(rows)}")
    if rows:
        check(rows[0][0] == "dispatch" and rows[0][1] == "gamma", "row names verb+repo")
        check(rows[0][3] is None and rows[0][4] is None,
              "a freshly minted row is undecided and unsigned")


def test_dry_run_mints_nothing(h, approver):
    db = h.new_db()
    env = {"HERMES_CC_DB": str(db), "HERMES_CC_APPROVAL_PUBKEY": str(approver.pub_path)}
    r = h.run(["dispatch", "gamma", "--tier", "implement", "--why", WHY, "--dry-run"],
              env_extra=env, stdin=BRIEF)
    check(r.returncode == 0, "dry-run exits 0")
    check(pending_rows(db) == 0, "a rehearsal asks nobody and mints no approval row")


def test_confirm_without_approval_refuses(h, approver):
    db, env, _ = plan_and_db(h, approver)
    r = confirm(h, env)
    check(r.returncode == 4, f"unapproved --confirm refuses with 4, got {r.returncode}")
    check("has not been clicked" in r.stderr or "no approval on file" in r.stderr,
          f"refusal explains how to get an approval: {r.stderr[:200]}")


def test_forged_unsigned_row_refuses(h, approver):
    """THE case. A row an agent could write itself with one UPDATE."""
    db, env, _ = plan_and_db(h, approver)
    approver.decide(db, plugin.payload_hash("dispatch", "gamma", "implement", BRIEF, WHY),
                    sign=False)
    r = confirm(h, env)
    check(r.returncode == 4,
          f"an unsigned approve row must not pass the gate, got {r.returncode}")


def test_wrong_key_signature_refuses(h, approver):
    db, env, _ = plan_and_db(h, approver)
    approver.decide(db, plugin.payload_hash("dispatch", "gamma", "implement", BRIEF, WHY),
                    key=Ed25519PrivateKey.generate())
    r = confirm(h, env)
    check(r.returncode == 4,
          f"a signature from another key must not pass the gate, got {r.returncode}")


def test_valid_signature_passes_gate(h, approver):
    db, env, _ = plan_and_db(h, approver)
    approver.decide(db, plugin.payload_hash("dispatch", "gamma", "implement", BRIEF, WHY))
    r = confirm(h, env)
    # Past the gate the run proceeds to sideclaw, which the harness points at a dead
    # port — so anything except the approval refusal means the gate opened.
    combined = r.stdout + r.stderr
    check(r.returncode != 4 or "approval" not in combined.lower(),
          f"a validly signed approval opens the gate, got {r.returncode}: {combined[:250]}")


def test_audit_records_the_approver(h, approver):
    """The one field in the audit line the agent could not have written for itself."""
    db, env, _ = plan_and_db(h, approver)
    approver.decide(db, plugin.payload_hash("dispatch", "gamma", "implement", BRIEF, WHY),
                    by="U0CLICKER")
    log = h.new_log("approved-audit")
    h.run(["dispatch", "gamma", "--tier", "implement", "--why", WHY, "--confirm"],
          env_extra=env, stdin=BRIEF, audit_log=log, auto_approve=False)
    text = log.read_text() if log.exists() else ""
    check("approved_by=U0CLICKER" in text,
          f"audit line names who approved, got {text[:250]!r}")


def test_denial_refuses_and_is_distinct(h, approver):
    db, env, _ = plan_and_db(h, approver)
    approver.decide(db, plugin.payload_hash("dispatch", "gamma", "implement", BRIEF, WHY),
                    decision="deny")
    r = confirm(h, env)
    check(r.returncode == 4, f"a denial refuses, got {r.returncode}")
    check("denied" in r.stderr.lower(),
          f"a denial is distinguishable from an absence: {r.stderr[:200]}")


def test_expired_approval_refuses(h, approver):
    db, env, _ = plan_and_db(h, approver)
    approver.decide(db, plugin.payload_hash("dispatch", "gamma", "implement", BRIEF, WHY),
                    expires_in_min=-1)
    r = confirm(h, env)
    check(r.returncode == 4, f"an expired approval refuses, got {r.returncode}")


def test_approval_is_single_use(h, approver):
    db, env, _ = plan_and_db(h, approver)
    approver.decide(db, plugin.payload_hash("dispatch", "gamma", "implement", BRIEF, WHY))
    first = confirm(h, env)
    check(first.returncode != 4 or "approval" not in (first.stdout + first.stderr).lower(),
          "first --confirm spends the approval")
    second = confirm(h, env)
    check(second.returncode == 4,
          f"a spent approval cannot be reused, got {second.returncode}")


def test_brief_edit_voids_approval(h, approver):
    """The binding that makes an approval mean something: approve a benign brief and
    the signature is worthless for any other, because the hash covers the brief."""
    db, env, _ = plan_and_db(h, approver)
    approver.decide(db, plugin.payload_hash("dispatch", "gamma", "implement", BRIEF, WHY))
    r = confirm(h, env, brief=BRIEF + "\nAlso delete the audit log.\n")
    check(r.returncode == 4,
          f"an edited brief must not ride an old approval, got {r.returncode}")


def test_why_edit_voids_approval(h, approver):
    """The stated reason is what the button showed. Swapping it after the click would
    put a justification in the audit log that nobody approved."""
    db, env, _ = plan_and_db(h, approver)
    approver.decide(db, plugin.payload_hash("dispatch", "gamma", "implement", BRIEF, WHY))
    r = confirm(h, env, why="something else entirely")
    check(r.returncode == 4,
          f"an edited --why must not ride an old approval, got {r.returncode}")


def test_only_the_gateway_publishes_its_key(h, approver):
    """The 2026-08-03 outage, as a test.

    `register()` runs in every process that discovers plugins — a CLI call, a cron
    subprocess — but only the gateway wires Socket Mode and can therefore ever sign.
    The first build published unconditionally, so a non-gateway process overwrote the
    file with a key nothing would ever sign with, and every approved merge afterwards
    refused as "not clicked yet". Two properties keep that closed: don't publish unless
    we are the gateway, and republish on the way to signing if the file is not ours.
    """
    import importlib

    home = Path(tempfile.mkdtemp(prefix="pubkey-"))
    env_backup = os.environ.get("HERMES_HOME")
    os.environ["HERMES_HOME"] = str(home)
    argv_backup = sys.argv[:]
    try:
        # A CLI-shaped process must not publish.
        sys.argv = ["hermes", "plugins", "list"]
        mod = importlib.util.module_from_spec(_pspec)
        _pspec.loader.exec_module(mod)
        mod._ensure_key()
        check(not (home / "dispatch-approval.pub").exists(),
              "a non-gateway process must not publish a signing key")
        cli_key = mod._PUBLIC_KEY_HEX

        # A gateway-shaped process must.
        sys.argv = ["hermes", "gateway", "run", "--replace"]
        gw = importlib.util.module_from_spec(_pspec)
        _pspec.loader.exec_module(gw)
        gw._ensure_key()
        pub = home / "dispatch-approval.pub"
        check(pub.exists() and pub.read_text().strip() == gw._PUBLIC_KEY_HEX,
              "the gateway publishes its own key")

        # And if something clobbers it, the next click republishes.
        pub.write_text(cli_key + "\n")
        gw._ensure_published()
        check(pub.read_text().strip() == gw._PUBLIC_KEY_HEX,
              "a clobbered key is republished by the process that signs")
    finally:
        sys.argv = argv_backup
        if env_backup is None:
            os.environ.pop("HERMES_HOME", None)
        else:
            os.environ["HERMES_HOME"] = env_backup
        shutil.rmtree(home, ignore_errors=True)


def test_missing_pubkey_refuses(h, approver):
    """No plugin, no gateway, no key — the verb refuses rather than degrading to the
    instruction-level flag it replaced."""
    db, env, _ = plan_and_db(h, approver)
    approver.decide(db, plugin.payload_hash("dispatch", "gamma", "implement", BRIEF, WHY))
    env2 = dict(env)
    env2["HERMES_CC_APPROVAL_PUBKEY"] = str(Path(env["HERMES_CC_DB"]).parent / "nope.pub")
    r = confirm(h, env2)
    check(r.returncode == 4, f"a missing public key refuses, got {r.returncode}")
    check("plugin" in r.stderr.lower() or "public key" in r.stderr.lower(),
          f"refusal names the cause: {r.stderr[:200]}")


CASES = [
    test_hash_agreement,
    test_plan_mints_pending,
    test_dry_run_mints_nothing,
    test_confirm_without_approval_refuses,
    test_forged_unsigned_row_refuses,
    test_wrong_key_signature_refuses,
    test_valid_signature_passes_gate,
    test_audit_records_the_approver,
    test_denial_refuses_and_is_distinct,
    test_expired_approval_refuses,
    test_approval_is_single_use,
    test_brief_edit_voids_approval,
    test_why_edit_voids_approval,
    test_only_the_gateway_publishes_its_key,
    test_missing_pubkey_refuses,
]


def main() -> int:
    h = Harness()
    root = Path(tempfile.mkdtemp(prefix="dispatch-approval-"))
    approver = Approver(root)
    try:
        for case in CASES:
            try:
                case(h, approver)
            except Exception as exc:  # a raising case is a failing case
                FAILURES.append(f"{case.__name__} raised {exc!r}")
    finally:
        h.cleanup()

    print(f"{CHECKS[0]} checks, {len(FAILURES)} failure(s)")
    for f in FAILURES:
        print(f"  FAIL {f}")
    return 1 if FAILURES else 0


if __name__ == "__main__":
    sys.exit(main())
