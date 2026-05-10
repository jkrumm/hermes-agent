"""Coverage block: full TickTick backlog + all open GitHub items.

Emits structured key=value blocks the morning + evening briefing prompts
parse to surface dateless tasks and fresh GitHub captures that
`/summary.ticktick` (date-bound only) and watchdog (stale-only) miss.

Called from briefing-context.py as a subprocess. Output gets appended to
the prompt under `## Script Output`.

Blocks emitted:
  COVERAGE_AVAILABLE=true|false
  TICKTICK_BACKLOG=[...]              # one line per project, with counts
  TICKTICK_HIGH_PRIO_DATELESS=[...]   # P5 tasks with no due date — would
                                      # vanish from /summary otherwise
  GITHUB_OPEN_BY_REPO=[...]           # one line per repo with open items
  GITHUB_FRESH_48H=[...]              # items created in last 48h
  GITHUB_TOTAL=<N>                    # rolled-up count

Source of truth: ~/SourceRoot/hermes-agent/scripts/briefing-coverage.py
Symlinked — ~/.hermes/scripts/ → ~/SourceRoot/hermes-agent/scripts/
"""

from __future__ import annotations

import datetime as dt
import json
import os
import subprocess
import sys
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

API_BASE = "https://argo.jkrumm.com/api"
GH_OWNER = "jkrumm"
HTTP_TIMEOUT = 8
GH_TIMEOUT = 20
FRESH_HOURS = 48


def load_env() -> dict[str, str]:
    env_path = Path.home() / ".hermes" / ".env"
    out: dict[str, str] = {}
    if not env_path.exists():
        return out
    for line in env_path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        out[k.strip()] = v.strip().strip('"').strip("'")
    return out


def http_get_json(url: str, headers: dict[str, str]) -> Any | None:
    try:
        req = urllib.request.Request(url, headers=headers)
        with urllib.request.urlopen(req, timeout=HTTP_TIMEOUT) as r:
            return json.loads(r.read())
    except (urllib.error.URLError, urllib.error.HTTPError, json.JSONDecodeError, TimeoutError):
        return None


def gh_search(kind: str) -> list[dict[str, Any]]:
    """kind: 'prs' or 'issues'"""
    fields = "title,repository,url,number,createdAt,updatedAt"
    if kind == "prs":
        fields += ",isDraft"
    try:
        res = subprocess.run(
            ["gh", "search", kind, "--owner", GH_OWNER, "--state", "open",
             "--json", fields, "--limit", "100"],
            capture_output=True, text=True, timeout=GH_TIMEOUT,
        )
        if res.returncode != 0:
            return []
        return json.loads(res.stdout or "[]")
    except (subprocess.TimeoutExpired, json.JSONDecodeError, FileNotFoundError):
        return []


def parse_iso(s: str | None) -> dt.datetime | None:
    if not s:
        return None
    try:
        return dt.datetime.fromisoformat(s.replace("Z", "+00:00"))
    except (ValueError, AttributeError):
        return None


def hours_ago(d: dt.datetime | None, now: dt.datetime) -> float | None:
    if d is None:
        return None
    return (now - d).total_seconds() / 3600


def fmt_age(hours: float | None) -> str:
    if hours is None:
        return "?"
    if hours < 24:
        return f"{int(hours)}h"
    days = hours / 24
    if days < 7:
        return f"{int(days)}d"
    return f"{int(days / 7)}w"


def main() -> None:
    env = load_env()
    api_key = env.get("HOMELAB_API_KEY") or os.environ.get("HOMELAB_API_KEY", "")
    if not api_key:
        print("COVERAGE_AVAILABLE=false")
        print("COVERAGE_REASON=missing HOMELAB_API_KEY")
        return

    headers = {"Authorization": f"Bearer {api_key}"}
    now = dt.datetime.now(dt.timezone.utc)
    fresh_threshold = now - dt.timedelta(hours=FRESH_HOURS)

    # --- TickTick: full backlog per project ---
    projects_resp = http_get_json(f"{API_BASE}/ticktick/projects", headers)
    if not isinstance(projects_resp, dict) or "data" not in projects_resp:
        print("COVERAGE_AVAILABLE=false")
        print("COVERAGE_REASON=ticktick projects fetch failed")
        return

    backlog_lines: list[str] = []
    high_prio_dateless: list[str] = []
    for p in projects_resp["data"]:
        if p.get("closed"):
            continue
        pid, pname = p.get("id"), p.get("name", "?")
        data = http_get_json(f"{API_BASE}/ticktick/project/{pid}/data", headers)
        inner = data.get("data") if isinstance(data, dict) else None
        tasks = inner.get("tasks", []) if isinstance(inner, dict) else []
        active = [t for t in tasks if t.get("status") == 0]
        dateless = [t for t in active if not t.get("dueDate")]
        high_prio = [t for t in active if t.get("priority") == 5]
        high_prio_no_date = [t for t in high_prio if not t.get("dueDate")]

        flags: list[str] = []
        if dateless:
            flags.append(f"{len(dateless)} dateless")
        if high_prio:
            flags.append(f"{len(high_prio)} P5")
        flag_str = f" ({', '.join(flags)})" if flags else ""
        backlog_lines.append(f"  - {pname}: {len(active)} active{flag_str}")

        for t in high_prio_no_date[:3]:
            title = (t.get("title") or "?")[:80]
            high_prio_dateless.append(f"  - {pname}: {title} (P5, no due-date)")

    print("COVERAGE_AVAILABLE=true")
    if backlog_lines:
        print("TICKTICK_BACKLOG=[")
        for line in backlog_lines:
            print(line)
        print("]")
    if high_prio_dateless:
        print("TICKTICK_HIGH_PRIO_DATELESS=[")
        for line in high_prio_dateless:
            print(line)
        print("]")

    # --- GitHub: all open issues + PRs across owner ---
    prs = [p for p in gh_search("prs") if not p.get("isDraft")]
    issues = gh_search("issues")
    by_repo: dict[str, dict[str, int]] = {}
    fresh: list[str] = []

    for kind, items in (("PR", prs), ("issue", issues)):
        for it in items:
            repo_obj = it.get("repository") or {}
            repo = repo_obj.get("nameWithOwner") or repo_obj.get("name") or "?"
            repo_short = repo.split("/", 1)[-1]
            num = it.get("number")
            title = (it.get("title") or "?")[:70]
            created = parse_iso(it.get("createdAt"))
            updated = parse_iso(it.get("updatedAt"))
            age_str = fmt_age(hours_ago(created, now))

            slot = by_repo.setdefault(repo_short, {"PR": 0, "issue": 0})
            slot[kind] += 1

            if created and created > fresh_threshold:
                fresh.append(f"  - {repo_short}#{num} {kind}: {title} (created {age_str} ago)")
            elif updated and updated > fresh_threshold and (not created or created <= fresh_threshold):
                fresh.append(f"  - {repo_short}#{num} {kind}: {title} (updated {fmt_age(hours_ago(updated, now))} ago)")

    if by_repo:
        print("GITHUB_OPEN_BY_REPO=[")
        for repo_short, counts in sorted(by_repo.items()):
            parts: list[str] = []
            if counts["PR"]:
                parts.append(f"{counts['PR']} PR" + ("s" if counts["PR"] > 1 else ""))
            if counts["issue"]:
                parts.append(f"{counts['issue']} issue" + ("s" if counts["issue"] > 1 else ""))
            print(f"  - {repo_short}: {', '.join(parts)}")
        print("]")
    print(f"GITHUB_TOTAL={len(prs)} PR{'s' if len(prs) != 1 else ''}, {len(issues)} issue{'s' if len(issues) != 1 else ''}")

    if fresh:
        print(f"GITHUB_FRESH_{FRESH_HOURS}H=[")
        for line in fresh:
            print(line)
        print("]")


if __name__ == "__main__":
    main()
