#!/usr/bin/env python3
"""Regression guard for the two ways the watchdog silently lost an alert.

Run: ~/.hermes/hermes-agent/venv/bin/python3 tests/test_watchdog_delivery.py

BUG 1 — a notification stamped during quiet hours was BURNED, not deferred.
`_run_poll` marked rows notified unconditionally, then `compose_slack_body()`
returned "" for quiet/vacation. With a cooldown at or near 24h that is not a
delayed message but a permanently silent one: the next eligible emit lands at the
same wall-clock hour, back inside the same window, forever.

BUG 2 — `upsert_grouped` never cleared `resolved_at`. Once `sweep_stale_grouped()`
retired a signature after 7 idle days, a recurrence kept ticking
`last_reminder_at` on a row that every `resolved_at IS NULL` reader ignores.

Both fired together on 2026-08-24: a Slack socket died at 03:44, its `hermes_log`
signature (24h cooldown, resolved back in June) produced a 48-hour ~17,300-line
reconnect flood, and the digest never mentioned it once.
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
    tmp = Path(tempfile.mkdtemp(prefix="wd-test-")) / "watchdog.db"
    wp.DB_PATH = tmp
    return wp.db_connect()


def observed(external_id: str = "sig-a", title: str = "something broke") -> list[dict]:
    return [{"external_id": external_id, "title": title, "url": "", "payload": {}}]


def grouped(external_id: str = "sig-a", count: int = 5) -> list[dict]:
    return [{"external_id": external_id, "title": "slack_bolt: Failed to connect",
             "url": "", "payload": {}, "count": count}]


def notified_at(conn, external_id: str = "sig-a"):
    row = conn.execute("SELECT notified_at FROM events WHERE external_id=?", (external_id,)).fetchone()
    return row["notified_at"] if row else None


print("\n1. reconcile — quiet hours defer rather than burn")
conn = fresh_db()
t0 = dt.datetime(2026, 8, 24, 3, 44, tzinfo=dt.timezone.utc)

new, rem, res = wp.reconcile(conn, "uk", observed(), t0, 0, 6, deliver=False)
check("no NEW emitted while suppressed", len(new), 0)
check("row exists anyway", conn.execute("SELECT COUNT(*) c FROM events").fetchone()["c"], 1)
check("notified_at NOT stamped", notified_at(conn), None)

# 07:00, quiet window over — the backlog must fire now.
t1 = t0 + dt.timedelta(hours=3, minutes=16)
new, rem, res = wp.reconcile(conn, "uk", observed(), t1, 0, 6, deliver=True)
check("fires as NEW on first delivering poll", len(new), 1)
check("notified_at stamped once delivered", notified_at(conn) is not None, True)

# A reminder must likewise not consume its anchor while suppressed.
t2 = t1 + dt.timedelta(hours=7)
new, rem, res = wp.reconcile(conn, "uk", observed(), t2, 0, 6, deliver=False)
check("no reminder emitted while suppressed", len(rem), 0)
anchor = conn.execute("SELECT last_reminder_at FROM events WHERE external_id='sig-a'").fetchone()
check("reminder anchor untouched", anchor["last_reminder_at"], None)
new, rem, res = wp.reconcile(conn, "uk", observed(), t2, 0, 6, deliver=True)
check("reminder fires on the next delivering poll", len(rem), 1)
conn.close()

print("\n2. upsert_grouped — quiet hours defer rather than burn")
conn = fresh_db()
out = wp.upsert_grouped(conn, "hermes_log", grouped(), t0, flap_threshold=1, cooldown_hours=24,
                        deliver=False)
check("no emission while suppressed", len(out), 0)
check("row recorded anyway", conn.execute("SELECT COUNT(*) c FROM events").fetchone()["c"], 1)
check("notified_at NOT stamped", notified_at(conn), None)

out = wp.upsert_grouped(conn, "hermes_log", grouped(), t1, flap_threshold=1, cooldown_hours=24,
                        deliver=True)
check("emits on the first delivering poll", len(out), 1)
conn.close()

print("\n3. upsert_grouped — a swept signature re-opens when it recurs")
conn = fresh_db()
june = dt.datetime(2026, 6, 8, 23, 30, tzinfo=dt.timezone.utc)
wp.upsert_grouped(conn, "hermes_log", grouped(), june, flap_threshold=1, cooldown_hours=24)

# 7+ idle days → the sweeper retires it, exactly as it did on 2026-06-23.
swept = wp.sweep_stale_grouped(conn, june + dt.timedelta(days=10))
check("sweeper resolved the idle row", swept, 1)

# The identical error returns two months later.
aug = dt.datetime(2026, 8, 24, 12, 0, tzinfo=dt.timezone.utc)
out = wp.upsert_grouped(conn, "hermes_log", grouped(), aug, flap_threshold=1, cooldown_hours=24)
row = conn.execute("SELECT resolved_at, reminder_count, first_seen FROM events "
                   "WHERE external_id='sig-a'").fetchone()
check("resolved_at cleared on recurrence", row["resolved_at"], None)
check("visible to `resolved_at IS NULL` readers", row["resolved_at"] is None, True)
check("re-emitted", len(out), 1)
check("first_seen re-anchored to the recurrence", row["first_seen"], aug.isoformat())
check("reminder_count reset", row["reminder_count"], 0)
conn.close()

print("\n4. delivering polls are unchanged (the default path)")
conn = fresh_db()
new, rem, res = wp.reconcile(conn, "uk", observed(), t0, 0, 6)
check("reconcile still emits NEW by default", len(new), 1)
out = wp.upsert_grouped(conn, "hermes_log", grouped(), t0, flap_threshold=1, cooldown_hours=24)
check("upsert_grouped still emits by default", len(out), 1)
conn.close()

print("\n5. resolution still tracked while suppressed")
conn = fresh_db()
wp.reconcile(conn, "uk", observed(), t0, 0, 6, deliver=True)
# The condition clears during quiet hours — the row must still close.
wp.reconcile(conn, "uk", [], t0 + dt.timedelta(hours=1), 0, 6, deliver=False)
row = conn.execute("SELECT resolved_at FROM events WHERE external_id='sig-a'").fetchone()
check("disappearance still resolves under suppression", row["resolved_at"] is not None, True)
conn.close()

print()
if failures:
    print(f"{len(failures)} failure(s):")
    for f in failures:
        print(f"  - {f}")
    sys.exit(1)
print("all cases as expected")
