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
_orig_fetch_agents = ao.fetch_agents
_orig_refresh = ao.refresh
_orig_load_state = ao._load_state
_orig_save_state = ao._save_state
ao.fetch = _boom
ao.fetch_agents = _boom
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
    ao.fetch_agents = _orig_fetch_agents
    ao.refresh = _orig_refresh
    ao._load_state = _orig_load_state
    ao._save_state = _orig_save_state


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
