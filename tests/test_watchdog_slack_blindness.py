#!/usr/bin/env python3
"""Regression guard for the Slack poll that failed silently.

Run: ~/.hermes/hermes-agent/venv/bin/python3 tests/test_watchdog_slack_blindness.py

On 2026-09-07 argo's Slack *read* token was repointed at a newly created app that
was a member of no channel, so every `conversations.history` call 500'd. The
watchdog never noticed: `poll_slack_messages` returned `[], since_ts` on any HTTP
error — byte-identical to "no new messages" — so `slack_alert` and `slack_update`
went blind for hours while every run exited 0 and pinged the UptimeKuma heartbeat.

The fix is a reported `ok` flag, a per-source consecutive-failure cursor, and a
non-zero exit once the streak reaches SLACK_FAIL_STREAK_ALERT. All three are
checked here, plus the two things that must NOT change: a single blip stays
quiet, and one success clears the streak.
"""

import datetime as dt
import importlib.util
import sqlite3
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
spec = importlib.util.spec_from_file_location("watchdog_poll", REPO / "scripts" / "watchdog-poll.py")
wp = importlib.util.module_from_spec(spec)
spec.loader.exec_module(wp)

failures: list[str] = []


def check(name: str, got, want) -> None:
    if got == want:
        print(f"  ok   {name}")
    else:
        failures.append(f"{name}: got {got!r}, want {want!r}")
        print(f"  FAIL {name}: got {got!r}, want {want!r}")


def fresh_db() -> sqlite3.Connection:
    tmp = Path(tempfile.mkdtemp(prefix="wd-slack-test-")) / "watchdog.db"
    wp.DB_PATH = tmp
    return wp.db_connect()


ENV = {"HOMELAB_API_KEY": "test-key"}
NOW_ISO = "2026-09-07T10:00:00+00:00"


def with_http_get(result):
    """Swap wp.http_get for one returning ``result``; returns the original."""
    original = wp.http_get
    wp.http_get = lambda *a, **k: result
    return original


print("\n1. poll_slack_messages reports the failure instead of an empty channel")
original = with_http_get({"_error": "HTTP Error 500: Internal Server Error"})
msgs, latest, ok = wp.poll_slack_messages(ENV, "C0AS1LAUQ3C", "1788000000.000000")
check("no messages", msgs, [])
check("cursor not advanced", latest, "1788000000.000000")
check("ok is False", ok, False)

wp.http_get = lambda *a, **k: {"messages": [
    {"ts": "1788000100.000000", "text": "VPS edge 5xx rate"},
]}
msgs, latest, ok = wp.poll_slack_messages(ENV, "C0AS1LAUQ3C", "1788000000.000000")
check("success returns the message", len(msgs), 1)
check("success advances the cursor", latest, "1788000100.000000")
check("ok is True", ok, True)
wp.http_get = original

print("\n2. an empty channel is not a failure")
original = with_http_get({"messages": []})
_, _, ok = wp.poll_slack_messages(ENV, "C0AS1LAUQ3C", "1788000000.000000")
check("empty channel still ok", ok, True)
wp.http_get = original

print("\n3. cursor_get_int tolerates missing and junk values")
conn = fresh_db()
check("missing key", wp.cursor_get_int(conn, "nope"), 0)
wp.cursor_set(conn, "junk", "not-a-number", NOW_ISO)
check("non-numeric value", wp.cursor_get_int(conn, "junk"), 0)
wp.cursor_set(conn, "two", "2", NOW_ISO)
check("numeric value", wp.cursor_get_int(conn, "two"), 2)
conn.close()

print("\n4. the streak accumulates, and one success clears it")
conn = fresh_db()
check("clean at rest", wp.slack_poll_failure(conn), None)

for i in range(1, wp.SLACK_FAIL_STREAK_ALERT):
    wp.cursor_set(conn, "slack_alert_fail_streak", str(i), NOW_ISO)
    check(f"still quiet below threshold ({i})", wp.slack_poll_failure(conn), None)

wp.cursor_set(conn, "slack_alert_fail_streak", str(wp.SLACK_FAIL_STREAK_ALERT), NOW_ISO)
blind = wp.slack_poll_failure(conn)
check("reports at threshold", blind is not None, True)
check("names the source", "slack_alert" in (blind or ""), True)

wp.cursor_set(conn, "slack_alert_fail_streak", "0", NOW_ISO)
check("one success clears it", wp.slack_poll_failure(conn), None)
conn.close()

print("\n5. _run_poll writes the streak, and main() exits non-zero once blind")
conn = fresh_db()
original = with_http_get({"_error": "HTTP Error 500: Internal Server Error"})
# Seed the cursors so the first-run branch (which only primes them) is past.
wp.cursor_set(conn, "slack_alert_ts", "1788000000.000000", NOW_ISO)
wp.cursor_set(conn, "slack_update_ts", "1788000000.000000", NOW_ISO)
now = dt.datetime(2026, 9, 7, 10, 0, tzinfo=dt.timezone.utc)

# Isolate the Slack leg: every other source is a live network/ssh call.
wp.poll_uk = lambda *a, **k: []
wp.poll_docker = lambda *a, **k: []
wp.poll_op_refs = lambda *a, **k: ([], True)
wp.poll_github = lambda *a, **k: {"github_pr": [], "github_issue": []}
wp.poll_hermes_cron = lambda *a, **k: []
wp.poll_stray_skills = lambda *a, **k: []
wp.poll_hermes_logs = lambda *a, **k: []

for expected in range(1, wp.SLACK_FAIL_STREAK_ALERT + 1):
    wp._run_poll(conn, now, ENV, deliver=False)
    check(f"streak after {expected} failed poll(s)",
          wp.cursor_get_int(conn, "slack_alert_fail_streak"), expected)

check("blind after the threshold is reached", wp.slack_poll_failure(conn) is not None, True)
conn.commit()

# main() must turn that into a non-zero exit so watchdog-slack.py withholds the
# UptimeKuma heartbeat. Stub the poll itself — the wiring is what is under test.
wp._run_poll = lambda *a, **k: ([], [], [])
wp.load_env = lambda: ENV
wp.load_state = lambda: {}
check("main() exits 1 while blind", wp.main(["--slack-body"]), 1)

for src in ("slack_alert", "slack_update"):
    wp.cursor_set(conn, f"{src}_fail_streak", "0", NOW_ISO)
conn.commit()
check("main() exits 0 once reads recover", wp.main(["--slack-body"]), 0)

conn.close()
wp.http_get = original

print()
if failures:
    print(f"{len(failures)} failure(s):")
    for f in failures:
        print(f"  - {f}")
    sys.exit(1)
print("all cases as expected")
