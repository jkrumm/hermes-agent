"""Watchdog summary — read-only snapshot of currently open watchdog items.

Emits a compact block consumed by briefing-context.py and the morning
briefing prompt's Infrastructure section. Does not mutate state.

Source of truth: ~/SourceRoot/claude-local/hermes/scripts/watchdog-summary.py
"""

from __future__ import annotations

import datetime as dt
import json
import sqlite3
import sys
from pathlib import Path

DB_PATH = Path.home() / ".hermes" / "watchdog.db"


def fmt_age(now: dt.datetime, iso: str) -> str:
    when = dt.datetime.fromisoformat(iso)
    secs = (now - when).total_seconds()
    if secs < 3600:
        return f"{int(secs / 60)}m"
    if secs < 86400:
        return f"{int(secs / 3600)}h"
    return f"{int(secs / 86400)}d"


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

    conn.close()

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
    return 0


if __name__ == "__main__":
    sys.exit(main())
