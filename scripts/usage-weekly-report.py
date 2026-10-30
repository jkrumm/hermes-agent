#!/usr/bin/env python3
"""usage-weekly-report — cron entry point (no_agent, Monday): print last week's usage report.

usage-tracker's weekly LaunchAgent (Monday 07:00) writes one Markdown file per ISO
week; this prints the file for the week that just ended and nothing else, so the
cron delivers it verbatim. A missing file is one line saying so, never silence:
the agent not having run is the thing worth hearing about.
"""

import datetime
import os
import sys

REPORTS_DIR = os.path.expanduser(
    os.environ.get("USAGE_REPORTS_DIR", "~/.local/share/usage-tracker/reports")
)
MAX_CHARS = 35000  # Slack's message ceiling is 40k; leave room


def last_iso_week(today: datetime.date) -> str:
    year, week, _ = (today - datetime.timedelta(days=7)).isocalendar()
    return f"{year}-W{week:02d}"


def main() -> int:
    week = last_iso_week(datetime.date.today())
    path = os.path.join(REPORTS_DIR, f"{week}.md")
    if not os.path.isfile(path):
        print(f"usage weekly report {week}: no report file (the usage-tracker report agent did not write it)")
        return 0
    with open(path, encoding="utf-8") as f:
        text = f.read().strip()
    if len(text) > MAX_CHARS:
        text = text[:MAX_CHARS].rstrip() + f"\n\n(truncated; full report: {week}.md in the reports directory)"
    print(text)
    return 0


if __name__ == "__main__":
    sys.exit(main())
