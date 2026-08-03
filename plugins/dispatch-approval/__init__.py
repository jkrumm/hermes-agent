"""Sign dispatch-bridge approvals that arrive as Slack button clicks.

WHY THIS EXISTS, AND WHY A SIGNATURE RATHER THAN A FLAG.

`hermes-cc.sh`'s `--confirm` is a flag on the same invocation, supplied by the same
agent it constrains — the script's own header says so. Moving the gate to a Slack
button does not by itself fix that: the gateway, the script and the agent's terminal
tool all run as the same uid against the same `watchdog.db`, so an agent that wanted
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
"""

from __future__ import annotations

import datetime as dt
import hashlib
import json
import logging
import os
import sqlite3
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


def _hermes_home() -> Path:
    try:
        from hermes_cli.config import get_hermes_home  # type: ignore

        return Path(get_hermes_home())
    except Exception:
        return Path(os.environ.get("HERMES_HOME", str(Path.home() / ".hermes")))


def _db_path() -> Path:
    """The dispatch bridge's store. `hermes-cc.sh` owns this file; we only ever
    UPDATE a row it already INSERTed, and never create the table."""
    override = os.environ.get("HERMES_CC_DB")
    if override:
        return Path(override)
    return _hermes_home() / "watchdog.db"


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


def _ensure_key() -> None:
    """Mint the keypair and publish the public half. Called once, at register()."""
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

    # Written atomically: hermes-cc.sh may read this file at any moment, and a
    # half-written key would fail verification in a way that looks like tampering
    # rather than like a race.
    path = _hermes_home() / _PUBKEY_FILENAME
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".pub.tmp")
    tmp.write_text(_PUBLIC_KEY_HEX + "\n", encoding="utf-8")
    os.chmod(tmp, 0o644)
    os.replace(tmp, path)
    logger.info("[dispatch-approval] signing key minted, public half at %s", path)


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


def _record_decision(nonce: str, decision: str, decided_by: str) -> Optional[dict]:
    """Write the signed decision onto the pending row.

    Returns the row's public fields on success, None if there was nothing to decide.
    The UPDATE is guarded on `decision IS NULL`, so a second click — or a click racing
    another — changes nothing and reports as already-decided.
    """
    db = _db_path()
    if not db.exists():
        logger.warning("[dispatch-approval] no dispatch db at %s", db)
        return None

    conn = sqlite3.connect(str(db))
    conn.row_factory = sqlite3.Row
    try:
        row = conn.execute(
            "SELECT nonce, repo, tier, verb, payload_hash, expires_at, decision "
            "FROM dispatch_approvals WHERE nonce = ?",
            (nonce,),
        ).fetchone()
        if row is None:
            logger.warning("[dispatch-approval] no pending approval for nonce %s", nonce)
            return None
        if row["decision"] is not None:
            return {"already": True, "decision": row["decision"], "repo": row["repo"],
                    "tier": row["tier"], "verb": row["verb"]}

        now = dt.datetime.now(dt.timezone.utc).isoformat()
        sig = _sign(nonce, row["payload_hash"], decision, decided_by, row["expires_at"])
        cur = conn.execute(
            "UPDATE dispatch_approvals SET decision = ?, decided_at = ?, decided_by = ?, "
            "signature = ? WHERE nonce = ? AND decision IS NULL",
            (decision, now, decided_by, sig, nonce),
        )
        conn.commit()
        if cur.rowcount == 0:
            return {"already": True, "decision": "?", "repo": row["repo"],
                    "tier": row["tier"], "verb": row["verb"]}
        return {"already": False, "decision": decision, "repo": row["repo"],
                "tier": row["tier"], "verb": row["verb"], "expires_at": row["expires_at"]}
    finally:
        conn.close()


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
                f"Approved by <@{user_id}>. Valid until {result.get('expires_at', '?')}."
            )
        else:
            text = f":x: *Denied* — `{verb}` {tier} on `{repo}`. Denied by <@{user_id}>."
        await _replace_message(response_url, text)
        logger.info(
            "[dispatch-approval] %s %s %s on %s by %s", decision, verb, tier, repo, user_id
        )

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


def payload_hash(verb: str, repo: str, tier: str, body: str, why: str = "") -> str:
    """The binding between an approval and the exact request it approves.

    `body` is the brief for a dispatch and `<job-id>@<head-sha>` for a merge; `why` is
    the stated reason, which is bound because the button message shows it — approving a
    reason that --confirm could then swap would make the audit log record a
    justification nobody saw.

    Kept here next to `canonical_message` so the two halves of the contract live in
    one file; `hermes-cc.sh` reimplements it in five lines of Python and
    `tests/test_dispatch_approval.py` asserts the two agree.
    """
    h = hashlib.sha256()
    for part in (verb, repo, tier, body, why):
        h.update(part.encode("utf-8"))
        h.update(b"\x00")
    return h.hexdigest()
