#!/usr/bin/env python3
"""Agents overview — read-only summary of every Claude Code / herdr agent
sideclaw is tracking, for the morning briefing and an on-demand Slack post.

Talks to sideclaw's overview endpoints (`http://localhost:7705`, a local
LaunchAgent — see `skills/agents/SKILL.md`):

  GET  /api/overview          -> {ok, data: {generatedAt, summary, projects[], overview, ...}}
  POST /api/jobs {"tool":"overview"} -> {ok, job:{id, status, ...}}   -- triggers
       a fresh LLM pass; poll GET /api/jobs/<id> until status is
       done|failed, then re-GET /api/overview for the merged result.

Refresh is consumer-driven, not clock-driven: `--briefing` only refreshes
when the cached overview is missing or older than
`HERMES_AGENTS_BRIEFING_MAX_AGE_S` (default 7200s) — an idle night produces
zero model calls.

`data.humanQueue` (sideclaw, 2026-09-07) is the mini's ask-human queue —
`[{id, askedAt, question, cmd?}]`, work that needs a PRESENT human (a
biometric `op`, an ACL push). It renders as a "Needs you" section at the
top of the briefing and the `--post-full` overview.

An agent in state `needs_you` is ALWAYS listed in the briefing, whatever its
recommendation — `summary.needsYou` counts by state, so a briefing whose
header says "1 need you" must show that one item.

This script only reads. It never sends keys to a herdr pane and never
dispatches — that is warden's job (scripts/hermes-cc.sh is only the exec shim
into it).

Retired 2026-09-11: the scheduled `#agents` Slack digest (`--slack-body`,
cron job `72aa2fb36307`) that reposted this data every 30 minutes. Its code
(`render_slack()`, the fingerprint-based change detection, the once-per-day
unreachable warning) was removed 2026-09-12 once nothing referenced it any
more — see `docs/scheduled-jobs.md` for the retirement history and how to
recreate it from git if ever needed. `--post-full` (an on-demand, human-run
Slack post of the full overview) is unrelated and still live.

Source of truth: ~/SourceRoot/hermes-agent/scripts/agents-overview.py
~/.hermes/scripts/ is itself a symlink to this directory (see make setup).
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

DEFAULT_BASE = "http://localhost:7705"

BRIEFING_MAX_AGE_S_ENV = "HERMES_AGENTS_BRIEFING_MAX_AGE_S"
DEFAULT_BRIEFING_MAX_AGE_S = 7200

DEFAULT_AGENTS_CHANNEL = "C0BVDE5R562"
SLACK_POST_URL = "https://slack.com/api/chat.postMessage"

# SLACK_BOT_TOKEN is unconditionally Tier-1-stripped from every subprocess the
# gateway spawns (tools/environments/local.py's _ALWAYS_STRIP_KEYS — same
# treatment as GITHUB_TOKEN), so a cron-run `--post-full` never sees it via
# os.environ. Mirrors watchdog-poll.py's resolve_secret() fallback: inherited
# env first (covers a manual run), else the encrypted secrets cache.
SECRETS_RUN = Path.home() / ".local" / "bin" / "secrets-run"
SLACK_TOKEN_REF = "op://hermes/slack/bot-token"

# Emoji map for the Block Kit overview — plain_text/mrkdwn render emoji
# shortcodes, not unicode glyphs (those are sideclaw's own .txt rendering).
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

# Recommendations worth a morning-briefing line.
QUIET = {"watch", "close"}

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


def _human_queue(data: dict[str, Any] | None) -> list[dict[str, Any]]:
    """`data.humanQueue` as a list of dicts, tolerant of the key being absent
    (an older sideclaw) or malformed — never raises."""
    if not data:
        return []
    raw = data.get("humanQueue")
    if not isinstance(raw, list):
        return []
    return [e for e in raw if isinstance(e, dict) and e.get("id") is not None]


def _is_needs_you(agent: dict[str, Any]) -> bool:
    return agent.get("state") == "needs_you"


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


def _needs_you_lines(cur: dict[str, Any]) -> list[str]:
    """Plain-text 'Needs you' block for the briefing: one line per
    human-queue entry, question first, the proposed command (if any) after
    it. Empty list when the queue is empty."""
    queue = _human_queue(cur)
    if not queue:
        return []
    lines = ["*Needs you* (human queue)"]
    for entry in queue:
        question = (entry.get("question") or "?").strip()
        cmd = (entry.get("cmd") or "").strip()
        line = f"⚠ {question}"
        if cmd:
            line += f" — `{cmd}`"
        lines.append(line)
    return lines


def _human_queue_block(cur: dict[str, Any]) -> dict[str, Any] | None:
    """Block Kit `section` for the human queue, or None when it is empty.
    Question and command are attacker-influenced text (an agent wrote the
    ask) — escaped and truncated like every other agent-derived string."""
    queue = _human_queue(cur)
    if not queue:
        return None
    lines = [":raising_hand: *Needs you* — human queue on the mini"]
    for entry in queue:
        question = _truncate(_escape((entry.get("question") or "?").strip()), STANDING_MAX)
        cmd = _truncate(_escape((entry.get("cmd") or "").strip()), BLOCKER_MAX)
        line = f"• {question}"
        if cmd:
            line += f"\n    ↳ `{cmd}`"
        lines.append(line)
    lines.append("_drain with `make human-queue` on the MacBook_")
    text = _truncate("\n".join(lines), SECTION_TEXT_MAX)
    return {"type": "section", "text": {"type": "mrkdwn", "text": text}}


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
    if recommendation == "answer" or recommendation == "needs_you":
        return 0
    if recommendation in ("ship", "merge", "review"):
        return 1
    return 2


def _agent_priority(agent: dict[str, Any]) -> int:
    """A blocked agent sorts with `answer` whatever its recommendation says."""
    if _is_needs_you(agent):
        return 0
    return _priority(agent.get("recommendation"))


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
    hq = len(_human_queue(cur))
    if hq:
        text += f" · {hq} human-queue"
    return _truncate(text, HEADER_TEXT_MAX)


def _blocks_footer_text(cur: dict[str, Any]) -> str:
    overview = cur.get("overview") or {}
    age = _fmt_age_ms(overview.get("ageMs"))
    model = overview.get("model") or "?"
    hhmm = _fmt_hhmm(overview.get("generatedAt"))
    return f"overview {age} old · {model} · {hhmm}"


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


def render_slack_blocks(cur: dict[str, Any]) -> list[dict[str, Any]]:
    """Block Kit body for the on-demand `--post-full` overview. Pure — same
    `cur` shape as render_briefing().

    Shows every agent with a recommendation, grouped by project. Projects
    are sorted with any `answer` agent first, then ship/merge/review, then
    the rest; agents within a project use the same order. Capped at
    BLOCKS_MAX total blocks — lowest-priority projects are dropped first,
    replaced by a trailing `… and N more projects` context block."""
    project_chunks: list[tuple[int, dict[str, Any]]] = []
    for project in cur.get("projects") or []:
        shown = [a for a in (project.get("agents") or []) if a.get("recommendation")]
        if not shown:
            continue
        shown.sort(key=lambda a: _agent_priority(a))
        priority = min(_agent_priority(a) for a in shown)
        block = _project_section_block(project.get("name") or "?", project.get("git"), shown)
        project_chunks.append((priority, block))

    project_chunks.sort(key=lambda item: item[0])
    all_blocks = [b for _, b in project_chunks]
    # The human queue outranks every project: it is the one thing only a
    # present human can move, so it is never the block that gets dropped.
    hq_block = _human_queue_block(cur)
    if hq_block is not None:
        all_blocks.insert(0, hq_block)

    header_block = {"type": "header", "text": {"type": "plain_text", "text": _blocks_header_text(cur)}}
    footer_block = {"type": "context", "elements": [{"type": "mrkdwn", "text": _blocks_footer_text(cur)}]}

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
    lines.extend(_needs_you_lines(cur))
    for project in cur.get("projects") or []:
        pname = project.get("name") or "?"
        for a in project.get("agents") or []:
            rec = a.get("recommendation")
            if (not rec or rec in QUIET) and not _is_needs_you(a):
                continue
            title = a.get("title") or "?"
            standing = (a.get("standing") or "").strip()
            blocker = (a.get("blocker") or "").strip()
            lines.append(f"{pname} · {rec} · {title} · {standing} · {blocker}")

    if len(lines) > BRIEFING_MAX_LINES:
        overflow = len(lines) - (BRIEFING_MAX_LINES - 1)
        lines = lines[: BRIEFING_MAX_LINES - 1] + [f"… and {overflow} more"]

    return "\n".join(lines)


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
        blocks = render_slack_blocks(cur)
        fallback = render_briefing(cur)
        if not post_blocks(_channel(), blocks, fallback, token):
            print("agents-overview: --post-full slack post failed", file=sys.stderr)
            return 1
        print(
            f"agents-overview: posted full overview ({len(blocks)} blocks) to {_channel()}",
            file=sys.stderr,
        )
        return 0

    print("usage: agents-overview.py --briefing | --json | --post-full", file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main())
