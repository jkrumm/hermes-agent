"""Dispatch sweep — the return path that closes a dispatch without a human.

Runs every 5 min as a Hermes `no_agent` cron script, invoked as `python3
<path>` with no args. Under `no_agent`, the script's stdout would normally
BE the delivered message (see cron/scheduler.py) — but this script already
does its own per-dispatch delivery via `hermes send` into each dispatch's own
origin thread, which is a different target per row, not the cron's single
configured target. So production stdout is always empty; every diagnostic
goes to stderr, and empty stdout on the cron path just means "no framework
double-delivery," not "nothing happened."

WHAT IT DOES, one pass: read every dispatch row with `reported_at IS NULL`
(watchdog.db's `dispatches` table, owned by scripts/hermes-cc.sh — see
docs/dispatch-bridge.md § "The dispatch record"). For each, poll sideclaw's
job endpoint. A still-running job is left alone. A terminal job (done,
failed, interrupted) gets folded back into the row (status, verdict_json,
finished_at), then — if the dispatch has an origin_channel — a deterministic,
no-LLM message is composed and sent via `hermes send`, and only a delivery
exit code 0 stamps `reported_at`. A dispatch with no origin_channel (e.g.
opened from a context with no Slack thread to answer into) can never be
delivered anywhere, so it is closed with a sentinel instead of accumulating
as a permanent debt — see UNDELIVERABLE_SENTINEL below.

CRASH SAFETY — read this before changing the write order. The script must be
killable at any instant without losing a debt:
  1. The terminal-status UPDATE (status/verdict_json/finished_at) commits
     BEFORE any delivery attempt. A kill here just means the next sweep
     re-polls a job that's already terminal and re-derives the same update —
     idempotent, no harm.
  2. `reported_at` is stamped ONLY after `hermes send` returns exit code 0,
     in its own commit, immediately. A kill between the send and this commit
     means the next sweep sends the same message again (the row is still
     `reported_at IS NULL`) — a duplicate Slack post, never a lost one.
This is an AT-LEAST-ONCE contract, not exactly-once, by design: the failure
mode this script must never have is a verdict that silently vanishes because
the process died between "sent" and "recorded." An occasional duplicate
message in a thread is a cosmetic annoyance; a lost verdict is the thing
Phase 3 exists to prevent.

WAKE-UP NUDGE. The verdict above is posted via `hermes send`, i.e. as
Hermes's own Slack bot user — and Slack ingest unconditionally drops
Hermes's own messages (echo-loop protection), so nothing wakes the agent
when an episode finishes. For an *actionable* dispatch (done, implement
tier, has an artifact URL, not already merged — see is_actionable()), this
script additionally posts a short nudge through argo's Slack API, which
posts as the HomeLab bot — a different user Hermes does ingest — strictly
AFTER `reported_at` is stamped, and best-effort (its failure never affects
`reported_at` and never raises — see send_nudge()). The nudge body is
restricted to fields the dispatch bridge itself owns (job id, repo, tier,
artifact URL) and never carries episode-authored text — see
build_nudge_body()'s docstring for why that boundary is a security
property, not a style choice.

Source of truth: ~/SourceRoot/hermes-agent/scripts/dispatch-sweep.py
~/.hermes/scripts/ is itself a symlink to this directory (see make setup).
"""

from __future__ import annotations

import datetime as dt
import json
import os
import sqlite3
import subprocess
import sys
import tempfile
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

HERMES_HOME = Path.home() / ".hermes"
DB_PATH = HERMES_HOME / "watchdog.db"

# Same override hermes-cc.sh honors (HERMES_CC_SIDECLAW_BASE / it reads the same
# dispatches table) — localhost, unauthenticated, reachable only from this machine.
SIDECLAW_BASE = os.environ.get("HERMES_CC_SIDECLAW_BASE", "http://localhost:7705")

# `hermes send` reuses the gateway's platform credentials directly — no running
# gateway, no LLM turn. Absolute path (mirrors watchdog-poll.py's SECRETS_RUN
# constant) so this doesn't depend on PATH under the cron's minimal environment.
HERMES_BIN = Path.home() / ".local" / "bin" / "hermes"

SIDECLAW_POLL_TIMEOUT = 15  # seconds; a bare GET against a localhost job server
HERMES_SEND_TIMEOUT = 30    # seconds; shells out to the gateway's platform client

TERMINAL_STATUSES = {"done", "failed", "interrupted"}

# --- Wake-up nudge (argo Slack API) -----------------------------------------
#
# The verdict above is sent via `hermes send`, which posts as Hermes's own
# Slack bot user — and Slack ingest unconditionally drops Hermes's own
# messages (echo-loop protection, independent of allow_bots), so nothing
# wakes the agent when an episode finishes. For an *actionable* dispatch
# (see is_actionable()) we additionally post a short nudge through argo's
# Slack API, which posts as the HomeLab bot — a different user, which Hermes
# DOES ingest — so it can decide whether to call `merge`.
#
# Same API_BASE + same bearer secret (op://common/api/SECRET, env
# HOMELAB_API_KEY) that scripts/briefing-coverage.py and
# scripts/watchdog-poll.py already use; resolve_api_key() below mirrors
# briefing-coverage.py's implementation exactly.
ARGO_API_BASE = "https://argo.jkrumm.com/api"
ARGO_API_KEY_REF = "op://common/api/SECRET"
SECRETS_RUN = Path.home() / ".local" / "bin" / "secrets-run"
ARGO_HTTP_TIMEOUT = 10  # seconds; a bare POST against a remote HTTP API

# A dispatch with no origin_channel was never asked from a Slack thread (e.g.
# opened from a cron context with nothing to answer into) — it can NEVER be
# delivered anywhere, so it must not sit open forever as unpaid debt. Rather
# than adding a new column to a table scripts/hermes-cc.sh owns (the dispatch
# bridge's single-writer-per-table rule — see docs/dispatch-bridge.md §
# "Component split"), this closes the row with a sentinel string in
# `reported_at` instead of a real timestamp. Safe because every reader of that
# column (hermes-cc.sh's `cmd_list`, the schema's own comment) only ever tests
# NULL-ness, never parses the value as a date — and the sentinel is
# self-explanatory if the row is ever inspected directly with sqlite3.
UNDELIVERABLE_SENTINEL = "undeliverable:no-origin-channel"

# Slack mrkdwn block limit is 4000 chars; this leaves headroom for the
# "(message truncated)" suffix itself and any mrkdwn formatting overhead.
BODY_CHAR_LIMIT = 3800
EVIDENCE_CAP = 5

DB_SCHEMA = """
CREATE TABLE IF NOT EXISTS dispatches (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    job_id TEXT NOT NULL UNIQUE,
    tier TEXT NOT NULL,
    repo TEXT NOT NULL,
    brief TEXT NOT NULL,
    why TEXT,
    origin_channel TEXT,
    origin_thread_ts TEXT,
    origin_event_id INTEGER,
    status TEXT NOT NULL,
    verdict_json TEXT,
    artifact_url TEXT,
    created_at TEXT NOT NULL,
    finished_at TEXT,
    reported_at TEXT
);
CREATE INDEX IF NOT EXISTS idx_dispatches_open ON dispatches(status) WHERE reported_at IS NULL;
CREATE INDEX IF NOT EXISTS idx_dispatches_created ON dispatches(created_at);
"""


def db_connect() -> sqlite3.Connection:
    """Same idiom as watchdog-poll.py: sqlite3.connect + Row factory + an
    idempotent executescript. The DDL is copied verbatim from
    scripts/hermes-cc.sh (the table's owner) so this sweeper works even on a
    fresh mini where hermes-cc.sh has never run yet.

    `merged_at` is deliberately outside DB_SCHEMA, same as hermes-cc.sh's own
    `db_py()`: `CREATE TABLE IF NOT EXISTS` is a no-op against a table that
    already exists on this machine, so a column added only to the CREATE
    statement would never appear on a live DB. Additive ALTER TABLE, run
    every connect, mirrors hermes-cc.sh's migration exactly."""
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.executescript(DB_SCHEMA)
    existing_columns = {r[1] for r in conn.execute("PRAGMA table_info(dispatches)")}
    if "merged_at" not in existing_columns:
        conn.execute("ALTER TABLE dispatches ADD COLUMN merged_at TEXT")
        conn.commit()
    return conn


def _apply_db_override(argv: list[str]) -> None:
    """--db PATH, or the HERMES_CC_DB env var hermes-cc.sh already honors
    (same table) — lets a test point this at a throwaway copy of the DB
    without touching the real ~/.hermes/watchdog.db. Mirrors watchdog-poll.py's
    dry-run DB_PATH swap: reassign the module-level global before db_connect()
    ever opens it."""
    global DB_PATH
    if "--db" in argv:
        idx = argv.index("--db")
        if idx + 1 < len(argv):
            DB_PATH = Path(argv[idx + 1]).expanduser()
            return
    env_override = os.environ.get("HERMES_CC_DB")
    if env_override:
        DB_PATH = Path(env_override).expanduser()


def http_get(url: str, timeout: int = SIDECLAW_POLL_TIMEOUT) -> Any:
    req = urllib.request.Request(url)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode())
    except (urllib.error.URLError, urllib.error.HTTPError, json.JSONDecodeError,
            TimeoutError, ValueError) as e:
        return {"_error": str(e)}


def poll_job(job_id: str) -> dict[str, Any] | None:
    """GET the sideclaw job. None on any transport/parse failure or malformed
    envelope — never raises, so one unreachable poll can't take the sweep down."""
    data = http_get(f"{SIDECLAW_BASE}/api/jobs/{job_id}")
    if not isinstance(data, dict) or "_error" in data or not data.get("ok"):
        return None
    job = data.get("job")
    return job if isinstance(job, dict) else None


def http_post_json(url: str, payload: dict[str, Any], headers: dict[str, str],
                    timeout: int = ARGO_HTTP_TIMEOUT) -> Any:
    """POST sibling of http_get — same urllib idiom, same never-raise contract:
    any transport/parse failure folds into a {"_error": ...} dict rather than
    propagating, so a bad nudge attempt can't take the sweep down."""
    data = json.dumps(payload).encode()
    req = urllib.request.Request(
        url, data=data, method="POST",
        headers={"Content-Type": "application/json", **headers},
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode())
    except (urllib.error.URLError, urllib.error.HTTPError, json.JSONDecodeError,
            TimeoutError, ValueError) as e:
        return {"_error": str(e)}


def resolve_api_key() -> str:
    """Mirrors scripts/briefing-coverage.py's resolve_api_key() exactly:
    process env first (HOMELAB_API_KEY), then the secrets-run cache shim with
    a widened PATH (the cache backend needs sops+jq, which the gateway's
    minimal cron PATH may not reach). Returns "" on any failure — a missing
    key is simply a nudge failure, never a hard error for this script."""
    val = os.environ.get("HOMELAB_API_KEY", "")
    if val:
        return val
    env = os.environ.copy()
    env["PATH"] = "/opt/homebrew/bin:/usr/local/bin:" + env.get("PATH", "/usr/bin:/bin")
    try:
        r = subprocess.run(
            [str(SECRETS_RUN), "read", ARGO_API_KEY_REF],
            capture_output=True, text=True, timeout=15, env=env,
        )
    except (OSError, subprocess.SubprocessError):
        return ""
    return r.stdout.strip() if r.returncode == 0 else ""


def is_actionable(*, status: str, tier: str, artifact_url: str | None,
                   merged_at: str | None) -> bool:
    """A dispatch is actionable — i.e. worth waking Hermes for — only when
    ALL of: the job finished successfully (status == "done"), it was an
    implement-tier episode (the only tier that can produce something to
    merge), it actually produced an artifact (a PR URL), and it isn't
    already merged. Anything else (investigate/author tiers, a
    failed/interrupted job, no artifact, already merged) gets today's
    behaviour — verdict only, no nudge."""
    return status == "done" and tier == "implement" and bool(artifact_url) and not merged_at


def build_nudge_body(*, job_id: str, repo: str, tier: str, artifact_url: str) -> str:
    """Deterministic wake-up nudge, in the same voice as format_message().

    SECURITY — do not "improve" this by inlining the episode's summary,
    verdict, recommendation, evidence, or branch. This nudge is ingested by
    Hermes as a live user turn (that is the whole point — it's what wakes
    the agent), so any episode-authored prose in it becomes an instruction
    to an agent that can go on to merge code to master. The episode's
    output is derived from repo content, which can include third-party
    text. Restricting this body to fields the dispatch bridge itself owns
    — job id, repo, tier, artifact URL — keeps that injection surface
    empty by construction. The full verdict (including any episode prose)
    is already in the thread from the prior `hermes send` — Hermes reads
    it there, as a human would, rather than having it re-injected here."""
    job_short = job_id[:8]
    return (
        f":bell: Implement episode finished — {repo}\n"
        f"Unmerged PR: {artifact_url}\n"
        f"Review the verdict above and decide whether to merge — use the `claude-dispatch` "
        f"skill's `merge {job_id}` verb, or explain why not.\n"
        f"_tier {tier} · job `{job_short}`_"
    )


def send_nudge(*, origin_channel: str, origin_thread_ts: str | None, job_id: str,
               repo: str, tier: str, artifact_url: str) -> None:
    """Best-effort wake-up nudge via argo's Slack API (posts as the HomeLab
    bot, which Hermes — unlike its own bot — actually ingests). Must run
    STRICTLY AFTER reported_at is already stamped (see the module
    docstring's crash-safety contract) and must NEVER affect it and NEVER
    raise: at-most-once is the correct trade here, since the worst case is
    "Hermes isn't woken and a human pokes the thread," which is exactly
    today's behaviour. A caught exception is logged to stderr, not
    propagated — this function is called from a context where letting it
    raise would incorrectly look like the sweep itself failed."""
    try:
        api_key = resolve_api_key()
        if not api_key:
            print(
                f"dispatch-sweep: no HOMELAB_API_KEY available, skipping nudge for "
                f"job {job_id} (repo {repo})",
                file=sys.stderr,
            )
            return
        body = build_nudge_body(job_id=job_id, repo=repo, tier=tier, artifact_url=artifact_url)
        if origin_thread_ts:
            url = f"{ARGO_API_BASE}/slack/channels/{origin_channel}/messages/{origin_thread_ts}/reply"
        else:
            url = f"{ARGO_API_BASE}/slack/channels/{origin_channel}/messages"
        result = http_post_json(url, {"text": body}, {"Authorization": f"Bearer {api_key}"})
        if not isinstance(result, dict) or "_error" in result:
            print(
                f"dispatch-sweep: nudge post failed for job {job_id} (repo {repo}): {result}",
                file=sys.stderr,
            )
    except Exception as e:  # a nudge failure must never look like a sweep failure
        print(f"dispatch-sweep: nudge raised for job {job_id} (repo {repo}): {e}", file=sys.stderr)


def send_message(target: str, body: str) -> int:
    """Deliver `body` to `target` via `hermes send --file` (never as an argv
    string — the brief may contain arbitrary text). Returns the subprocess exit
    code (0 ok, 1 delivery/backend error, 2 usage error); a spawn/timeout
    failure folds into a synthetic 1 so the `== 0` gate on reported_at still
    holds — it never raises."""
    tmp_path = ""
    try:
        with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False) as f:
            f.write(body)
            tmp_path = f.name
        r = subprocess.run(
            [str(HERMES_BIN), "send", "--to", target, "--file", tmp_path, "--json", "--quiet"],
            capture_output=True, text=True, timeout=HERMES_SEND_TIMEOUT,
        )
        return r.returncode
    except (OSError, subprocess.SubprocessError):
        return 1
    finally:
        if tmp_path:
            try:
                os.unlink(tmp_path)
            except OSError:
                pass


def _truncate(text: str, limit: int) -> tuple[str, bool]:
    if len(text) <= limit:
        return text, False
    return text[:limit].rstrip() + "…", True


def format_evidence(evidence: list[Any]) -> list[str]:
    capped = evidence[:EVIDENCE_CAP]
    lines: list[str] = []
    for e in capped:
        if isinstance(e, dict):
            file = e.get("file") or "?"
            detail = e.get("detail") or ""
            lines.append(f"- `{file}` — {detail}")
        else:
            lines.append(f"- {e}")
    overflow = len(evidence) - len(capped)
    if overflow > 0:
        lines.append(f"- … and {overflow} more")
    return lines


def _finalize(lines: list[str]) -> str:
    body = "\n".join(lines)
    body, truncated = _truncate(body, BODY_CHAR_LIMIT)
    if truncated:
        body += "\n\n_(message truncated)_"
    return body


def _format_merged_ts(merged_at: str) -> str:
    """Render `merged_at` as `YYYY-MM-DD HH:MM UTC`. Fails toward "say it is
    merged" — a malformed or unparseable value still counts as merged (the
    merge happened; only the display degrades), so this falls back to the
    raw string rather than raising or dropping the merged treatment."""
    try:
        parsed = dt.datetime.fromisoformat(merged_at)
    except (TypeError, ValueError):
        return merged_at
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=dt.timezone.utc)
    return parsed.astimezone(dt.timezone.utc).strftime("%Y-%m-%d %H:%M UTC")


def format_message(*, repo: str, tier: str, job_id: str, status: str,
                    result: dict[str, Any] | None, error: Any,
                    merged_at: str | None = None) -> str:
    """Deterministic Slack mrkdwn body for one terminal dispatch. No LLM —
    every field comes straight from sideclaw's schema-shaped verdict object
    (`{verdict, confidence, evidence[], recommendation, nextAction, summary,
    degraded?, artifactUrl?, branch?}`) or, for a failed/interrupted job, its
    `error` string.

    `merged_at` is threaded in separately from `result` — it lives on the
    dispatches row itself (stamped by hermes-cc.sh's `merge` verb, which
    deliberately does NOT stamp `reported_at`: the merge announcement and the
    sweeper's verdict are different messages). Without this, a dispatch that
    was already merged still renders as "here is your draft PR, review it" —
    observed live 2026-08-02 on job 6f7c9cc4, where the merge landed at
    19:06:00 and the sweeper posted the stale review instruction at
    19:10:02. A truthy `merged_at` here means: say it is merged, everywhere
    that would otherwise read as an outstanding review ask."""
    job_short = job_id[:8]
    merged = bool(merged_at)

    if status in ("failed", "interrupted"):
        lines = [
            f":warning: Dispatch {status} — {repo}",
            f"error: {error if error else 'no error detail returned by sideclaw'}",
            "",
            f"_tier {tier} · job `{job_short}`_",
        ]
        return _finalize(lines)

    if not isinstance(result, dict):
        # status == "done" but sideclaw returned no result object at all —
        # render this plainly rather than staying silent, since silence is
        # exactly the debt this sweeper exists to close.
        lines = [
            f":warning: Dispatch done with no verdict — {repo}",
            "sideclaw reported status=done but returned no result object.",
            "",
            f"_tier {tier} · job `{job_short}`_",
        ]
        return _finalize(lines)

    degraded = bool(result.get("degraded"))
    lines = []
    if degraded:
        header = f":grey_question: Dispatch degraded — {repo}"
        if merged:
            header += " _(already merged)_"
        lines.append(header)
        lines.append("_The tool run failed partway through — this is not a finding about the repo._")
    elif merged:
        lines.append(f":white_check_mark: Dispatch verdict — {repo} _(already merged)_")
    else:
        lines.append(f":mag: Dispatch verdict — {repo}")

    summary = (result.get("summary") or "").strip()
    if summary:
        lines.append(summary)

    # The artifact goes directly under the summary, above the prose, because it is the
    # only actionable line in the message and `_finalize` truncates from the bottom.
    # `branch` without `artifactUrl` is its own real outcome: the implement tier pushed
    # work but opened no PR (the episode declined to describe one, or the run degraded),
    # and saying so is what stops that branch from being silently orphaned.
    artifact_url = (result.get("artifactUrl") or "").strip()
    branch = (result.get("branch") or "").strip()
    if artifact_url:
        artifact_line = f"*Artifact:* {artifact_url}"
        if merged:
            artifact_line += f" — *merged* {_format_merged_ts(merged_at)}"
        lines.append(artifact_line)
    elif branch:
        lines.append(f"*Branch pushed, no PR opened:* `{branch}`")

    verdict_text = (result.get("verdict") or "").strip()
    if verdict_text:
        v_text, v_truncated = _truncate(verdict_text, 1500)
        lines.append("")
        lines.append(v_text)
        if v_truncated:
            lines.append("_(verdict text truncated)_")

    recommendation = (result.get("recommendation") or "").strip()
    if recommendation:
        lines.append("")
        lines.append(f"*Recommendation:* {recommendation}")

    evidence = result.get("evidence")
    if isinstance(evidence, list) and evidence:
        lines.append("")
        lines.append("*Evidence:*")
        lines.extend(format_evidence(evidence))

    confidence = result.get("confidence") or "?"
    next_action = "none (merged)" if merged else (result.get("nextAction") or "?")
    lines.append("")
    lines.append(f"_confidence {confidence} · next {next_action} · tier {tier} · job `{job_short}`_")

    return _finalize(lines)


def process_dispatch(conn: sqlite3.Connection, row: sqlite3.Row, *, dry_run: bool) -> None:
    job_id = row["job_id"]
    repo = row["repo"]
    tier = row["tier"]

    job = poll_job(job_id)
    if job is None:
        print(
            f"dispatch-sweep: could not poll sideclaw for job {job_id} (repo {repo}) "
            f"— retrying next sweep",
            file=sys.stderr,
        )
        return

    status = job.get("status")
    if status not in TERMINAL_STATUSES:
        return  # still queued/running — nothing to report yet

    result = job.get("result")
    error = job.get("error")
    # `or None` so "" and NULL do not become two shapes of the same fact — every
    # reader of this column (and the actionable predicate below) filters on
    # IS NOT NULL / truthiness.
    artifact_url = ((result.get("artifactUrl") if isinstance(result, dict) else None) or "").strip() or None

    # Fold the terminal outcome back into the row and commit it BEFORE any
    # delivery attempt — see the module docstring's crash-safety contract.
    if not dry_run:
        now_iso = dt.datetime.now(dt.timezone.utc).isoformat()
        # `artifact_url` is denormalized out of the verdict into its own column so the
        # GitHub projection is a column read, not a JSON parse — the briefing and the
        # watchdog both want "what did this dispatch produce" without unpacking a blob.
        conn.execute(
            "UPDATE dispatches SET status=?, verdict_json=?, artifact_url=?, finished_at=? "
            "WHERE job_id=?",
            (
                status,
                json.dumps(result) if result is not None else None,
                artifact_url,
                now_iso,
                job_id,
            ),
        )
        conn.commit()

    origin_channel = row["origin_channel"]
    origin_thread_ts = row["origin_thread_ts"]

    if not origin_channel:
        print(
            f"dispatch-sweep: job {job_id} (repo {repo}, tier {tier}) finished with no "
            f"origin_channel — cannot deliver to any thread, closing with a sentinel",
            file=sys.stderr,
        )
        if dry_run:
            print(
                f"[dry-run] would stamp reported_at={UNDELIVERABLE_SENTINEL!r} for job "
                f"{job_id} (no origin_channel, nothing sent)"
            )
            return
        conn.execute(
            "UPDATE dispatches SET reported_at=? WHERE job_id=? AND reported_at IS NULL",
            (UNDELIVERABLE_SENTINEL, job_id),
        )
        conn.commit()
        return

    body = format_message(repo=repo, tier=tier, job_id=job_id, status=status,
                           result=result, error=error, merged_at=row["merged_at"])
    target = f"slack:{origin_channel}:{origin_thread_ts}" if origin_thread_ts else f"slack:{origin_channel}"
    actionable = is_actionable(status=status, tier=tier, artifact_url=artifact_url,
                                merged_at=row["merged_at"])

    if dry_run:
        print(f"[dry-run] would send to {target} (job {job_id}, repo {repo}):\n{body}\n")
        if actionable:
            nudge_body = build_nudge_body(job_id=job_id, repo=repo, tier=tier,
                                           artifact_url=artifact_url)
            print(f"[dry-run] would nudge {target} (job {job_id}, repo {repo}):\n{nudge_body}\n")
        return

    rc = send_message(target, body)
    if rc == 0:
        now_iso2 = dt.datetime.now(dt.timezone.utc).isoformat()
        conn.execute(
            "UPDATE dispatches SET reported_at=? WHERE job_id=? AND reported_at IS NULL",
            (now_iso2, job_id),
        )
        conn.commit()
        # Strictly AFTER reported_at is stamped, and best-effort — see
        # send_nudge()'s docstring for why ordering here is load-bearing.
        if actionable:
            send_nudge(origin_channel=origin_channel, origin_thread_ts=origin_thread_ts,
                       job_id=job_id, repo=repo, tier=tier, artifact_url=artifact_url)
    else:
        print(
            f"dispatch-sweep: hermes send exited {rc} for job {job_id} (repo {repo}, "
            f"target {target}) — reported_at left NULL, next sweep retries",
            file=sys.stderr,
        )


def main(argv: list[str] | None = None) -> int:
    argv = list(argv if argv is not None else sys.argv[1:])
    dry_run = "--dry-run" in argv
    # Accepted but a deliberate no-op: main() already performs exactly one pass
    # per invocation (the cron's own 5-minute schedule is the loop), so there is
    # nothing for --once to change. Documented rather than silently ignored, so
    # a caller can't wonder whether omitting it does something different.
    _ = "--once" in argv

    _apply_db_override(argv)

    conn = db_connect()
    try:
        rows = conn.execute(
            "SELECT * FROM dispatches WHERE reported_at IS NULL ORDER BY id"
        ).fetchall()
        for row in rows:
            try:
                process_dispatch(conn, row, dry_run=dry_run)
            except Exception as e:  # one bad row must never stop the others
                print(
                    f"dispatch-sweep: row job_id={row['job_id']!r} (repo {row['repo']!r}) "
                    f"raised: {e} — skipping, next sweep retries",
                    file=sys.stderr,
                )
    finally:
        conn.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
