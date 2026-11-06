#!/usr/bin/env python3
"""usage-weekly-report — cron entry point (no_agent, Monday): print last week's usage report.

usage-tracker's weekly LaunchAgent (Monday 07:00) writes one Markdown file per ISO
week; this prints the file for the week that just ended and nothing else, so the
cron output keeps the full text; it is also published to the ntfy topic `updates`
(the publish helper clips to ntfy's body cap). A missing file is one line saying so, never silence:
the agent not having run is the thing worth hearing about.
"""

import datetime
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import ntfy_notify  # noqa: E402

REPORTS_DIR = os.path.expanduser(
    os.environ.get("USAGE_REPORTS_DIR", "~/.local/share/usage-tracker/reports")
)


def last_iso_week(today: datetime.date) -> str:
    year, week, _ = (today - datetime.timedelta(days=7)).isocalendar()
    return f"{year}-W{week:02d}"


def main() -> int:
    week = last_iso_week(datetime.date.today())
    path = os.path.join(REPORTS_DIR, f"{week}.md")
    if not os.path.isfile(path):
        text = f"usage weekly report {week}: no report file (the usage-tracker report agent did not write it)"
    else:
        with open(path, encoding="utf-8") as f:
            text = f.read().strip()
    print(text)
    try:
        ntfy_notify.publish("updates", "Usage weekly", text)
    except ntfy_notify.NtfyError as e:
        print(f"usage-weekly-report: {e}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
