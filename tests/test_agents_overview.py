"""Regression suite for scripts/agents-overview.py's pure functions.

Covers: delta() only reacts to a recommendation actually changing (new
agent, changed recommendation, disappeared agent) and ignores everything
else that churns run to run (state, standing wording); render_slack()'s
silence rule (quiet whenever `changes` is empty, full stop — a persistent,
unchanged `answer` item does NOT repost every cycle; the morning briefing
re-surfaces it daily instead) and its line cap; render_briefing()'s line
cap and its watch/close exclusion; and the unavailable-degrades-gracefully
path for both CLI modes.

No network, no sideclaw, no state file — every case builds its fixtures
in-memory and calls the module's functions directly (or monkeypatches
fetch/refresh for the CLI-level unavailable cases).

Run against the live tree:

    ~/.hermes/hermes-agent/venv/bin/python3 tests/test_agents_overview.py

Exit status is 0 only when every case matches.
"""

from __future__ import annotations

import importlib.util
import io
import sys
from contextlib import redirect_stdout
from pathlib import Path

_HERE = Path(__file__).resolve().parent
_spec = importlib.util.spec_from_file_location(
    "agents_overview", _HERE.parent / "scripts" / "agents-overview.py",
)
assert _spec and _spec.loader, "Failed to load agents-overview.py"
ao = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(ao)

failures: list[str] = []


def check(name: str, got, want) -> None:
    if got == want:
        print(f"  ok   {name}")
    else:
        failures.append(f"{name}: got {got!r}, want {want!r}")
        print(f"  FAIL {name}: got {got!r}, want {want!r}")


def check_true(name: str, cond: bool) -> None:
    check(name, bool(cond), True)


# --- fixtures --------------------------------------------------------------

def mk_agent(id_: str, title: str, recommendation: str | None,
             standing: str = "", blocker: str = "", state: str = "working") -> dict:
    return {
        "id": id_, "title": title, "state": state,
        "recommendation": recommendation, "standing": standing,
        "blocker": blocker, "confidence": "high",
    }


def mk_overview(projects: list[tuple[str, list[dict]]], summary: dict | None = None) -> dict:
    return {
        "summary": summary or {
            "needsYou": 0, "working": 0, "idle": 0, "stale": 0, "done": 0, "dispatch": 0,
        },
        "overview": {"generatedAt": 0, "model": "claude-haiku-4-5", "ageMs": 0},
        "projects": [{"name": name, "cwd": f"/repo/{name}", "git": None, "agents": agents}
                      for name, agents in projects],
        "warnings": [],
    }


# --- delta() -----------------------------------------------------------------

print("1. delta() — new agent with recommendation=answer")
prev = mk_overview([("repoA", [mk_agent("a1", "Fix bug", "watch")])])
cur = mk_overview([
    ("repoA", [mk_agent("a1", "Fix bug", "watch")]),
    ("repoB", [mk_agent("b1", "Ask about deploy", "answer")]),
])
changes = ao.delta(prev, cur)
check_true("new answer agent produces a change", any("repoB" in c and "answer" in c for c in changes))
check("exactly one change (only b1 is new)", len(changes), 1)

print("\n2. delta() — recommendation change on an existing agent")
prev = mk_overview([("repoA", [mk_agent("a1", "Fix bug", "watch")])])
cur = mk_overview([("repoA", [mk_agent("a1", "Fix bug", "ship")])])
changes = ao.delta(prev, cur)
check("one change recorded", len(changes), 1)
check_true("change names old and new recommendation", "watch" in changes[0] and "ship" in changes[0])

print("\n3. delta() — agent disappears")
prev = mk_overview([("repoA", [mk_agent("a1", "Fix bug", "watch")])])
cur = mk_overview([("repoA", [])])
changes = ao.delta(prev, cur)
check("one 'gone' change recorded", len(changes), 1)
check_true("gone change mentions the agent", "Fix bug" in changes[0])

print("\n4. delta() — watch<->working state churn is ignored")
prev = mk_overview([("repoA", [mk_agent("a1", "Long task", "watch", state="working")])])
cur = mk_overview([("repoA", [mk_agent("a1", "Long task", "watch", state="idle")])])
check("no changes for a state-only flip", ao.delta(prev, cur), [])

print("\n5. delta() — standing-wording-only change is ignored")
prev = mk_overview([("repoA", [mk_agent("a1", "Long task", "watch", standing="doing X")])])
cur = mk_overview([("repoA", [mk_agent("a1", "Long task", "watch", standing="now doing Y")])])
check("no changes for a standing-only edit", ao.delta(prev, cur), [])


# --- render_slack() ------------------------------------------------------

print("\n6. render_slack() — silence: no changes, no actionable items")
cur = mk_overview([("repoA", [mk_agent("a1", "Idle thing", "watch")])])
check("silent", ao.render_slack(cur, []), "")

print("\n7. render_slack() — silence: no changes, only a non-answer actionable item")
cur = mk_overview([("repoA", [mk_agent("a1", "Ready PR", "ship")])])
check("silent when nothing changed, regardless of a ship item", ao.render_slack(cur, []), "")

print("\n8. render_slack() — silence: a PERSISTENT 'answer' item with no changes")
# The rule that matters most: an unresolved question sitting there run after
# run must not repost every cycle just because it's still 'answer'. Only a
# change in `changes` (produced by delta()) should ever speak it again.
cur = mk_overview([("repoA", [mk_agent("a1", "Blocked Q", "answer", standing="waiting on you")])])
check("silent even with a live answer item if nothing changed", ao.render_slack(cur, []), "")

print("\n9. render_slack() — speaks: changes non-empty, with a live 'answer' item")
cur = mk_overview([("repoA", [mk_agent("a1", "Blocked Q", "answer", standing="waiting on you")])])
body = ao.render_slack(cur, ["new: repoA — Blocked Q (answer)"])
check_true("non-empty when changes is non-empty", body != "")
check_true("body names the project", "repoA" in body)
check_true("body names the agent title", "Blocked Q" in body)

print("\n9b. render_slack() — speaks: changes non-empty even with no actionable items")
cur = mk_overview([("repoA", [mk_agent("a1", "Idle thing", "watch")])])
check_true("non-empty when changes is non-empty", ao.render_slack(cur, ["new: repoA — Idle thing (watch)"]) != "")

print("\n10. render_slack() — line cap with 30 agents")
agents = [mk_agent(f"a{i}", f"Task {i}", "ship") for i in range(30)]
cur = mk_overview([("repoA", agents)])
body = ao.render_slack(cur, ["forced non-silence"])
lines = body.splitlines()
check_true(f"<= {ao.SLACK_MAX_LINES} lines (got {len(lines)})", len(lines) <= ao.SLACK_MAX_LINES)
check_true("overflow marker present", any(line.startswith("…") for line in lines))


# --- render_briefing() ---------------------------------------------------

print("\n11. render_briefing() — excludes watch/close, includes the rest")
cur = mk_overview([("repoA", [
    mk_agent("a1", "Watched task", "watch"),
    mk_agent("a2", "Closed task", "close"),
    mk_agent("a3", "Needs answer", "answer", standing="stuck", blocker="waiting on input"),
    mk_agent("a4", "Ready to merge", "merge"),
])])
text = ao.render_briefing(cur)
check_true("watch excluded", "Watched task" not in text)
check_true("close excluded", "Closed task" not in text)
check_true("answer included", "Needs answer" in text)
check_true("merge included", "Ready to merge" in text)

print("\n12. render_briefing() — line cap with 30 agents")
agents = [mk_agent(f"a{i}", f"Task {i}", "review") for i in range(30)]
cur = mk_overview([("repoA", agents)])
text = ao.render_briefing(cur)
lines = text.splitlines()
check_true(f"<= {ao.BRIEFING_MAX_LINES} lines (got {len(lines)})", len(lines) <= ao.BRIEFING_MAX_LINES)
check_true("overflow marker present", any(line.startswith("…") for line in lines))


# --- unavailable path (CLI level) -----------------------------------------

print("\n13. main(['--briefing']) degrades to one line when sideclaw is unreachable")
def _boom(base, timeout_s=10):
    raise ConnectionRefusedError("sideclaw down")

_orig_fetch = ao.fetch
ao.fetch = _boom
try:
    out = io.StringIO()
    with redirect_stdout(out):
        rc = ao.main(["--briefing"])
    check("exit 0", rc, 0)
    check("one-line unavailable message", out.getvalue().strip(), "agents overview unavailable")
finally:
    ao.fetch = _orig_fetch

print("\n14. main(['--slack-body']) degrades to silent exit 0 when sideclaw is unreachable")
_orig_fetch = ao.fetch
_orig_refresh = ao.refresh
_orig_load_state = ao._load_state
_orig_save_state = ao._save_state
ao.fetch = _boom
ao.refresh = lambda base, timeout_s=120: None
ao._load_state = lambda: None
saved = {}
ao._save_state = lambda cur: saved.setdefault("called", True)
try:
    out = io.StringIO()
    with redirect_stdout(out):
        rc = ao.main(["--slack-body"])
    check("exit 0", rc, 0)
    check("empty stdout", out.getvalue(), "")
    check("state not saved on total failure", saved.get("called", False), False)
finally:
    ao.fetch = _orig_fetch
    ao.refresh = _orig_refresh
    ao._load_state = _orig_load_state
    ao._save_state = _orig_save_state


print()
if failures:
    print(f"{len(failures)} failure(s):")
    for f in failures:
        print(f"  - {f}")
    sys.exit(1)
print("all cases as expected")
