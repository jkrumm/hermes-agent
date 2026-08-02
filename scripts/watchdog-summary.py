"""Watchdog summary — read-only snapshot of currently open watchdog items.

Emits a compact block consumed by briefing-context.py and the morning
briefing prompt's Infrastructure section. Does not mutate state.

Source of truth: ~/SourceRoot/hermes-agent/scripts/watchdog-summary.py
"""

from __future__ import annotations

import datetime as dt
import json
import sqlite3
import sys
from pathlib import Path

DB_PATH = Path.home() / ".hermes" / "watchdog.db"

# "Overnight" for the morning briefing: a dispatch that finished within this
# many hours of the poll is still worth mentioning; older ones have already
# been seen (delivered into their origin thread by dispatch-sweep.py, or
# folded into a watchdog reminder) and would just be noise here.
DISPATCH_RECENT_HOURS = 18


def fmt_age(now: dt.datetime, iso: str) -> str:
    when = dt.datetime.fromisoformat(iso)
    secs = (now - when).total_seconds()
    if secs < 3600:
        return f"{int(secs / 60)}m"
    if secs < 86400:
        return f"{int(secs / 3600)}h"
    return f"{int(secs / 86400)}d"


def _dispatch_outcome_note(status: str, verdict_json: str | None) -> str:
    """Same rendering intent as watchdog-poll.py's _dispatch_summary — kept as
    its own small copy rather than a shared import, matching this repo's
    existing convention of independent, self-contained cron scripts."""
    if status in ("failed", "interrupted"):
        return status
    if not verdict_json:
        return "done, no verdict"
    try:
        v = json.loads(verdict_json)
    except json.JSONDecodeError:
        return "done, verdict unreadable"
    if not isinstance(v, dict):
        return "done, verdict unreadable"
    if v.get("degraded"):
        return "degraded (tool failure, not a finding)"
    return (v.get("summary") or "").strip() or "done, no summary"


def emit_dispatches(conn: sqlite3.Connection, now: dt.datetime) -> None:
    """Dispatch-bridge projection (Phase 3, docs/dispatch-bridge.md § 'Morning
    briefing' row): what's still running, and what landed overnight. Emits
    nothing at all -- not even an empty-bracket block -- when there is
    nothing to say, so an ordinary morning with an idle dispatch bridge adds
    zero lines to the briefing prompt. Conservative: any failure to read the
    dispatches table (doesn't exist yet) is treated as "nothing to project,"
    matching this script's read-only, never-mutating contract.
    """
    try:
        open_rows = conn.execute(
            "SELECT repo, tier, job_id, status, created_at FROM dispatches "
            "WHERE status IN ('queued','running') ORDER BY created_at"
        ).fetchall()
        cutoff = (now - dt.timedelta(hours=DISPATCH_RECENT_HOURS)).isoformat()
        recent_rows = conn.execute(
            "SELECT repo, tier, job_id, status, verdict_json, finished_at FROM dispatches "
            "WHERE finished_at IS NOT NULL AND finished_at >= ? ORDER BY finished_at DESC",
            (cutoff,),
        ).fetchall()
    except sqlite3.OperationalError:
        return  # dispatches table doesn't exist yet -- nothing to project

    if not open_rows and not recent_rows:
        return

    if open_rows:
        print("DISPATCHES_OPEN=[")
        for r in open_rows:
            age = fmt_age(now, r["created_at"])
            print(f"  - {r['repo']} (tier {r['tier']}, {r['status']}) — running {age} — job {r['job_id'][:8]}")
        print("]")

    if recent_rows:
        print("DISPATCHES_RECENT=[")
        for r in recent_rows:
            age = fmt_age(now, r["finished_at"])
            note = _dispatch_outcome_note(r["status"], r["verdict_json"])
            print(f"  - {r['repo']} (tier {r['tier']}) — finished {age} ago — {note}")
        print("]")


def main() -> int:
    if not DB_PATH.exists():
        print("WATCHDOG_AVAILABLE=false")
        return 0

    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    now = dt.datetime.now(dt.timezone.utc)

    open_rows = conn.execute(
        "SELECT source, external_id, title, url, first_seen, notified_at, reminder_count "
        "FROM events WHERE resolved_at IS NULL AND notified_at IS NOT NULL "
        "ORDER BY source, first_seen"
    ).fetchall()

    week_ago = (now - dt.timedelta(days=7)).isoformat()
    resolved_7d = conn.execute(
        "SELECT source, COUNT(*) AS n FROM events "
        "WHERE resolved_at IS NOT NULL AND resolved_at >= ? "
        "GROUP BY source ORDER BY source",
        (week_ago,),
    ).fetchall()

    print("WATCHDOG_AVAILABLE=true")
    if not open_rows:
        print("WATCHDOG_OPEN=[]")
    else:
        print("WATCHDOG_OPEN=[")
        for r in open_rows:
            age = fmt_age(now, r["first_seen"])
            url_part = f" {r['url']}" if r["url"] else ""
            rc = r["reminder_count"] or 0
            rc_part = f" (reminders={rc})" if rc else ""
            print(f"  - [{r['source']}] {r['title']} (open {age}){rc_part}{url_part}")
        print("]")

    if not resolved_7d:
        print("WATCHDOG_RESOLVED_7D=[]")
    else:
        print("WATCHDOG_RESOLVED_7D=[")
        for r in resolved_7d:
            print(f"  - {r['source']}: {r['n']}")
        print("]")

    emit_dispatches(conn, now)
    conn.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
