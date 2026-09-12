"""Regression suite for scripts/agents-overview.py's pure functions.

Covers: render_briefing()'s line cap and its watch/close exclusion (with the
needs_you override), needs_refresh()'s staleness gate, render_slack_blocks()'s
Block Kit rendering (header/footer, ordering, escaping, the 50-block cap) for
the on-demand `--post-full` overview, and the unavailable-degrades-gracefully
path for `--briefing`.

No network, no sideclaw, no state file — every case builds its fixtures
in-memory and calls the module's functions directly (or monkeypatches
fetch/refresh for the CLI-level unavailable case).

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


# --- render_briefing() ---------------------------------------------------

print("11. render_briefing() — excludes watch/close, includes the rest")
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


# --- needs_you agents + the human queue ---------------------------------------

print("\n14c. needs_you agent with a non-actionable recommendation is still listed in the briefing")
cur_ny = mk_overview([("argo", [mk_agent("a1", "Migrate schema", "watch", standing="waiting on input", state="needs_you")])],
                     summary={"needsYou": 1, "working": 0, "idle": 0, "stale": 0, "done": 0, "dispatch": 0})
brief_ny = ao.render_briefing(cur_ny)
check_true("briefing lists the needs_you agent despite recommendation=watch", "Migrate schema" in brief_ny)

print("\n14d. humanQueue — 'Needs you' section in blocks and briefing")
cur_hq = mk_overview([("argo", [mk_agent("a1", "Ship it", "ship")])])
cur_hq["humanQueue"] = [
    {"id": "q1", "askedAt": "2026-09-07T10:00:00Z", "question": "Reseed the secrets cache", "cmd": "make secrets-seed"},
    {"id": "q2", "askedAt": "2026-09-07T10:05:00Z", "question": "Push the ACL <change> & serve"},
]
blocks_hq = ao.render_slack_blocks(cur_hq)
check_true("human-queue block comes first after the header", "Needs you" in blocks_hq[1]["text"]["text"])
check_true("human-queue block escapes agent-derived text", "&lt;change&gt; &amp;" in blocks_hq[1]["text"]["text"])
check_true("header counts the human queue", "2 human-queue" in blocks_hq[0]["text"]["text"])
brief_hq = ao.render_briefing(cur_hq)
check_true("briefing carries the Needs you lines", "Needs you" in brief_hq and "Reseed the secrets cache" in brief_hq)


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
blocks = ao.render_slack_blocks(cur)
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
blocks = ao.render_slack_blocks(cur)
section_texts = [b["text"]["text"] for b in blocks if b["type"] == "section"]
check_true("answer project's section comes first", section_texts[0].startswith("*repoAnswer*"))

print("\n28. render_slack_blocks() — agent line format (emoji, title, standing)")
cur = mk_overview([("repoA", [mk_agent("a1", "Fix bug", "ship", standing="tests green")])])
blocks = ao.render_slack_blocks(cur)
text = [b["text"]["text"] for b in blocks if b["type"] == "section"][0]
check_true("emoji present", ":package:" in text)
check_true("title present", "Fix bug" in text)
check_true("standing appended with a dash", "— tests green" in text)

print("\n29. render_slack_blocks() — blocker line present when set")
cur = mk_overview([("repoA", [
    mk_agent("a1", "Fix bug", "answer", standing="waiting", blocker="needs your input"),
])])
blocks = ao.render_slack_blocks(cur)
text = [b["text"]["text"] for b in blocks if b["type"] == "section"][0]
check_true("blocker line present", "needs your input" in text and "↳" in text)

print("\n30. render_slack_blocks() — blocker line absent when unset")
cur = mk_overview([("repoA", [mk_agent("a1", "Fix bug", "ship", standing="ok")])])
blocks = ao.render_slack_blocks(cur)
text = [b["text"]["text"] for b in blocks if b["type"] == "section"][0]
check_true("no blocker arrow", "↳" not in text)

print("\n31. render_slack_blocks() — escapes <@mention> and & in agent-derived text")
cur = mk_overview([("repoA", [
    mk_agent("a1", "Ping <@U123> & review", "ship", standing="uses <script> & more"),
])])
blocks = ao.render_slack_blocks(cur)
text = [b["text"]["text"] for b in blocks if b["type"] == "section"][0]
check_true("no raw <@ mention", "<@U123>" not in text)
check_true("mention escaped", "&lt;@U123&gt;" in text)
check_true("ampersand escaped", "&amp;" in text)

print("\n32. render_slack_blocks() — 50-block cap with 60 projects")
projects = [(f"repo{i}", [mk_agent(f"a{i}", f"Task {i}", "ship")]) for i in range(60)]
cur = mk_overview(projects)
blocks = ao.render_slack_blocks(cur)
check_true(f"<= {ao.BLOCKS_MAX} blocks (got {len(blocks)})", len(blocks) <= ao.BLOCKS_MAX)
check_true(
    "overflow marker is the final block",
    blocks[-1]["type"] == "context" and "more project" in blocks[-1]["elements"][0]["text"],
)

print("\n33. render_slack_blocks() — includes every agent that has a recommendation")
cur = mk_overview([("repoA", [
    mk_agent("a1", "Watched", "watch"),
    mk_agent("a2", "Ready", "ship"),
])])
blocks = ao.render_slack_blocks(cur)
text = "".join(b["text"]["text"] for b in blocks if b["type"] == "section")
check_true("non-actionable agent with a recommendation is included", "Watched" in text)
check_true("actionable agent is included", "Ready" in text)


print()
if failures:
    print(f"{len(failures)} failure(s):")
    for f in failures:
        print(f"  - {f}")
    sys.exit(1)
print("all cases as expected")
