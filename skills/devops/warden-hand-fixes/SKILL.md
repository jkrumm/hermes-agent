---
name: warden-hand-fixes
description: Use when warden's own code is the fix; land it by hand.
version: 1.0.0
metadata:
  hermes:
    tags: [warden, control-plane, hand-fix, state-log, tests, ledger]
    related_skills: [warden, warden-digest-triage, claude-dispatch, background-work-watch]
---

# Landing a fix in Warden's own repo

A large share of what Warden reports about itself comes back to Warden's own
code: a filter that froze a producer family, a digest heading that reprints, a
proposal pass that grows the policy file. Those fixes have no episode lane —
they are hand-fixes in `~/SourceRoot/warden`, and this is how they land.

**Why not `run warden`.** sideclaw's `resolveRepoIdentity()` requires a GitHub
`origin` for every episode that is not `investigate` and not `worktree: in-place`,
and the long-standing reading of this repo was that it has none. **Re-measured
2026-09-29: `git remote -v` in `~/SourceRoot/warden` reports
`origin  https://github.com/jkrumm/warden.git`**, so that reading is stale — do not
repeat the "no remote, the episode dies in pre-flight" claim without checking it
first. What has *not* been measured since is whether an implement episode against
warden now completes; before relying on either answer, read it off
`dispatch warden --dry-run --tier implement --why probe` (identity + tier) rather
than from this paragraph. The reason to prefer a hand-fix is unchanged and does not
depend on the remote: `scripts/triage.py` is *live* in this working tree, so a saved
edit is the next tick's behaviour, and a PR against the control plane is
merge-approval-gated (a clean validation routes to `needs_human` instead of
merging). Read-only lanes (`warden`, `warden-digest-triage`, `warden-card-intake`,
the `/items` API) are unaffected — this is only about *changing* warden.

## Procedure

1. **Read the repo's own memory before deriving anything.** `STATE.md` is the
two-page current state, including what is *deliberately* open (its "not yet
built" / "not yet made" bullets); `docs/history/state-log.md` is append-only with
one § per finding. Grep them for the symptom — the function name, the state name,
the alert heading — before reading code. **A residual already written up there as
a deferred decision does not need re-diagnosing: the analysis is done and only the
call is missing.** That is the usual reason a call you have been handed looks
"already known but still there" — and it is why the finding belongs in code, not
in a report. `CLAUDE.md` holds the conventions not restated here (venv python
3.11, `make setup` / `make test` / `make status`, the five LaunchAgents, the
ledger's own read rules).
2. **Write the failing test first.** Hand-rolled runners, no pytest; each file
   collects its own `test_*` functions. Assert on the real output surface — the
digest's own posted payload, the query's own rows — and run it before the fix to
watch it fail for the stated reason. **Never weaken, skip or delete a test to make
it pass**: a suite that cannot pass without a behaviour change is the finding.
The gate suite's count is a fact to report, never a number to edit.
3. **Verify on live data, not only on a fixture.** A ledger-wide predicate is
   measured against a `VACUUM INTO` copy of the live ledger — the repo's own
snapshot mechanism, never a bare `cp` of an open WAL database, which captures the
main file and its `-wal` at different instants:

   ```python
   import sqlite3
   live = sqlite3.connect("file:/Users/jkrumm/.warden/warden.db?mode=ro", uri=True)
   live.execute("VACUUM INTO ?", (copy_path,))   # a read-only handle; then close
   ```

   Run the *shipped* function against that copy through the repo's venv python. A
unit test proves the predicate; the live count proves the effect, and the effect
is a number (`rows 4 → 0`), not a sentence.
4. **Land it as one commit**: the code change, its test, the new § appended to
   `docs/history/state-log.md`, and the rewritten `STATE.md` — the log is the
memory and the next session is a stranger, so the three travel together. Direct
to `master`, one commit per logical concern, no attribution footers.
5. **Touch nothing in the supervision tree.** The loop runs `scripts/triage.py`
from this working tree, so a saved edit is live on the next tick: no restart, no
reload, never the LaunchAgents or the gateway.
6. **Confirm the tick, then re-confirm the effect.** `/health`'s
   `pollers.loop.last_run` must be *after* the edit and stay `ok`, with no
traceback in `~/Library/Logs/warden-loop.err` for that run (that file starts with an
older crash, so match a traceback to its position/timestamp instead of counting
matches); then re-run the step-3
probe on a fresh copy. A change that has not survived a tick is not landed, and "the
test passes" is not the same claim as "the loop now behaves differently".

## Pitfalls

- **Write the commit message to a file and use `git commit -F`.** A message in a
double-quoted shell string *executes* its backticks: the quoted code fragments are
substituted away and the body silently loses the SQL predicate, the test names and
the numbers — while the commit itself still succeeds, so the loss is invisible
until someone reads the log. Same reason for helper scripts: `write_file` then run
the file, never a shell heredoc. Quoting survives, and the gateway's command guard
is not scanning a script body as if it were the command.
- **A code fix is not a licence to write the loop's inputs.** The policy file
  (`config/triage-policy.json`) and the ledger rows are the control plane's own;
change code, state and docs, not the rules or the rows a human owns.
- **Do not "unstick" the rows a fixed mechanism left behind.** Rows frozen by the
  old behaviour are terminal history; the corrected behaviour is the deliverable,
and moving them is a separate decision with its own audit trail.
- **Check whether the loop is already carrying the same fix before you hand-fix it.**
  A verdict can be routed into the loop by a parallel lane while you are reading the
  code — typically a `human`-origin `run <repo> --tier implement` row named after the
  same signature and `--why`. Two lanes then produce the same change twice, once as a
  commit and once as a PR whose worktree predates that commit. Read the ledger for a
  recent human row over the same signature before editing:
  `select event_id, signature, state, dispatch_job from triage_items where origin='human'
  order by event_id desc limit 5`.
- **A reopened item cannot always be handed back to the loop.** `maybe_auto_implement()`
  requires `implement_job IS NULL`, so a row whose earlier round died before a PR (a
  pre-flight failure, e.g. when the repo had no `origin`) carries a corpse
  `implement_job` that blocks every later verdict on that row — the second round lands by
  hand even now that the repo is implement-reachable and has a remote. Read that column
  before recommending a re-dispatch.
- **A neighbour skill's mechanism claim can be stale — the repo's source and its
  state-log are the authority.** Skills describing this control plane are written
  from a past state of it; when one asserts an ordering, a filter or a default,
check it against the code before building a conclusion on it (step 1 exists for
exactly this). Correct the skill rather than working around a wrong claim.

## Report shape

German, verdict first, 3–6 lines: what was actually wrong, the change in one
clause ("one predicate"), the test count, the live number, and the tick it went
live on. Name the mechanism, not the state name. No narration of the calls made,
no closing question about work already finished.
