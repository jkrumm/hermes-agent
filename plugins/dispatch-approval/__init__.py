"""Sign dispatch-bridge approvals that arrive as Slack button clicks.

WHY THIS EXISTS, AND WHY A SIGNATURE RATHER THAN A FLAG.

`hermes-cc.sh`'s `--confirm` is a flag on the same invocation, supplied by the same
agent it constrains — the script's own header says so. Moving the gate to a Slack
button does not by itself fix that: the gateway, the script and the agent's terminal
tool all run as the same uid against the same `warden.db`, so an agent that wanted
to approve its own dispatch could simply UPDATE the row. A button with no signature
buys UX and nothing else.

What the agent cannot do is produce an Ed25519 signature over a key it never sees.
This plugin generates a keypair at gateway startup, keeps the private half in this
process's memory and never writes it anywhere, and publishes only the public half to
``$HERMES_HOME/dispatch-approval.pub``. `hermes-cc.sh` verifies against that file. The
private key is reachable only by attaching a debugger to the gateway process, which is
a different threat entirely from the one this defends against — prompt injection
reaching a brief, which produces *words*, and words cannot mint a signature.

That is the property the whole gate rests on: a Slack interaction payload is not text.
Nothing in the ingestion path — an issue body, a relayed alert, a poisoned README —
can cause one to exist.

RESTART SEMANTICS. A new keypair is minted on every gateway start, so pending
approvals do not survive a restart: their signatures no longer verify and
`hermes-cc.sh` refuses. That is deliberate and fails closed. Approvals are meant to be
spent within minutes; an approval that outlived the process that witnessed the click
would be a worse thing to trust than one that expired.

WHO WRITES THE ROW (2026-09-09). This plugin no longer opens the ledger for writing
at all — both of its connections are `mode=ro`. The decision is signed here and then
*requested* as an `approval_decision` intent through warden's queue
(`warden/scripts/intents.py`), which owns the single UPDATE. DESIGN.md § The ledger
requires one writer process, and a Slack plugin living inside the gateway while
holding a writable handle on the ledger is exactly the "control plane inside the
thing it supervises" coupling the extraction removed. The authority model is
untouched by that move: the private key still exists only in this process's RAM,
still gets minted at startup, still signs a real Slack interaction payload, and
`require_signed_approval()` in `hermes-cc.sh` remains the one and only verifier.
Only the writer moved. The queue deliberately verifies nothing — a forged spool file
cannot mint a signature, so the worst it can do is deny an approval nobody then acts
on, and that is a human noticing nothing happened rather than a merge nobody sanctioned.

APPROVE RUNS THE VERB (2026-09-07). Before, a click only signed the row and then
waited for Hermes to notice and re-run `--confirm` — which it never reliably did, so
approved dispatches sat unspent until they expired. Now the plan branch stores the
exact invocation on the row (`argv_json`, minus --confirm/--wait and minus the
--brief-file/--context-file paths; the brief as `stdin_text`, never argv; the context
as `context_text`, handed back through a private temp file), and the Approve handler
re-runs `hermes-cc.sh <argv> --confirm` in a subprocess. The stored bytes are what the
payload hash binds, so a row edited after the click refuses like any other mismatch,
and a file the agent deleted or rewrote after planning is never consulted — the path
was the TOCTOU. Nothing is bypassed: that subprocess performs the very
same signature verification a hand-typed --confirm does (require_signed_approval —
the row this handler just signed is what it verifies), the recursion guard, the
budget, the audit line. The outcome (job opened / merged / refused) is posted into
the origin thread over the plain Slack Web API (`chat.postMessage`, mirroring
`warden/scripts/slack_client.py` — see `_send_to_origin()`'s own docstring for why
this is a hand copy rather than an import), and the running episode's verdict still
arrives through the sweeper as before.
"""

from __future__ import annotations

import asyncio
import datetime as dt
import hashlib
import json
import logging
import os
import sqlite3
import subprocess
import sys
import tempfile
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Optional

logger = logging.getLogger(__name__)

# The signing key. Module-global, RAM-only, never serialized. See the module docstring.
_SIGNING_KEY: Any = None
_PUBLIC_KEY_HEX: str = ""

# Bump when the canonical string below changes shape. The verifier pins the same
# literal, so an unrecognised version fails verification rather than silently
# validating a differently-framed payload.
_SIG_VERSION = "v1"

APPROVE_ACTION = "hermes_cc_approve"
DENY_ACTION = "hermes_cc_deny"

_PUBKEY_FILENAME = "dispatch-approval.pub"

# The dispatcher the Approve click re-runs. Overridable so the test suite can
# stand in a stub without a gateway.
# hermes-cc.sh moved wholesale into warden (2026-09-10); ~/.hermes/scripts/hermes-cc.sh
# still resolves (whole-dir symlink into hermes-agent/scripts/, now an exec shim), but
# the plugin calls the real script directly rather than bouncing through the shim.
_DEFAULT_CC_SCRIPT = Path.home() / "SourceRoot" / "warden" / "scripts" / "hermes-cc.sh"
# warden's intent queue — the door this plugin requests a ledger change through,
# because it no longer performs one. See `_record_decision`.
_DEFAULT_INTENTS_CLI = Path.home() / "SourceRoot" / "warden" / "scripts" / "intents.py"

# --- Slack delivery of the re-run outcome (mirrors warden/scripts/slack_client.py) --
#
# A hand copy, not an import: this runs inside the gateway process, in this repo,
# and warden's modules are reached by local path within warden only — a plugin
# depending on another repo's file layout is the wrong kind of coupling. Keep this
# in sync with slack_client.py by hand if either changes shape.
_SLACK_POST_URL = "https://slack.com/api/chat.postMessage"
_SECRETS_RUN = Path.home() / ".local" / "bin" / "secrets-run"
_SLACK_TOKEN_REF = "op://hermes/slack/bot-token"
_SLACK_POST_TIMEOUT_S = 15
# An implement episode is submitted in seconds (the wait is the sweeper's); a merge
# talks to GitHub a handful of times. Anything past this is wedged, not slow.
_RUN_TIMEOUT_S = 120
# Spooling one file and draining a handful of them is milliseconds of work against a
# local SQLite file. Anything past this is a locked ledger, not a slow one.
_INTENTS_TIMEOUT_S = 30


def _hermes_home() -> Path:
    try:
        from hermes_cli.config import get_hermes_home  # type: ignore

        return Path(get_hermes_home())
    except Exception:
        return Path(os.environ.get("HERMES_HOME", str(Path.home() / ".hermes")))


def _db_path() -> Path:
    """The dispatch bridge's store. `hermes-cc.sh` owns the tables; warden owns the
    schema and, since Slice 2b, the write — this plugin only ever READS this file,
    read-only, and hands the write to `warden/scripts/intents.py`."""
    override = os.environ.get("HERMES_CC_DB")
    if override:
        return Path(override)
    # Moved to warden with the control plane (2026-09-09). The path still has to
    # follow the ledger even though nothing here writes it: the drain is passed this
    # same path, and a click that spooled against a database nothing reads would look
    # exactly like a click that worked.
    return Path.home() / ".warden" / "warden.db"


def canonical_message(
    nonce: str,
    payload_hash: str,
    decision: str,
    decided_by: str,
    expires_at: str,
) -> bytes:
    """The exact bytes that get signed.

    Every field that the verifier will act on is in here. `payload_hash` is what binds
    an approval to one specific request — approve a benign brief and the signature is
    worthless for any other, because the hash is over the brief itself. `decision` is
    in here so a deny cannot be replayed as an approve by flipping a column.

    `|` is a safe separator because every field is constrained upstream: nonce and
    payload_hash are hex, decision is one of two literals, expires_at is ISO-8601, and
    decided_by is a Slack user id. None of them can contain the separator.
    """
    return "|".join(
        [_SIG_VERSION, nonce, payload_hash, decision, decided_by, expires_at]
    ).encode("utf-8")


def _is_gateway_process() -> bool:
    """Is this the process that will actually receive Slack clicks?

    `register()` runs in every process that discovers plugins, not just the gateway —
    a CLI invocation, a cron subprocess. Only the gateway wires Socket Mode, so only
    the gateway can ever sign anything, and a key published by any other process is a
    key no click will ever match.
    """
    argv = " ".join(sys.argv)
    return "gateway" in argv and ("run" in sys.argv or "start" in sys.argv)


def _publish_public_key() -> None:
    """Write the public half where hermes-cc.sh looks for it.

    Atomic: hermes-cc.sh may read at any moment, and a half-written key fails
    verification in a way that looks like tampering rather than like a race.
    """
    path = _hermes_home() / _PUBKEY_FILENAME
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".pub.tmp")
    tmp.write_text(_PUBLIC_KEY_HEX + "\n", encoding="utf-8")
    os.chmod(tmp, 0o644)
    os.replace(tmp, path)
    logger.info("[dispatch-approval] published public key at %s", path)


def _ensure_published() -> None:
    """Republish if the file on disk is not ours.

    This is the guarantee, and it is deliberately not the argv heuristic above: a
    process that is handling a click IS the gateway, whatever its argv looks like. It
    self-heals the failure this exists because of — on 2026-08-03 a non-gateway process
    minted its own key at startup and overwrote the file, so every signature the real
    gateway produced afterwards verified against the wrong key and every approved
    merge refused as "not clicked yet". Cheap: one small read per click.
    """
    if not _PUBLIC_KEY_HEX:
        return
    path = _hermes_home() / _PUBKEY_FILENAME
    try:
        if path.read_text(encoding="utf-8").strip() == _PUBLIC_KEY_HEX:
            return
    except OSError:
        pass
    logger.warning(
        "[dispatch-approval] published key was not ours (another process overwrote it) "
        "— republishing before signing"
    )
    _publish_public_key()


def _ensure_key() -> None:
    """Mint the keypair. Called once, at register()."""
    global _SIGNING_KEY, _PUBLIC_KEY_HEX
    if _SIGNING_KEY is not None:
        return

    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

    _SIGNING_KEY = Ed25519PrivateKey.generate()
    raw = _SIGNING_KEY.public_key().public_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PublicFormat.Raw,
    )
    _PUBLIC_KEY_HEX = raw.hex()
    logger.info("[dispatch-approval] signing key minted")

    # Publish only from the gateway. Any other process would be handing hermes-cc.sh a
    # key that nothing can ever sign with.
    if _is_gateway_process():
        _publish_public_key()
    else:
        logger.debug("[dispatch-approval] not the gateway — key not published")


def _approver_ids() -> Optional[set]:
    """Optional allowlist of Slack user ids permitted to approve.

    Unset by default, and that is the right default for this workspace: it is a
    single-user Slack, so the property the gate needs is "a human clicked", not "a
    particular human clicked" — and a bot cannot click at all. Set
    HERMES_CC_APPROVER_IDS (comma-separated) to tighten it if the workspace ever
    gains a second member.
    """
    raw = os.environ.get("HERMES_CC_APPROVER_IDS", "").strip()
    if not raw:
        return None
    return {x.strip() for x in raw.split(",") if x.strip()}


def _sign(nonce: str, payload_hash: str, decision: str, decided_by: str, expires_at: str) -> str:
    msg = canonical_message(nonce, payload_hash, decision, decided_by, expires_at)
    return _SIGNING_KEY.sign(msg).hex()


def _read_approval(db: Path, nonce: str) -> Optional[sqlite3.Row]:
    """One approval row, READ-ONLY.

    `mode=ro` is not decoration: it is what makes "this plugin is not a ledger
    writer" a property SQLite enforces on every connection this file opens,
    rather than one the file merely promises. warden's CLAUDE.md states it as a
    rule — read-only means read-only.

    `signature` is selected alongside the fields the caller returns because the
    post-drain read has to tell OUR write from somebody else's; see
    `_record_decision`.
    """
    conn = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    try:
        return conn.execute(
            "SELECT nonce, repo, tier, verb, payload_hash, expires_at, decision, channel, "
            "signature FROM dispatch_approvals WHERE nonce = ?",
            (nonce,),
        ).fetchone()
    finally:
        conn.close()


def _run_intents(args: list[str], stdin_text: Optional[str] = None) -> subprocess.CompletedProcess:
    """One `python3 intents.py …` call.

    `sys.executable`, deliberately, and not a second interpreter constant to keep in
    sync: `intents.py` and the `ledger.py` it loads are pure stdlib, and warden's venv
    is pinned to the same Python version as the gateway's.

    Never raises. A spawn or timeout failure folds into rc=-1 with the reason in
    stderr — exactly like `_run_cc()` — because the caller decides from the ROW and
    not from an exit code.
    """
    cmd = [sys.executable, str(_intents_cli()), *args]
    try:
        return subprocess.run(
            cmd, input=stdin_text or "", capture_output=True, text=True,
            timeout=_INTENTS_TIMEOUT_S, env=_subprocess_env(),
        )
    except (subprocess.TimeoutExpired, OSError, ValueError) as exc:
        return subprocess.CompletedProcess(cmd, -1, "", f"could not run intents.py: {exc}")


def _record_decision(nonce: str, decision: str, decided_by: str) -> Optional[dict]:
    """Sign the pending row's decision here, and let warden's queue write it.

    Returns the row's public fields on success, None if there was nothing to decide —
    the same keys, the same types, the same meaning of None as when this function did
    the UPDATE itself.

    THIS OPENS NO WRITABLE HANDLE ON THE LEDGER. Both reads are `mode=ro`; the write
    is one `approval_decision` intent spooled through `warden/scripts/intents.py`,
    which owns the single guarded UPDATE (`AND decision IS NULL`, so a second click —
    or a click racing another — still changes nothing).

    THE DRAIN IS SYNCHRONOUS, AND THAT CONSTRAINT DECIDED THE WHOLE DESIGN.
    `execute_approved()` re-runs `hermes-cc.sh <argv> --confirm` in a subprocess
    immediately after this click, and `require_signed_approval()` reads the row. If
    the drain were left to warden's 600s loop, the click would appear to do nothing
    for up to ten minutes.

    Nothing about the authority model moved: the key is still RAM-only, the signature
    is still minted here from a real Slack interaction payload, and
    `require_signed_approval()` is still the one verifier. Only the writer moved.
    """
    db = _db_path()
    if not db.exists():
        logger.warning("[dispatch-approval] no dispatch db at %s", db)
        return None

    row = _read_approval(db, nonce)
    if row is None:
        logger.warning("[dispatch-approval] no pending approval for nonce %s", nonce)
        return None
    if row["decision"] is not None:
        return {"already": True, "decision": row["decision"], "repo": row["repo"],
                "tier": row["tier"], "verb": row["verb"]}

    # `payload_hash` and `expires_at` come from the ROW, exactly as they always have.
    # They are what bind an approval to specific bytes and a specific deadline, which
    # is why warden's intents.py refuses both by name if a spool file tries to carry
    # them — the intent below deliberately does not.
    sig = _sign(nonce, row["payload_hash"], decision, decided_by, row["expires_at"])
    intent = {
        "v": 1,
        "kind": "approval_decision",
        "created_at": dt.datetime.now(dt.timezone.utc).isoformat(),
        "source": "dispatch-approval",
        "nonce": nonce,
        "decision": decision,
        "decided_by": decided_by,
        "signature": sig,
    }

    # The intent goes on STDIN, never argv: it carries a signature, and argv crosses a
    # `ps` boundary that anyone logged into this host can read.
    spooled = _run_intents(["--record"], json.dumps(intent))
    if spooled.returncode != 0:
        logger.error("[dispatch-approval] intents --record failed (%s): %s",
                     spooled.returncode, spooled.stderr.strip()[:300])

    drained = _run_intents(["--drain", str(db)])
    if drained.returncode != 0:
        # NOT the success signal for this click, and do not turn it into one:
        # `--drain` exits 1 when ANY file in the spool was rejected, including one
        # some other surface wrote that has nothing to do with this button. The row
        # is the source of truth.
        logger.warning("[dispatch-approval] intents --drain reported a rejection (%s): %s",
                       drained.returncode, drained.stderr.strip()[:300])

    after = _read_approval(db, nonce)
    if after is None or after["decision"] is None:
        # Raise rather than return None. None means "no longer on file", which the
        # click handler renders as ":grey_question: This approval request is no longer
        # on file" — a lie when the row is sitting there undecided. The handler already
        # catches exceptions and renders ":warning: Could not record the decision.",
        # which is the truth.
        raise RuntimeError(
            f"the decision for nonce {nonce} did not reach the ledger — "
            f"intents --record: {spooled.stderr.strip()[:300] or 'ok'} / "
            f"intents --drain: {drained.stderr.strip()[:300] or 'ok'}"
        )

    if after["signature"] != sig:
        # Someone else's click won the race — report THEIR decision, exactly as the
        # old `rowcount == 0` branch did. Ed25519 signing here is deterministic, so
        # two identical clicks by the same user on the same row mint the SAME
        # signature and land in the "we won" branch below instead. That is correct
        # either way — the row says what it says — so nobody needs to "fix" it.
        return {"already": True, "decision": after["decision"], "repo": row["repo"],
                "tier": row["tier"], "verb": row["verb"]}
    return {"already": False, "decision": decision, "repo": row["repo"],
            "tier": row["tier"], "verb": row["verb"], "expires_at": row["expires_at"],
            "channel": row["channel"]}


def _load_invocation(nonce: str) -> Optional[dict]:
    """The stored argv + stdin for a row, or None when the plan predates the
    columns (an approval minted by an older hermes-cc.sh — the click still signs,
    and Hermes runs --confirm the old way)."""
    conn = sqlite3.connect(f"file:{_db_path()}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    try:
        cols = {r[1] for r in conn.execute("PRAGMA table_info(dispatch_approvals)")}
        if "argv_json" not in cols:
            return None
        context_col = "context_text" if "context_text" in cols else "NULL AS context_text"
        row = conn.execute(
            f"SELECT argv_json, stdin_text, {context_col}, channel FROM dispatch_approvals WHERE nonce = ?",
            (nonce,),
        ).fetchone()
    finally:
        conn.close()
    if row is None or not row["argv_json"]:
        return None
    try:
        argv = json.loads(row["argv_json"])
    except (TypeError, ValueError):
        return None
    if not isinstance(argv, list) or not all(isinstance(a, str) for a in argv):
        return None
    return {"argv": argv, "stdin": row["stdin_text"], "context": row["context_text"],
            "channel": row["channel"]}


def _origin_thread(argv: list[str]) -> Optional[str]:
    """--origin-thread <ts> / --origin-thread=<ts> out of the stored argv."""
    for i, a in enumerate(argv):
        if a == "--origin-thread" and i + 1 < len(argv):
            return argv[i + 1]
        if a.startswith("--origin-thread="):
            return a.split("=", 1)[1]
    return None


def _cc_script() -> Path:
    return Path(os.environ.get("HERMES_CC_SCRIPT", str(_DEFAULT_CC_SCRIPT)))


def _resolve_slack_token() -> str:
    """`SLACK_BOT_TOKEN` env first, else `secrets-run read op://hermes/slack/
    bot-token` with a 15s timeout — mirrors warden/scripts/slack_client.py's
    resolve_slack_token() by hand (see the module-level comment above). ""
    on any failure; a missing token is a best-effort delivery failure here,
    never a hard error."""
    val = os.environ.get("SLACK_BOT_TOKEN", "")
    if val:
        return val
    env = os.environ.copy()
    env["PATH"] = "/opt/homebrew/bin:/usr/local/bin:" + env.get("PATH", "/usr/bin:/bin")
    try:
        r = subprocess.run(
            [str(_SECRETS_RUN), "read", _SLACK_TOKEN_REF],
            capture_output=True, text=True, timeout=15, env=env,
        )
    except (OSError, subprocess.SubprocessError):
        return ""
    return r.stdout.strip() if r.returncode == 0 else ""


def _slack_post_message(token: str, channel: str, text: str,
                         thread_ts: Optional[str] = None) -> dict:
    """Blocking `chat.postMessage` — run this under `asyncio.to_thread()`,
    never called directly from an async context (see `_send_to_origin()`).
    Mirrors warden/scripts/slack_client.py's slack_post_message() by hand.
    Returns Slack's own parsed JSON on any completed round-trip (including
    its own `{"ok": false, "error": ...}`), or a synthetic `{"ok": False,
    "error": ...}` on a transport/parse failure — never raises."""
    payload: dict = {"channel": channel, "text": text}
    if thread_ts:
        payload["thread_ts"] = thread_ts
    body = json.dumps(payload).encode()
    req = urllib.request.Request(
        _SLACK_POST_URL, data=body,
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json; charset=utf-8"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=_SLACK_POST_TIMEOUT_S) as resp:
            return json.loads(resp.read().decode())
    except (urllib.error.URLError, urllib.error.HTTPError, json.JSONDecodeError,
            TimeoutError, OSError) as e:
        return {"ok": False, "error": str(e)}


def _intents_cli() -> Path:
    """warden's intent queue CLI. Env-var-first, documented-default-second — the same
    shape `hermes-cc.sh` already uses to reach across into warden (`HERMES_CC_DB`,
    `HERMES_CC_TRIAGE_POLICY_JSON`), so an operator or a test overrides one variable
    and there is no second copy of the path to keep in sync."""
    return Path(os.environ.get("WARDEN_INTENTS_CLI", str(_DEFAULT_INTENTS_CLI)))


def _subprocess_env() -> dict:
    """The gateway's env minus the Claude Code markers hermes-cc.sh's recursion
    guard keys on. The gateway is not a Claude Code session, but a gateway started
    from inside one inherits its markers — and then every click would refuse
    with 'a dispatched episode may never dispatch'."""
    env = dict(os.environ)
    for marker in ("CLAUDECODE", "CLAUDE_CODE_SESSION", "CLAUDE_SESSION_ID", "CLAUDE_ENTRYPOINT"):
        env.pop(marker, None)
    env["PATH"] = "/opt/homebrew/bin:/usr/local/bin:" + env.get("PATH", "/usr/bin:/bin")
    return env


async def _run_cc(argv: list[str], stdin_text: Optional[str],
                  context_text: Optional[str] = None) -> tuple[int, str, str]:
    """`hermes-cc.sh <argv> --confirm`, brief on stdin, the stored context (if any)
    through a 0600 temp file this process owns for the length of the call — the
    script's only context input is a path, and the agent's path is the thing we
    stopped trusting. Never raises: a spawn or timeout failure folds into rc=-1
    with the reason in stderr."""
    cmd = ["bash", str(_cc_script()), *argv]
    context_path: Optional[str] = None
    if context_text is not None:
        fd, context_path = tempfile.mkstemp(prefix="dispatch-approval-ctx-", suffix=".txt")
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(context_text)
        cmd += ["--context-file", context_path]
    cmd.append("--confirm")
    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env=_subprocess_env(),
        )
        out, err = await asyncio.wait_for(
            proc.communicate((stdin_text or "").encode("utf-8")), timeout=_RUN_TIMEOUT_S
        )
        return proc.returncode if proc.returncode is not None else -1, out.decode("utf-8", "replace"), err.decode("utf-8", "replace")
    except asyncio.TimeoutError:
        try:
            proc.kill()
        except Exception:
            pass
        return -1, "", f"hermes-cc.sh did not finish within {_RUN_TIMEOUT_S}s"
    except (OSError, ValueError) as exc:
        return -1, "", f"could not run hermes-cc.sh: {exc}"
    finally:
        if context_path is not None:
            try:
                os.unlink(context_path)
            except OSError:
                pass


def outcome_text(verb: str, repo: str, tier: str, rc: int, stdout: str, stderr: str, user_id: str) -> str:
    """Deterministic one-message summary of the re-run for the origin thread.
    Reads the --json object hermes-cc.sh printed; falls back to stderr."""
    payload: dict = {}
    try:
        payload = json.loads(stdout) if stdout.strip() else {}
    except ValueError:
        payload = {}
    if not isinstance(payload, dict):
        payload = {}
    head = f"`{verb}` {tier} on `{repo}` — approved by <@{user_id}>"
    if rc == 0 and payload.get("ok"):
        if verb == "merge":
            url = payload.get("prUrl") or payload.get("artifactUrl") or ""
            return f":white_check_mark: {head}\nMerged. {url}".rstrip()
        job_id = payload.get("jobId") or "?"
        return (
            f":rocket: {head}\nEpisode opened: job `{job_id}`. It is NOT finished — the "
            f"5-minute sweeper delivers the verdict into this thread."
        )
    reason = (payload.get("error") or stderr.strip() or stdout.strip() or "no detail")[:600]
    code = payload.get("exitCode", rc)
    return f":x: {head}\nDid not run (exit {code}): {reason}"


async def _send_to_origin(channel: Optional[str], thread_ts: Optional[str], text: str) -> None:
    """Same delivery target as dispatch-sweep.py: `slack:<chan>[:<ts>]`, now over
    the plain Slack Web API (`chat.postMessage`) instead of shelling out to
    `hermes send` — that used the gateway's own Slack Socket Mode connection,
    the one piece of infrastructure a signed-approval handler running INSIDE
    the gateway cannot depend on staying up. `_slack_post_message()` is a
    blocking `urllib` call, so it runs under `asyncio.to_thread()` rather than
    on this coroutine's own event loop. Best effort, same as before: a failure
    here is logged and never raised — the click was already spent and the
    verb already ran; only the outcome notice is at stake."""
    if not channel:
        logger.warning("[dispatch-approval] no origin channel on the approval row — outcome not posted")
        return
    token = _resolve_slack_token()
    if not token:
        logger.warning("[dispatch-approval] no Slack token available — outcome not posted")
        return
    try:
        result = await asyncio.to_thread(_slack_post_message, token, channel, text, thread_ts)
        if not result.get("ok"):
            logger.warning("[dispatch-approval] slack post failed: %s", result.get("error"))
    except Exception as exc:  # pragma: no cover - best effort
        logger.warning("[dispatch-approval] could not post the outcome: %s", exc)


async def execute_approved(nonce: str, verb: str, repo: str, tier: str, user_id: str) -> Optional[str]:
    """Run the approved invocation and post its outcome. Returns the posted text
    (None when the row carried no invocation — the pre-2026-09-07 shape)."""
    inv = _load_invocation(nonce)
    if inv is None:
        logger.info("[dispatch-approval] nonce %s has no stored invocation — signed only", nonce)
        return None
    rc, out, err = await _run_cc(inv["argv"], inv["stdin"], inv["context"])
    text = outcome_text(verb, repo, tier, rc, out, err, user_id)
    logger.info("[dispatch-approval] re-ran %s %s on %s: rc=%s", verb, tier, repo, rc)
    await _send_to_origin(inv["channel"], _origin_thread(inv["argv"]), text)
    return text


async def _replace_message(response_url: str, text: str) -> None:
    """Swap the buttons for the outcome, so a stale approval cannot be clicked twice
    and the thread reads as a record afterwards.

    Uses the interaction's `response_url` rather than a Slack client: it needs no
    token, and it is scoped by Slack to exactly this one message.
    """
    if not response_url:
        return
    try:
        import httpx

        async with httpx.AsyncClient(timeout=10) as client:
            await client.post(
                response_url,
                json={"replace_original": True, "text": text, "blocks": [
                    {"type": "section", "text": {"type": "mrkdwn", "text": text}}
                ]},
            )
    except Exception as exc:  # pragma: no cover - best effort
        logger.warning("[dispatch-approval] could not update message: %s", exc)


def _valid_for(expires_at: Optional[str]) -> str:
    """"Valid for another 28 min" beats an ISO timestamp with microseconds on it.

    Nobody reading a phone notification wants to subtract
    2026-08-03T10:18:04.248013+00:00 from the current time in their head.
    """
    if not expires_at:
        return "Spend it soon."
    try:
        exp = dt.datetime.fromisoformat(expires_at)
    except ValueError:
        return "Spend it soon."
    if exp.tzinfo is None:
        exp = exp.replace(tzinfo=dt.timezone.utc)
    mins = int((exp - dt.datetime.now(dt.timezone.utc)).total_seconds() // 60)
    if mins <= 0:
        return "Already expired — re-plan for a fresh one."
    if mins == 1:
        return "Valid for another minute."
    return f"Valid for another {mins} min."


def _make_handler(decision: str):
    async def _handler(ack, body, action) -> None:
        await ack()

        user = (body or {}).get("user", {}) or {}
        user_id = user.get("id", "") or ""
        user_name = user.get("name", "unknown")
        nonce = (action or {}).get("value", "") or ""
        response_url = (body or {}).get("response_url", "") or ""

        # A bot cannot click a button, so this is belt-and-braces: it rejects a
        # workspace/app id shape reaching here through any path that is not a human
        # interaction.
        if not user_id.startswith("U"):
            logger.warning("[dispatch-approval] non-user click ignored: %r", user_id)
            return

        allow = _approver_ids()
        if allow is not None and user_id not in allow:
            logger.warning(
                "[dispatch-approval] unauthorized click by %s (%s)", user_name, user_id
            )
            await _replace_message(response_url, ":no_entry: Not authorized to approve dispatches.")
            return

        if _SIGNING_KEY is None:
            logger.error("[dispatch-approval] no signing key — refusing to record a decision")
            await _replace_message(
                response_url, ":warning: Approval key unavailable — dispatch cannot proceed."
            )
            return

        # A click proves this process is the gateway, so this is the authoritative
        # moment to make sure the published key is ours.
        _ensure_published()

        try:
            result = _record_decision(nonce, decision, user_id)
        except Exception as exc:
            logger.error("[dispatch-approval] could not record decision: %s", exc, exc_info=True)
            await _replace_message(response_url, ":warning: Could not record the decision.")
            return

        if result is None:
            await _replace_message(
                response_url,
                ":grey_question: This approval request is no longer on file (expired or cleared).",
            )
            return

        if result.get("already"):
            await _replace_message(
                response_url,
                f":grey_exclamation: Already {result['decision']}d — no change.",
            )
            return

        verb = result.get("verb", "dispatch")
        repo = result.get("repo", "?")
        tier = result.get("tier", "?")
        if decision == "approve":
            text = (
                f":white_check_mark: *Approved* — `{verb}` {tier} on `{repo}`\n"
                f"Approved by <@{user_id}>. Running it now — the outcome lands in this thread."
            )
        else:
            text = f":x: *Denied* — `{verb}` {tier} on `{repo}`. Denied by <@{user_id}>."
        await _replace_message(response_url, text)
        logger.info(
            "[dispatch-approval] %s %s %s on %s by %s", decision, verb, tier, repo, user_id
        )
        if decision == "approve":
            # Off the click's own task: Slack expects the ack within seconds, the
            # re-run can take a minute (a merge talks to GitHub). Failure is
            # logged and posted, never raised into the gateway.
            async def _run() -> None:
                try:
                    await execute_approved(nonce, verb, repo, tier, user_id)
                except Exception as exc:  # pragma: no cover - never take the gateway down
                    logger.error("[dispatch-approval] executing the approval failed: %s", exc, exc_info=True)
            asyncio.create_task(_run())

    return _handler


def register(ctx) -> None:
    """Plugin entry point — mint the key, wire the two buttons."""
    try:
        _ensure_key()
    except Exception as exc:
        # Fail loudly but do not take the gateway down. hermes-cc.sh refuses every
        # gated verb while the public key is absent, so the consequence of landing
        # here is "no writing dispatches", never "unguarded writing dispatches".
        logger.error(
            "[dispatch-approval] could not mint signing key: %s — gated dispatch verbs "
            "will refuse until this is fixed", exc, exc_info=True,
        )
        return

    ctx.register_slack_action_handler(APPROVE_ACTION, _make_handler("approve"))
    ctx.register_slack_action_handler(DENY_ACTION, _make_handler("deny"))
    logger.info("[dispatch-approval] registered approve/deny handlers")


def payload_hash(verb: str, repo: str, tier: str, body: str, why: str = "",
                 context: str = "") -> str:
    """The binding between an approval and the exact request it approves.

    `body` is the brief for a dispatch and `<job-id>@<head-sha>` for a merge; `why` is
    the stated reason, which is bound because the button message shows it — approving a
    reason that --confirm could then swap would make the audit log record a
    justification nobody saw. `context` is the --context-file bytes (empty when none):
    the plan never shows them and the click replays unattended, so an unbound context
    file was a swap-after-approve hole for whoever could write it — the agent included.

    Kept here next to `canonical_message` so the two halves of the contract live in
    one file; `hermes-cc.sh` (warden/scripts/, since 2026-09-10) reimplements it in
    five lines of Python and `warden/tests/test_dispatch_approval.py` asserts the
    two agree.
    """
    h = hashlib.sha256()
    for part in (verb, repo, tier, body, why, context):
        h.update(part.encode("utf-8"))
        h.update(b"\x00")
    return h.hexdigest()
