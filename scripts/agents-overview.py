#!/usr/bin/env python3
"""Agents overview — read-only summary of every Claude Code / herdr agent
sideclaw is tracking, for Slack pings and the morning briefing.

Talks to sideclaw's overview endpoints (`http://localhost:7705`, a local
LaunchAgent — see `skills/agents/SKILL.md`):

  GET  /api/overview          -> {ok, data: {generatedAt, summary, projects[], overview, ...}}
  GET  /api/agents            -> {ok, data: {generatedAt, summary, projects[], ...}}  -- same
       shape as /api/overview minus `overview`/recommendations: a deterministic
       snapshot with no LLM involved, used to decide whether a refresh is worth
       triggering at all.
  POST /api/jobs {"tool":"overview"} -> {ok, job:{id, status, ...}}   -- triggers
       a fresh LLM pass; poll GET /api/jobs/<id> until status is
       done|failed, then re-GET /api/overview for the merged result.

Refresh is consumer-driven, not clock-driven: `--briefing` only refreshes
when the cached overview is missing or older than
`HERMES_AGENTS_BRIEFING_MAX_AGE_S` (default 7200s); `--slack-body` only
refreshes when the deterministic `/api/agents` snapshot's fingerprint()
differs from the last run's — an idle night produces zero model calls.

This script only reads. It never sends keys to a herdr pane and never
dispatches — that is scripts/hermes-cc.sh's job.

Source of truth: ~/SourceRoot/hermes-agent/scripts/agents-overview.py
~/.hermes/scripts/ is itself a symlink to this directory (see make setup).
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

STATE_PATH = Path.home() / ".hermes" / "agents-overview-state.json"

DEFAULT_BASE = "http://localhost:7705"

BRIEFING_MAX_AGE_S_ENV = "HERMES_AGENTS_BRIEFING_MAX_AGE_S"
DEFAULT_BRIEFING_MAX_AGE_S = 7200

DEFAULT_AGENTS_CHANNEL = "C0BVDE5R562"
SLACK_POST_URL = "https://slack.com/api/chat.postMessage"

# SLACK_BOT_TOKEN is unconditionally Tier-1-stripped from every subprocess the
# gateway spawns (tools/environments/local.py's _ALWAYS_STRIP_KEYS — same
# treatment as GITHUB_TOKEN), so a cron-run `--slack-body`/`--post-full` never
# sees it via os.environ. Mirrors watchdog-poll.py's resolve_secret() fallback:
# inherited env first (covers a manual run), else the encrypted secrets cache.
SECRETS_RUN = Path.home() / ".local" / "bin" / "secrets-run"
SLACK_TOKEN_REF = "op://hermes/slack/bot-token"

# Recommendation -> icon, mirrors sideclaw's own /api/overview.txt rendering.
RECOMMENDATION_ICONS = {
    "answer": "?!",
    "continue": "→",  # ->
    "ship": "⇧",      # up-shift arrow
    "review": "⚑",    # flag
    "merge": "⇄",     # merge arrows
    "close": "✓",     # check
    "stale": "·",     # middle dot
    "watch": "●",     # filled circle
}

# Emoji map for the Block Kit digest — mirrors RECOMMENDATION_ICONS above but
# using Slack `:emoji:` names instead of unicode glyphs (plain_text/mrkdwn
# render emoji shortcodes; the unicode glyphs above are for the .txt surface).
RECOMMENDATION_EMOJI = {
    "answer": ":rotating_light:",
    "ship": ":package:",
    "merge": ":twisted_rightwards_arrows:",
    "review": ":eyes:",
    "continue": ":arrow_forward:",
    "close": ":white_check_mark:",
    "stale": ":zzz:",
    "watch": ":hourglass_flowing_sand:",
    "none": ":grey_question:",
}

# Recommendations worth a Slack ping / a morning-briefing line.
ACTIONABLE = {"answer", "ship", "merge", "review"}
QUIET = {"watch", "close"}

SLACK_MAX_LINES = 25
BRIEFING_MAX_LINES = 20

# Block Kit hard limits (render_slack_blocks) — see docs/agents-overview.md.
BLOCKS_MAX = 50
SECTION_TEXT_MAX = 3000
HEADER_TEXT_MAX = 150
TITLE_MAX = 60
STANDING_MAX = 110
BLOCKER_MAX = 100


def _base_url() -> str:
    return os.environ.get("HERMES_AGENTS_SIDECLAW_BASE", DEFAULT_BASE)


def _channel() -> str:
    return os.environ.get("HERMES_AGENTS_CHANNEL", DEFAULT_AGENTS_CHANNEL)


def _resolve_ref(ref: str) -> str:
    """Resolve one op:// ref via the secrets-run shim; '' on any failure."""
    env = os.environ.copy()
    # secrets-run's cache backend needs sops+jq (Homebrew); ensure they resolve
    # even under a minimal PATH (the gateway spawns cron scripts with a
    # sanitized env — same fix as watchdog-poll.py's _resolve_ref).
    env["PATH"] = "/opt/homebrew/bin:/usr/local/bin:" + env.get("PATH", "/usr/bin:/bin")
    try:
        r = subprocess.run(
            [str(SECRETS_RUN), "read", ref],
            capture_output=True, text=True, timeout=15, env=env,
        )
    except (OSError, subprocess.SubprocessError):
        return ""
    return r.stdout.strip() if r.returncode == 0 else ""


def resolve_slack_token() -> str:
    """SLACK_BOT_TOKEN from the inherited process env first (a manual run, or
    any spawn path that doesn't sanitize it), else the encrypted secrets
    cache — the normal path when invoked as a cron job, since the gateway's
    subprocess sanitizer strips SLACK_BOT_TOKEN unconditionally. Never
    raises, never logs the token itself."""
    val = os.environ.get("SLACK_BOT_TOKEN", "")
    if val:
        return val
    return _resolve_ref(SLACK_TOKEN_REF)


def fetch(base: str, timeout_s: int = 10) -> dict[str, Any]:
    """GET /api/overview and return the `data` object. Raises on any
    transport/shape failure — callers decide how to degrade."""
    req = urllib.request.Request(f"{base}/api/overview")
    with urllib.request.urlopen(req, timeout=timeout_s) as resp:
        payload = json.loads(resp.read().decode())
    if not payload.get("ok"):
        raise RuntimeError(f"overview fetch not ok: {payload}")
    return payload["data"]


def fetch_agents(base: str, timeout_s: int = 10) -> dict[str, Any]:
    """GET /api/agents and return the `data` object — the deterministic
    snapshot (no LLM overview, no recommendations) used to decide whether a
    refresh is worth its model call. Same failure contract as fetch()."""
    req = urllib.request.Request(f"{base}/api/agents")
    with urllib.request.urlopen(req, timeout=timeout_s) as resp:
        payload = json.loads(resp.read().decode())
    if not payload.get("ok"):
        raise RuntimeError(f"agents fetch not ok: {payload}")
    return payload["data"]


def fingerprint(data: dict[str, Any]) -> str:
    """Pure, deterministic fingerprint of a snapshot's agent/project state:
    sha256 over the canonical JSON of the sorted rows
    (agent.id, agent.state, agent.lastActivityAt, project.name,
    project.git.dirty, project.git.ahead) across every agent in every
    project. Sorting by each row's own canonical JSON (rather than the raw
    tuples) keeps this stable across dict key order and project/agent
    iteration order, and sidesteps comparing mixed None/str/int/bool values
    directly."""
    rows: list[list[Any]] = []
    for project in data.get("projects") or []:
        git = project.get("git") or {}
        for agent in project.get("agents") or []:
            rows.append([
                agent.get("id"),
                agent.get("state"),
                agent.get("lastActivityAt"),
                project.get("name"),
                git.get("dirty"),
                git.get("ahead"),
            ])
    rows.sort(key=lambda row: json.dumps(row, sort_keys=True, default=str))
    canonical = json.dumps(rows, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode()).hexdigest()


def needs_refresh(data: dict[str, Any], max_age_ms: int) -> bool:
    """Pure staleness check for --briefing: a missing/null overview (never
    run) or one older than max_age_ms needs a fresh pass before rendering."""
    overview = data.get("overview")
    if not overview:
        return True
    age_ms = overview.get("ageMs")
    if age_ms is None:
        return True
    return age_ms > max_age_ms


def _briefing_max_age_ms() -> int:
    try:
        return int(os.environ.get(BRIEFING_MAX_AGE_S_ENV, DEFAULT_BRIEFING_MAX_AGE_S)) * 1000
    except ValueError:
        return DEFAULT_BRIEFING_MAX_AGE_S * 1000


def _fmt_age_ms(ms: int | None) -> str:
    if ms is None:
        return "unknown"
    secs = ms / 1000
    if secs < 3600:
        return f"{int(secs / 60)}m"
    if secs < 86400:
        return f"{int(secs / 3600)}h"
    return f"{int(secs / 86400)}d"


def refresh(base: str, timeout_s: int = 120) -> dict[str, Any] | None:
    """Trigger a fresh overview pass and wait for it, bounded so a single
    `terminal` tool call (180s cap) never blocks past its own budget. Six
    polls, 20s apart, is the default — tolerates any failure by returning
    None (never raises); the caller falls back to a plain fetch()."""
    try:
        body = json.dumps({"tool": "overview", "params": {}}).encode()
        req = urllib.request.Request(
            f"{base}/api/jobs",
            data=body,
            headers={"content-type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=15) as resp:
            submitted = json.loads(resp.read().decode())
        job_id = submitted["job"]["id"]
    except (urllib.error.URLError, urllib.error.HTTPError, KeyError,
            json.JSONDecodeError, TimeoutError, OSError):
        return None

    poll_interval = 20
    polls = max(1, timeout_s // poll_interval)
    for _ in range(polls):
        time.sleep(poll_interval)
        try:
            with urllib.request.urlopen(f"{base}/api/jobs/{job_id}", timeout=15) as resp:
                polled = json.loads(resp.read().decode())
        except (urllib.error.URLError, urllib.error.HTTPError,
                json.JSONDecodeError, TimeoutError, OSError):
            return None
        status = polled.get("job", {}).get("status")
        if status == "done":
            try:
                return fetch(base)
            except Exception:
                return None
        if status == "failed":
            return None
    return None


def _agent_index(overview: dict[str, Any] | None) -> dict[str, dict[str, Any]]:
    """id -> {recommendation, title, project} for every agent in an overview
    `data` object. Deliberately ignores `standing`/`state` — those churn
    every run without being a decision-relevant change."""
    idx: dict[str, dict[str, Any]] = {}
    if not overview:
        return idx
    for project in overview.get("projects") or []:
        pname = project.get("name") or "?"
        for agent in project.get("agents") or []:
            aid = agent.get("id")
            if not aid:
                continue
            idx[aid] = {
                "recommendation": agent.get("recommendation"),
                "title": agent.get("title") or "?",
                "project": pname,
            }
    return idx


def delta(prev: dict[str, Any] | None, cur: dict[str, Any]) -> list[str]:
    """Pure diff of two overview `data` objects, by agent id: new agents,
    changed recommendations, agents that disappeared. A recommendation that
    stays the same never produces an entry, no matter what else about the
    agent (state, standing wording) changed in the meantime — that's what
    makes watch<->working churn and standing-only edits invisible here.

    Each entry carries a trailing `[id:<agent id>]` tag — machine-readable,
    parsed by `_changed_ids()` so render_slack_blocks() can show a changed
    agent in the digest even when its recommendation isn't itself
    actionable (e.g. a stale agent going `close`). The human-readable prefix
    is unchanged, so this is additive."""
    prev_idx = _agent_index(prev)
    cur_idx = _agent_index(cur)
    changes: list[str] = []

    for aid, info in cur_idx.items():
        if aid not in prev_idx:
            changes.append(
                f"new: {info['project']} — {info['title']} ({info['recommendation']}) [id:{aid}]"
            )
            continue
        old_rec = prev_idx[aid]["recommendation"]
        new_rec = info["recommendation"]
        if old_rec != new_rec:
            changes.append(
                f"changed: {info['project']} — {info['title']} "
                f"({old_rec} → {new_rec}) [id:{aid}]"
            )

    for aid, info in prev_idx.items():
        if aid not in cur_idx:
            changes.append(f"gone: {info['project']} — {info['title']} [id:{aid}]")

    return changes


_CHANGE_ID_RE = re.compile(r"\[id:([^\]]+)\]$")


def _changed_ids(changes: list[str]) -> set[str]:
    """Extract the `[id:...]` tags delta() appends to each entry."""
    ids: set[str] = set()
    for c in changes:
        m = _CHANGE_ID_RE.search(c)
        if m:
            ids.add(m.group(1))
    return ids


def _project_actionable(cur: dict[str, Any]) -> list[tuple[str, list[dict[str, Any]]]]:
    grouped: list[tuple[str, list[dict[str, Any]]]] = []
    for project in cur.get("projects") or []:
        items = [
            a for a in (project.get("agents") or [])
            if a.get("recommendation") in ACTIONABLE
        ]
        if items:
            grouped.append((project.get("name") or "?", items))
    return grouped


def _summary_line(cur: dict[str, Any]) -> str:
    s = cur.get("summary") or {}
    return (
        f"agents: {s.get('needsYou', 0)} needs_you · "
        f"{s.get('working', 0)} working · "
        f"{s.get('idle', 0)} idle · "
        f"{s.get('stale', 0)} stale · "
        f"{s.get('done', 0)} done · "
        f"{s.get('dispatch', 0)} dispatch"
    )


def render_slack(cur: dict[str, Any], changes: list[str]) -> str:
    """mrkdwn body: header + actionable (answer/ship/merge/review) agents
    grouped by project. Silence is the normal case — empty string whenever
    `changes` is empty, full stop. A persistent, unchanged `answer` item is
    NOT re-announced every cycle (this cron runs every 30 min — reposting an
    unresolved question that often would be noise, not a nudge); the morning
    briefing re-surfaces standing answer items daily via render_briefing(),
    which is enough."""
    if not changes:
        return ""

    grouped = _project_actionable(cur)

    lines = [_summary_line(cur)]
    for pname, items in grouped:
        lines.append(f"*{pname}*")
        for a in items:
            icon = RECOMMENDATION_ICONS.get(a.get("recommendation"), "·")
            title = a.get("title") or "?"
            standing = (a.get("standing") or "").strip()
            suffix = f" — {standing}" if standing else ""
            lines.append(f"{icon} {title}{suffix}")

    if len(lines) > SLACK_MAX_LINES:
        overflow = len(lines) - (SLACK_MAX_LINES - 1)
        lines = lines[: SLACK_MAX_LINES - 1] + [f"… and {overflow} more"]

    return "\n".join(lines)


def _escape(text: str) -> str:
    """Escape Slack mrkdwn control chars in agent-derived text (titles,
    standings, blockers — sourced from transcripts, attacker-influenced).
    Order matters: `&` first, or the entities just inserted get re-escaped."""
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _truncate(text: str, limit: int) -> str:
    """Truncate to at most `limit` chars, appending an ellipsis when cut."""
    if len(text) <= limit:
        return text
    if limit <= 1:
        return text[:limit]
    return text[: limit - 1].rstrip() + "…"


def _priority(recommendation: str | None) -> int:
    """0 = answer, 1 = ship/merge/review, 2 = everything else."""
    if recommendation == "answer":
        return 0
    if recommendation in ("ship", "merge", "review"):
        return 1
    return 2


def _fmt_hhmm(generated_at_ms: int | None) -> str:
    if not generated_at_ms:
        return "--:--"
    try:
        return time.strftime("%H:%M", time.localtime(generated_at_ms / 1000))
    except (OSError, OverflowError, ValueError, TypeError):
        return "--:--"


def _blocks_header_text(cur: dict[str, Any]) -> str:
    s = cur.get("summary") or {}
    text = (
        f"Agents · {s.get('needsYou', 0)} need you · "
        f"{s.get('working', 0)} working · {s.get('stale', 0)} stale"
    )
    return _truncate(text, HEADER_TEXT_MAX)


def _blocks_footer_text(cur: dict[str, Any], changes: list[str]) -> str:
    overview = cur.get("overview") or {}
    age = _fmt_age_ms(overview.get("ageMs"))
    model = overview.get("model") or "?"
    hhmm = _fmt_hhmm(overview.get("generatedAt"))
    return f"overview {age} old · {model} · {len(changes)} changes since last digest · {hhmm}"


def _project_section_block(
    pname: str, git: dict[str, Any] | None, agents: list[dict[str, Any]],
) -> dict[str, Any]:
    git = git or {}
    branch = _escape(str(git.get("branch") or "?"))
    dirty_mark = "*" if git.get("dirty") else ""
    lines = [f"*{_escape(pname)}*  `{branch}{dirty_mark}`"]
    for a in agents:
        emoji = RECOMMENDATION_EMOJI.get(a.get("recommendation") or "", RECOMMENDATION_EMOJI["none"])
        title = _truncate(_escape((a.get("title") or "?").strip()), TITLE_MAX)
        standing = _truncate(_escape((a.get("standing") or "").strip()), STANDING_MAX)
        suffix = f" — {standing}" if standing else ""
        lines.append(f"{emoji} {title}{suffix}")
        blocker = (a.get("blocker") or "").strip()
        if blocker:
            blocker_t = _truncate(_escape(blocker), BLOCKER_MAX)
            lines.append(f"    ↳ _{blocker_t}_")
    text = _truncate("\n".join(lines), SECTION_TEXT_MAX)
    return {"type": "section", "text": {"type": "mrkdwn", "text": text}}


def render_slack_blocks(
    cur: dict[str, Any], changes: list[str], *, full: bool = False,
) -> list[dict[str, Any]]:
    """Block Kit body for the #agents digest / on-demand overview. Pure —
    same `cur`/`changes` shapes as render_slack()/delta().

    Which agents show, per project: `full=True` (--post-full) shows every
    agent with a recommendation; `full=False` (the cron digest) shows only
    agents whose recommendation is actionable (answer/ship/merge/review) OR
    whose id appears in `changes` (delta()'s `[id:...]` tags) — so a
    newly-changed but non-actionable agent (e.g. -> close) still surfaces,
    while a persistent unchanged watch/continue agent stays out.

    Projects are sorted with any `answer` agent first, then ship/merge/
    review, then the rest; agents within a project use the same order.
    Capped at BLOCKS_MAX total blocks — lowest-priority projects are
    dropped first, replaced by a trailing `… and N more projects` context
    block."""
    changed_ids = _changed_ids(changes)

    project_chunks: list[tuple[int, dict[str, Any]]] = []
    for project in cur.get("projects") or []:
        all_agents = project.get("agents") or []
        if full:
            shown = [a for a in all_agents if a.get("recommendation")]
        else:
            shown = [
                a for a in all_agents
                if a.get("recommendation") in ACTIONABLE or a.get("id") in changed_ids
            ]
        if not shown:
            continue
        shown.sort(key=lambda a: _priority(a.get("recommendation")))
        priority = min(_priority(a.get("recommendation")) for a in shown)
        block = _project_section_block(project.get("name") or "?", project.get("git"), shown)
        project_chunks.append((priority, block))

    project_chunks.sort(key=lambda item: item[0])
    all_blocks = [b for _, b in project_chunks]

    header_block = {"type": "header", "text": {"type": "plain_text", "text": _blocks_header_text(cur)}}
    footer_block = {"type": "context", "elements": [{"type": "mrkdwn", "text": _blocks_footer_text(cur, changes)}]}

    def _assemble(kept: list[dict[str, Any]]) -> list[dict[str, Any]]:
        blocks = [header_block]
        for i, block in enumerate(kept):
            if i:
                blocks.append({"type": "divider"})
            blocks.append(block)
        blocks.append(footer_block)
        return blocks

    kept = list(all_blocks)
    while kept:
        blocks = _assemble(kept)
        extra = 1 if len(kept) < len(all_blocks) else 0
        if len(blocks) + extra <= BLOCKS_MAX:
            break
        kept = kept[:-1]
    else:
        blocks = _assemble(kept)

    dropped = len(all_blocks) - len(kept)
    if dropped:
        plural = "s" if dropped != 1 else ""
        blocks.append({
            "type": "context",
            "elements": [{"type": "mrkdwn", "text": f"… and {dropped} more project{plural}"}],
        })

    return blocks


def post_blocks(channel: str, blocks: list[dict[str, Any]], text_fallback: str, token: str) -> bool:
    """POST `blocks` to Slack's chat.postMessage. Returns True iff Slack
    reports `ok: true`; never raises — any transport/parse failure or
    `ok: false` returns False so the caller falls back to plain mrkdwn.
    `text_fallback` is required by the Slack API as the notification-text /
    unfurl-fallback field even when blocks render the real body. Never logs
    the token."""
    body = json.dumps({
        "channel": channel,
        "blocks": blocks,
        "text": text_fallback,
        "unfurl_links": False,
    }).encode()
    req = urllib.request.Request(
        SLACK_POST_URL,
        data=body,
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json; charset=utf-8",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            payload = json.loads(resp.read().decode())
    except (urllib.error.URLError, urllib.error.HTTPError, json.JSONDecodeError, TimeoutError, OSError):
        return False
    ok = bool(payload.get("ok"))
    if not ok:
        print(f"agents-overview: slack post failed: {payload.get('error', 'unknown')}", file=sys.stderr)
    return ok


def render_briefing(cur: dict[str, Any]) -> str:
    """Plain-text block for the morning-briefing prompt: counts, then every
    agent whose recommendation is not watch/close (i.e. nothing to do)."""
    lines = [_summary_line(cur)]
    for project in cur.get("projects") or []:
        pname = project.get("name") or "?"
        for a in project.get("agents") or []:
            rec = a.get("recommendation")
            if not rec or rec in QUIET:
                continue
            title = a.get("title") or "?"
            standing = (a.get("standing") or "").strip()
            blocker = (a.get("blocker") or "").strip()
            lines.append(f"{pname} · {rec} · {title} · {standing} · {blocker}")

    if len(lines) > BRIEFING_MAX_LINES:
        overflow = len(lines) - (BRIEFING_MAX_LINES - 1)
        lines = lines[: BRIEFING_MAX_LINES - 1] + [f"… and {overflow} more"]

    return "\n".join(lines)


def _load_state() -> dict[str, Any] | None:
    try:
        return json.loads(STATE_PATH.read_text())
    except (FileNotFoundError, json.JSONDecodeError):
        return None


def _save_state(cur: dict[str, Any]) -> None:
    try:
        STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
        tmp = STATE_PATH.with_suffix(STATE_PATH.suffix + f".tmp.{os.getpid()}")
        tmp.write_text(json.dumps(cur))
        tmp.replace(STATE_PATH)
    except OSError:
        pass


def main(argv: list[str] | None = None) -> int:
    args = argv if argv is not None else sys.argv[1:]
    base = _base_url()

    if "--briefing" in args:
        try:
            cur = fetch(base)
        except Exception:
            print("agents overview unavailable")
            return 0
        if needs_refresh(cur, _briefing_max_age_ms()):
            refreshed = refresh(base)
            if refreshed is not None:
                cur = refreshed
            else:
                age_ms = (cur.get("overview") or {}).get("ageMs")
                print(render_briefing(cur))
                print(f"overview verdicts are {_fmt_age_ms(age_ms)} old")
                return 0
        print(render_briefing(cur))
        return 0

    if "--json" in args:
        try:
            cur = fetch(base)
        except Exception as e:
            print(json.dumps({"error": str(e)}))
            return 0
        print(json.dumps(cur))
        return 0

    if "--slack-body" in args:
        prev = _load_state()
        try:
            snapshot = fetch_agents(base)
        except Exception:
            snapshot = None

        fp: str | None = None
        if snapshot is not None:
            fp = fingerprint(snapshot)
            if prev is not None and fp == prev.get("fingerprint"):
                # Deterministic snapshot unchanged since the last run —
                # nothing moved, so skip the model call entirely.
                return 0

        cur = refresh(base)
        if cur is None:
            try:
                cur = fetch(base)
            except Exception:
                # Sideclaw unreachable end to end — degrade silently, never
                # kill the calling cron. State is left untouched so the next
                # successful run diffs against the last known-good snapshot.
                return 0
        changes = delta(prev, cur)
        body = render_slack(cur, changes)
        if body:
            # Post Block Kit ourselves when a token resolves — the runner
            # delivers this script's stdout verbatim under no_agent, so
            # printing `body` here too would double-post. Only the mrkdwn
            # fallback (no token, or Slack rejected the post) goes to stdout.
            token = resolve_slack_token()
            posted = False
            blocks: list[dict[str, Any]] = []
            if token:
                blocks = render_slack_blocks(cur, changes, full=False)
                posted = post_blocks(_channel(), blocks, body, token)
            if posted:
                print(
                    f"agents-overview: posted digest via blocks "
                    f"({len(blocks)} blocks) to {_channel()}",
                    file=sys.stderr,
                )
            else:
                print(body)
        cur["fingerprint"] = fp if fp is not None else fingerprint(cur)
        _save_state(cur)
        return 0

    if "--post-full" in args:
        try:
            cur = fetch(base)
        except Exception:
            print("agents overview unavailable", file=sys.stderr)
            return 0
        token = resolve_slack_token()
        if not token:
            print("agents-overview: SLACK_BOT_TOKEN unresolved, cannot post --post-full", file=sys.stderr)
            return 1
        blocks = render_slack_blocks(cur, [], full=True)
        fallback = render_briefing(cur)
        if not post_blocks(_channel(), blocks, fallback, token):
            print("agents-overview: --post-full slack post failed", file=sys.stderr)
            return 1
        print(
            f"agents-overview: posted full overview ({len(blocks)} blocks) to {_channel()}",
            file=sys.stderr,
        )
        return 0

    print("usage: agents-overview.py --slack-body | --briefing | --json | --post-full", file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main())
