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
import json
import time
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

print("\n14. main(['--slack-body']) — sideclaw unreachable: warns once per day, keeps the snapshot")
_orig_fetch = ao.fetch
_orig_fetch_agents = ao.fetch_agents
_orig_refresh = ao.refresh
_orig_load_state = ao._load_state
_orig_save_state = ao._save_state
ao.fetch = _boom
ao.fetch_agents = _boom
ao.refresh = lambda base, timeout_s=120: None
prev_state = {"fingerprint": "keep-me", "projects": []}
ao._load_state = lambda: dict(prev_state)
saved = {}
ao._save_state = lambda cur: saved.update(cur)
try:
    out = io.StringIO()
    with redirect_stdout(out):
        rc = ao.main(["--slack-body"])
    check("exit 0", rc, 0)
    check_true("warning line on stdout (delivered to #agents)", "sideclaw" in out.getvalue() and "unreachable" in out.getvalue())
    check_true("warned-on date stamped", saved.get(ao.UNREACHABLE_WARNED_KEY) == time.strftime("%Y-%m-%d"))
    check("last known-good fingerprint kept", saved.get("fingerprint"), "keep-me")
    # second run the same day: silent
    ao._load_state = lambda: dict(saved)
    saved2 = {}
    ao._save_state = lambda cur: saved2.setdefault("called", True)
    out2 = io.StringIO()
    with redirect_stdout(out2):
        rc2 = ao.main(["--slack-body"])
    check("second run exit 0", rc2, 0)
    check("second run the same day is silent", out2.getvalue(), "")
    check("second run does not rewrite state", saved2.get("called", False), False)
finally:
    ao.fetch = _orig_fetch
    ao.fetch_agents = _orig_fetch_agents
    ao.refresh = _orig_refresh
    ao._load_state = _orig_load_state
    ao._save_state = _orig_save_state

print("\n14b. unreachable_warning() — pure once-per-day gate")
check_true("no prior stamp -> warns", bool(ao.unreachable_warning(None, "2026-09-07", "http://x")))
check("same-day stamp -> silent", ao.unreachable_warning({ao.UNREACHABLE_WARNED_KEY: "2026-09-07"}, "2026-09-07", "http://x"), "")
check_true("older stamp -> warns again", bool(ao.unreachable_warning({ao.UNREACHABLE_WARNED_KEY: "2026-09-06"}, "2026-09-07", "http://x")))


# --- needs_you agents + the human queue ---------------------------------------

print("\n14c. needs_you agent with a non-actionable recommendation is still listed")
cur_ny = mk_overview([("argo", [mk_agent("a1", "Migrate schema", "watch", standing="waiting on input", state="needs_you")])],
                     summary={"needsYou": 1, "working": 0, "idle": 0, "stale": 0, "done": 0, "dispatch": 0})
body_ny = ao.render_slack(cur_ny, ["new: argo — Migrate schema (watch) [id:a1]"])
check_true("header counts 1 needs_you", "1 needs_you" in body_ny)
check_true("the needs_you agent is in the body", "Migrate schema" in body_ny)
blocks_ny = ao.render_slack_blocks(cur_ny, [], full=False)
check_true("blocks digest lists the needs_you agent", any("Migrate schema" in json.dumps(b) for b in blocks_ny))
brief_ny = ao.render_briefing(cur_ny)
check_true("briefing lists the needs_you agent despite recommendation=watch", "Migrate schema" in brief_ny)

print("\n14d. humanQueue — 'Needs you' section in digest, blocks and briefing")
cur_hq = mk_overview([("argo", [mk_agent("a1", "Ship it", "ship")])])
cur_hq["humanQueue"] = [
    {"id": "q1", "askedAt": "2026-09-07T10:00:00Z", "question": "Reseed the secrets cache", "cmd": "make secrets-seed"},
    {"id": "q2", "askedAt": "2026-09-07T10:05:00Z", "question": "Push the ACL <change> & serve"},
]
body_hq = ao.render_slack(cur_hq, ["needs you: Reseed the secrets cache [id:hq:q1]"])
check_true("mrkdwn digest has the Needs you header", "*Needs you*" in body_hq)
check_true("mrkdwn digest lists the question and cmd", "Reseed the secrets cache" in body_hq and "make secrets-seed" in body_hq)
blocks_hq = ao.render_slack_blocks(cur_hq, [], full=False)
check_true("human-queue block comes first after the header", "Needs you" in blocks_hq[1]["text"]["text"])
check_true("human-queue block escapes agent-derived text", "&lt;change&gt; &amp;" in blocks_hq[1]["text"]["text"])
check_true("header counts the human queue", "2 human-queue" in blocks_hq[0]["text"]["text"])
brief_hq = ao.render_briefing(cur_hq)
check_true("briefing carries the Needs you lines", "Needs you" in brief_hq and "Reseed the secrets cache" in brief_hq)

print("\n14e. delta() — a human-queue entry appearing or draining is a change")
prev_hq = mk_overview([("argo", [mk_agent("a1", "Ship it", "ship")])])
prev_hq["humanQueue"] = [{"id": "q0", "askedAt": "t", "question": "Old ask"}]
changes_hq = ao.delta(prev_hq, cur_hq)
check_true("new asks are deltas", any(c.startswith("needs you: Reseed") and c.endswith("[id:hq:q1]") for c in changes_hq))
check_true("drained asks are deltas", any(c.startswith("answered: Old ask") for c in changes_hq))
check("unchanged agent is not a delta", [c for c in changes_hq if "[id:a1]" in c], [])
check("no human queue on either side -> no hq deltas", [c for c in ao.delta(mk_overview([]), mk_overview([])) if "hq:" in c], [])

print("\n14f. fingerprint() — a new human-queue entry changes it, tolerant of the key being absent")
snap_a = {"projects": [], "humanQueue": [{"id": "q1", "askedAt": "t1", "question": "x"}]}
snap_b = {"projects": [], "humanQueue": [{"id": "q1", "askedAt": "t1", "question": "x"}, {"id": "q2", "askedAt": "t2", "question": "y"}]}
check_true("new entry changes the fingerprint", ao.fingerprint(snap_a) != ao.fingerprint(snap_b))
check("absent key == empty list", ao.fingerprint({"projects": []}), ao.fingerprint({"projects": [], "humanQueue": []}))
check("malformed humanQueue tolerated", ao.fingerprint({"projects": [], "humanQueue": "nope"}), ao.fingerprint({"projects": []}))


# --- fingerprint() -----------------------------------------------------------

def mk_snapshot(projects: list[tuple[str, dict | None, list[dict]]]) -> dict:
    """(name, git, agents) -> an /api/agents-shaped `data` object."""
    return {
        "summary": {"needsYou": 0, "working": 0, "idle": 0, "stale": 0, "done": 0, "dispatch": 0},
        "projects": [
            {"name": name, "cwd": f"/repo/{name}", "git": git, "agents": agents}
            for name, git, agents in projects
        ],
        "warnings": [],
    }


def mk_snap_agent(id_: str, state: str, last_activity: int) -> dict:
    return {"id": id_, "state": state, "lastActivityAt": last_activity}


print("\n15. fingerprint() — stable across agent order")
git_a = {"dirty": False, "ahead": 0}
snap1 = mk_snapshot([("repoA", git_a, [
    mk_snap_agent("a1", "working", 100),
    mk_snap_agent("a2", "idle", 200),
])])
snap2 = mk_snapshot([("repoA", git_a, [
    mk_snap_agent("a2", "idle", 200),
    mk_snap_agent("a1", "working", 100),
])])
check("fingerprint ignores agent order", ao.fingerprint(snap1), ao.fingerprint(snap2))

print("\n16. fingerprint() — stable across project order")
git_b = {"dirty": True, "ahead": 2}
snap3 = mk_snapshot([
    ("repoA", git_a, [mk_snap_agent("a1", "working", 100)]),
    ("repoB", git_b, [mk_snap_agent("b1", "idle", 300)]),
])
snap4 = mk_snapshot([
    ("repoB", git_b, [mk_snap_agent("b1", "idle", 300)]),
    ("repoA", git_a, [mk_snap_agent("a1", "working", 100)]),
])
check("fingerprint ignores project order", ao.fingerprint(snap3), ao.fingerprint(snap4))

print("\n17. fingerprint() — stable across dict key order")
snap5 = {
    "warnings": [],
    "projects": [{"agents": [
        {"lastActivityAt": 100, "id": "a1", "state": "working"},
        {"lastActivityAt": 200, "id": "a2", "state": "idle"},
    ], "git": git_a, "cwd": "/repo/repoA", "name": "repoA"}],
    "summary": {},
}
check("fingerprint ignores key order", ao.fingerprint(snap1), ao.fingerprint(snap5))

print("\n18. fingerprint() — changes when agent.state changes")
snap_state_a = mk_snapshot([("repoA", git_a, [mk_snap_agent("a1", "working", 100)])])
snap_state_b = mk_snapshot([("repoA", git_a, [mk_snap_agent("a1", "idle", 100)])])
check_true("state change flips fingerprint",
           ao.fingerprint(snap_state_a) != ao.fingerprint(snap_state_b))

print("\n19. fingerprint() — changes when lastActivityAt changes")
snap_ts_a = mk_snapshot([("repoA", git_a, [mk_snap_agent("a1", "working", 100)])])
snap_ts_b = mk_snapshot([("repoA", git_a, [mk_snap_agent("a1", "working", 999)])])
check_true("lastActivityAt change flips fingerprint",
           ao.fingerprint(snap_ts_a) != ao.fingerprint(snap_ts_b))

print("\n20. fingerprint() — changes when project.git.dirty changes")
snap_dirty_a = mk_snapshot([("repoA", {"dirty": False, "ahead": 0}, [mk_snap_agent("a1", "working", 100)])])
snap_dirty_b = mk_snapshot([("repoA", {"dirty": True, "ahead": 0}, [mk_snap_agent("a1", "working", 100)])])
check_true("git.dirty change flips fingerprint",
           ao.fingerprint(snap_dirty_a) != ao.fingerprint(snap_dirty_b))

print("\n21. fingerprint() — changes when project.git.ahead changes")
snap_ahead_a = mk_snapshot([("repoA", {"dirty": False, "ahead": 0}, [mk_snap_agent("a1", "working", 100)])])
snap_ahead_b = mk_snapshot([("repoA", {"dirty": False, "ahead": 3}, [mk_snap_agent("a1", "working", 100)])])
check_true("git.ahead change flips fingerprint",
           ao.fingerprint(snap_ahead_a) != ao.fingerprint(snap_ahead_b))


# --- needs_refresh() -----------------------------------------------------

print("\n22. needs_refresh() — null overview always needs a refresh")
check_true("null overview -> true", ao.needs_refresh({"overview": None}, 7200_000))
check_true("missing overview key -> true", ao.needs_refresh({}, 7200_000))

print("\n23. needs_refresh() — ageMs above the bound needs a refresh")
check_true("age above bound -> true",
           ao.needs_refresh({"overview": {"ageMs": 7200_001}}, 7200_000))

print("\n24. needs_refresh() — ageMs below the bound does not need a refresh")
check("age below bound -> false",
      ao.needs_refresh({"overview": {"ageMs": 100}}, 7200_000), False)

print("\n25. needs_refresh() — ageMs exactly at the bound does not need a refresh")
check("age at bound -> false",
      ao.needs_refresh({"overview": {"ageMs": 7200_000}}, 7200_000), False)


# --- render_slack_blocks() ------------------------------------------------

print("\n26. render_slack_blocks() — header block text")
cur = mk_overview(
    [("repoA", [mk_agent("a1", "Ship it", "ship")])],
    summary={"needsYou": 2, "working": 3, "idle": 0, "stale": 1, "done": 0, "dispatch": 0},
)
blocks = ao.render_slack_blocks(cur, [], full=True)
check("first block is a header", blocks[0]["type"], "header")
header_text = blocks[0]["text"]["text"]
check_true(
    "header names needsYou/working/stale",
    "2 need you" in header_text and "3 working" in header_text and "1 stale" in header_text,
)

print("\n27. render_slack_blocks() — project ordering: answer project first")
cur = mk_overview([
    ("repoShip", [mk_agent("s1", "Ship task", "ship")]),
    ("repoAnswer", [mk_agent("a1", "Answer task", "answer")]),
])
blocks = ao.render_slack_blocks(cur, [], full=True)
section_texts = [b["text"]["text"] for b in blocks if b["type"] == "section"]
check_true("answer project's section comes first", section_texts[0].startswith("*repoAnswer*"))

print("\n28. render_slack_blocks() — agent line format (emoji, title, standing)")
cur = mk_overview([("repoA", [mk_agent("a1", "Fix bug", "ship", standing="tests green")])])
blocks = ao.render_slack_blocks(cur, [], full=True)
text = [b["text"]["text"] for b in blocks if b["type"] == "section"][0]
check_true("emoji present", ":package:" in text)
check_true("title present", "Fix bug" in text)
check_true("standing appended with a dash", "— tests green" in text)

print("\n29. render_slack_blocks() — blocker line present when set")
cur = mk_overview([("repoA", [
    mk_agent("a1", "Fix bug", "answer", standing="waiting", blocker="needs your input"),
])])
blocks = ao.render_slack_blocks(cur, [], full=True)
text = [b["text"]["text"] for b in blocks if b["type"] == "section"][0]
check_true("blocker line present", "needs your input" in text and "↳" in text)

print("\n30. render_slack_blocks() — blocker line absent when unset")
cur = mk_overview([("repoA", [mk_agent("a1", "Fix bug", "ship", standing="ok")])])
blocks = ao.render_slack_blocks(cur, [], full=True)
text = [b["text"]["text"] for b in blocks if b["type"] == "section"][0]
check_true("no blocker arrow", "↳" not in text)

print("\n31. render_slack_blocks() — escapes <@mention> and & in agent-derived text")
cur = mk_overview([("repoA", [
    mk_agent("a1", "Ping <@U123> & review", "ship", standing="uses <script> & more"),
])])
blocks = ao.render_slack_blocks(cur, [], full=True)
text = [b["text"]["text"] for b in blocks if b["type"] == "section"][0]
check_true("no raw <@ mention", "<@U123>" not in text)
check_true("mention escaped", "&lt;@U123&gt;" in text)
check_true("ampersand escaped", "&amp;" in text)

print("\n32. render_slack_blocks() — 50-block cap with 60 projects")
projects = [(f"repo{i}", [mk_agent(f"a{i}", f"Task {i}", "ship")]) for i in range(60)]
cur = mk_overview(projects)
blocks = ao.render_slack_blocks(cur, [], full=True)
check_true(f"<= {ao.BLOCKS_MAX} blocks (got {len(blocks)})", len(blocks) <= ao.BLOCKS_MAX)
check_true(
    "overflow marker is the final block",
    blocks[-1]["type"] == "context" and "more project" in blocks[-1]["elements"][0]["text"],
)

print("\n33. render_slack_blocks() — full vs digest filter")
cur = mk_overview([("repoA", [
    mk_agent("a1", "Watched", "watch"),
    mk_agent("a2", "Ready", "ship"),
])])
digest_blocks = ao.render_slack_blocks(cur, [], full=False)
digest_text = "".join(b["text"]["text"] for b in digest_blocks if b["type"] == "section")
check_true("digest excludes a non-actionable, unchanged agent", "Watched" not in digest_text)
check_true("digest includes the actionable agent", "Ready" in digest_text)

full_blocks = ao.render_slack_blocks(cur, [], full=True)
full_text = "".join(b["text"]["text"] for b in full_blocks if b["type"] == "section")
check_true("full=True includes the non-actionable agent too", "Watched" in full_text)

print("\n33b. render_slack_blocks() — digest includes a changed but non-actionable agent")
prev = mk_overview([("repoA", [mk_agent("a1", "Watched", "watch")])])
cur = mk_overview([("repoA", [mk_agent("a1", "Watched", "close")])])
changes = ao.delta(prev, cur)
digest_blocks = ao.render_slack_blocks(cur, changes, full=False)
digest_text = "".join(b["text"]["text"] for b in digest_blocks if b["type"] == "section")
check_true(
    "digest includes a changed agent even though 'close' is non-actionable",
    "Watched" in digest_text,
)


# --- main(['--slack-body']) posting behavior ------------------------------

print("\n34. main(['--slack-body']) prints nothing when post_blocks succeeds")
prev_state = mk_overview([("repoA", [mk_agent("a1", "Fix bug", "watch")])])
cur_state = mk_overview([("repoA", [mk_agent("a1", "Fix bug", "ship")])])

_orig_fetch = ao.fetch
_orig_fetch_agents = ao.fetch_agents
_orig_refresh = ao.refresh
_orig_load_state = ao._load_state
_orig_save_state = ao._save_state
_orig_post_blocks = ao.post_blocks
_orig_resolve_slack_token = ao.resolve_slack_token


def _reset_slack_body_mocks():
    ao.fetch = _orig_fetch
    ao.fetch_agents = _orig_fetch_agents
    ao.refresh = _orig_refresh
    ao._load_state = _orig_load_state
    ao._save_state = _orig_save_state
    ao.post_blocks = _orig_post_blocks
    ao.resolve_slack_token = _orig_resolve_slack_token


ao.fetch_agents = lambda base, timeout_s=10: cur_state
ao.refresh = lambda base, timeout_s=120: cur_state
ao._load_state = lambda: {**prev_state, "fingerprint": "old"}
ao._save_state = lambda cur: None
ao.resolve_slack_token = lambda: "xoxb-fake"
ao.post_blocks = lambda channel, blocks, text_fallback, token: True
try:
    out = io.StringIO()
    with redirect_stdout(out):
        rc = ao.main(["--slack-body"])
    check("exit 0", rc, 0)
    check("no stdout when post_blocks succeeds", out.getvalue(), "")
finally:
    _reset_slack_body_mocks()

print("\n35. main(['--slack-body']) prints the mrkdwn fallback when post_blocks returns False")
ao.fetch_agents = lambda base, timeout_s=10: cur_state
ao.refresh = lambda base, timeout_s=120: cur_state
ao._load_state = lambda: {**prev_state, "fingerprint": "old"}
ao._save_state = lambda cur: None
ao.resolve_slack_token = lambda: "xoxb-fake"
ao.post_blocks = lambda channel, blocks, text_fallback, token: False
try:
    out = io.StringIO()
    with redirect_stdout(out):
        rc = ao.main(["--slack-body"])
    check("exit 0", rc, 0)
    check_true("fallback body printed when post_blocks fails", out.getvalue().strip() != "")
finally:
    _reset_slack_body_mocks()


print()
if failures:
    print(f"{len(failures)} failure(s):")
    for f in failures:
        print(f"  - {f}")
    sys.exit(1)
print("all cases as expected")
