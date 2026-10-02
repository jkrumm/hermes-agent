---
name: agent-worktree-test-hygiene
description: Use when a repo's test suite fails in an agent worktree.
version: 1.0.0
metadata:
  hermes:
    tags: [dispatch, sideclaw, warden, worktree, pytest, checks-failed, test-hygiene, gitignored, live-lane]
    related_skills: [agent-branch-recovery, claude-dispatch, warden]
---

# Making a repo's suite honest in an agent worktree

A dispatch episode runs in `git worktree add` at the pinned commit plus a
**bounded** copy of untracked/gitignored files. So it has no multi-gigabyte
store, no build output, and no live services. Tests that need any of those are
red in **every** episode of that repo.

The symptom is a loop, not an incident: every `implement` episode ends
`outcome: checks_failed`, pushes a branch, opens no PR, and lands `needs_human`
looking like a code problem. The fix is in the repo's **tests** — never in
production code, and never by deleting, weakening or blanket-skipping a test that
is genuinely checking code.

Recovering one already-pushed branch is `agent-branch-recovery`; this skill is the
durable fix that stops the loop producing those branches at all.

## 1. Reproduce in the episode's real environment

A bare `git worktree add --detach` is the environment to measure. Symlinking the
real store in gives a *different, much smaller* number and is how a worktree
gap gets misdiagnosed as a near-miss:

```bash
git worktree add --detach /tmp/<repo>-verify <ref>
cd /tmp/<repo>-verify && uv run pytest -q --tb=line -rf    # no store, no build output
```

Read what the episode *actually* received before theorising — the copy step logs
its own accounting:

```bash
grep -h 'dispatch.untracked_copy' ~/Library/Logs/sideclaw.jsonl | tail -5
```

`dispatch.untracked_copy_capped` names `copiedFiles` / `cappedFiles` and the bytes
left behind. That distinguishes "the store was missing" from "the store was
half-copied", and the two need different fixes.

## 2. A partial copy is worse than no copy

When the copy stops at its byte bound mid-walk, the worktree ends up with each
model's `static/meta.json` present and **zero** data chunks. A guard that only
checks `meta.json` therefore passes, and the test then dies further in on a
missing-chunk error. **Any store guard must assert a readable chunk, not just the
metadata file.**

Reproducing this shape by hand (copying the episode worktree's partial store into
a scratch worktree) yields *more* failures than an empty store, not fewer — that
is the same bug, not a second one.

## 3. One fix shape per kind of unrunnable test

| The test needs | Wrong fix | Right fix |
|-|-|-|
| A gitignored data/store tree | a `meta.json`-only guard | a shared store guard asserting a **readable chunk** per variable, then `pytest.skip` naming what is missing |
| An untracked build artifact (a built asset/web dir) | skipping the whole test | keep its real subject: assert the honest failure contract (the 503 and its payload) **and** that the other routes still answer |
| Live services / the live host's own health | leaving it red as "intended" | an opt-in marker plus a directory `conftest.py` that auto-skips unless an env gate is set |
| A live lane that can never pass in a worktree | leaving it in the default run | deselect it from the default invocation (§5) |

Reuse the skip messages the repo already uses, so the suite reads as one
convention rather than a pile of local inventions.

## 4. The store guard

Two checks, because a fresh worktree's store is unusable in two ways: the model's
`static/meta.json` can be absent outright, **or present with every chunk missing**.
`available_time_range` covers both — it derives the grid from `meta.json` and globs
the chunks on disk:

```python
# tests/<area>/_store_guard.py
import pytest


def skip_without_store(model: str, *variables: str) -> None:
    """Skip unless the model's meta.json AND a chunk per variable are readable."""
    root = default_data_root()
    if not (root / model / "static" / "meta.json").exists():
        pytest.skip(f"{model} not present in the local store")
    for variable in variables:
        if available_time_range(model, variable, root) is None:
            pytest.skip(f"no {model}/{variable} chunks on disk")
```

Call it as the **first statement** of each store-dependent test, and inside any
module-scoped fixture that touches the store.

## 5. Deselect a lane that cannot pass in a worktree

**This is the rule that matters most.** sideclaw's check step runs the repo's
plain test command with no marker filter of its own, so a lane that needs both a
huge local store and live services on fixed ports makes *every* episode red.
"Those failures are intended" stops being a defence the moment the lane sits in
the command the episode runs.

```toml
[tool.pytest.ini_options]
# This lane asserts against live services and the local store, so it cannot pass
# in a fresh worktree and must never gate a dispatch check. Its own docstring
# already says to run it standalone; a later `-m` overrides this.
addopts = "-m 'not <lane_marker>'"
```

A later `-m` on the command line wins, so `uv run pytest -m <lane_marker>` still
runs it standalone. **Deselecting a lane from the default run is not skipping a
test**: the lane keeps every property it had — it never skips, it still fails
loudly on a dead service, and it is still run explicitly where the live surface is
the question. Update the marker description and the repo's own validate table in
the same commit, and state what a developer must now type to run that lane.

## 6. Opt-in live marker

For tests that exercise the live host (a real watchdog pass, a store-vs-obs
alignment) rather than the code:

```python
# tests/<area>/conftest.py
import os
import pytest

SKIP_REASON = "live-host test; set RUN_<REPO>_LIVE=1 to run it here"


def pytest_collection_modifyitems(config, items):
    if os.environ.get("RUN_<REPO>_LIVE") == "1":
        return
    skip_live = pytest.mark.skip(reason=SKIP_REASON)
    for item in items:
        if item.get_closest_marker("<live_marker>"):
            item.add_marker(skip_live)
```

Register the marker in the pytest config alongside the existing ones. Give any
statistics helper the test uses a guard for **both** degenerate inputs — empty
pairs *and* zero variance — and have the test skip naming the missing evidence
instead of crashing with `ZeroDivisionError`. A crash on live data is not a
finding about the code.

## 7. Verify with the tool that actually gates the episode

"The suite is green" and "the next episode will open a PR" are different claims,
and only the second is the acceptance criterion. Run sideclaw's own check against
a fresh, storeless worktree:

```bash
curl -s -X POST http://127.0.0.1:7705/api/jobs -H 'content-type: application/json' \
  -d '{"tool":"check","params":{"cwd":"/tmp/<repo>-gate"}}'
# poll GET /api/jobs/<id> until status is done; expect passed: true, every step green
```

Pass `params.commands` to pin the exact commands rather than letting the worker
auto-discover them — auto-discovery on a polyglot repo can pick the wrong
ecosystem's runner. Report the counts the run returns (`N passed, M skipped, K
deselected, 0 failed, 0 errors`) plus the standalone lane's own count.

## 8. Before opening a fix item, check `origin/master`

On a direct-to-master repo the branch from a `checks_failed` episode can be
fast-forwarded onto master while you are still investigating, making the item you
were about to open redundant. Fetch and read master first; if it already landed,
say so and close the stale card instead.

If an item is already in flight for it, `./scripts/warden abort <event_id> --why
"<what landed and where>"` stops the episode and closes the item in one move.
Leaving it to run buys a verdict for finished work and can manufacture a
`needs_human` card at the deadline.

## Pitfalls

- **A `meta.json`-only presence check is not a store guard.** A byte-capped copy
  leaves metadata without chunks, so the guard passes and the test dies deeper in.
  Assert a readable chunk.
- **Never measure the gap with the store symlinked in.** It understates the
  failure badly and turns a worktree gap into a phantom near-miss.
- **Never `cd` into the episode's worktree and leave the shell there.** sideclaw
  tears the worktree down when the episode ends and the terminal session's cwd
  persists — every later command then fails with `cd: … No such file or directory`
  and exit 126, which looks like a broken tool rather than a stale cwd. Run
  worktree commands with an explicit `workdir`, or `cd` back out.
- **A live lane left in the default run is a permanent `checks_failed`.** The
  episode's check step has no marker filter of its own; deselect it in config.
- **Do not change production behaviour to make a test pass.** If a test cannot
  pass without changing production behaviour, that is the finding — report it.
