#!/usr/bin/env python3
"""Agents overview — read-only summary of every Claude Code / herdr agent
sideclaw is tracking, for Slack pings and the morning briefing.

Talks to sideclaw's overview endpoints (`http://localhost:7705`, a local
LaunchAgent — see `skills/agents/SKILL.md`):

  GET  /api/overview          -> {ok, data: {generatedAt, summary, projects[], ...}}
  POST /api/jobs {"tool":"overview"} -> {ok, job:{id, status, ...}}   -- triggers
       a fresh LLM pass; poll GET /api/jobs/<id> until status is
       done|failed, then re-GET /api/overview for the merged result.

This script only reads. It never sends keys to a herdr pane and never
dispatches — that is scripts/hermes-cc.sh's job.

Source of truth: ~/SourceRoot/hermes-agent/scripts/agents-overview.py
~/.hermes/scripts/ is itself a symlink to this directory (see make setup).
"""

from __future__ import annotations

import json
import os
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

STATE_PATH = Path.home() / ".hermes" / "agents-overview-state.json"

DEFAULT_BASE = "http://localhost:7705"

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

# Recommendations worth a Slack ping / a morning-briefing line.
ACTIONABLE = {"answer", "ship", "merge", "review"}
QUIET = {"watch", "close"}

SLACK_MAX_LINES = 25
BRIEFING_MAX_LINES = 20


def _base_url() -> str:
    return os.environ.get("HERMES_AGENTS_SIDECLAW_BASE", DEFAULT_BASE)


def fetch(base: str, timeout_s: int = 10) -> dict[str, Any]:
    """GET /api/overview and return the `data` object. Raises on any
    transport/shape failure — callers decide how to degrade."""
    req = urllib.request.Request(f"{base}/api/overview")
    with urllib.request.urlopen(req, timeout=timeout_s) as resp:
        payload = json.loads(resp.read().decode())
    if not payload.get("ok"):
        raise RuntimeError(f"overview fetch not ok: {payload}")
    return payload["data"]


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
    makes watch<->working churn and standing-only edits invisible here."""
    prev_idx = _agent_index(prev)
    cur_idx = _agent_index(cur)
    changes: list[str] = []

    for aid, info in cur_idx.items():
        if aid not in prev_idx:
            changes.append(
                f"new: {info['project']} — {info['title']} ({info['recommendation']})"
            )
            continue
        old_rec = prev_idx[aid]["recommendation"]
        new_rec = info["recommendation"]
        if old_rec != new_rec:
            changes.append(
                f"changed: {info['project']} — {info['title']} "
                f"({old_rec} → {new_rec})"
            )

    for aid, info in prev_idx.items():
        if aid not in cur_idx:
            changes.append(f"gone: {info['project']} — {info['title']}")

    return changes


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
        STATE_PATH.write_text(json.dumps(cur))
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
        cur = refresh(base)
        if cur is None:
            try:
                cur = fetch(base)
            except Exception:
                # Sideclaw unreachable end to end — degrade silently, never
                # kill the calling cron. State is left untouched so the next
                # successful run diffs against the last known-good snapshot.
                return 0
        body = render_slack(cur, delta(prev, cur))
        if body:
            print(body)
        _save_state(cur)
        return 0

    print("usage: agents-overview.py --slack-body | --briefing | --json", file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main())
