---
name: fresh-worktree-test-lanes
description: Use when a repo's tests can't pass in an agent worktree.
version: 1.0.0
metadata:
  hermes:
    tags: [pytest, worktree, checks_failed, sideclaw, dispatch, gitignored, addopts, markers, verify]
    related_skills: [agent-branch-recovery, warden, claude-dispatch, defect-report-verification]
---

# Test lanes that cannot pass in a fresh agent worktree

An episode's worktree is cut fresh from the default branch, so **nothing gitignored
is present** — sideclaw materializes untracked/gitignored files only up to a bound
(`MAX_COPY_BYTES` 100 MB / `MAX_COPY_FILES` 5000, `dispatch-git.ts`). A repo whose
suite needs a multi-gigabyte store (a model/observation `data/` tree, a built asset
directory) therefore fails in *every* episode, and every item in that repo lands
`checks_failed` with no PR.

The symptom is indistinguishable from a red diff, and the card's note reads like
finished work. Treat it as an environment defect until proven otherwise.

## Procedure

1. **Reproduce in a fresh worktree at the commit under test, with nothing linked in.**

   ```bash
   git worktree add --detach /tmp/<repo>-verify <ref>
   cd /tmp/<repo>-verify && uv run pytest -q
   ```

   Never reproduce in the live checkout — it has the store, so it is green and tells
you nothing about what an episode will see.

2. **Classify each failure by what it died on, not by what the card says.**

   | Failure | Cause | Fix |
   |-|-|-|
   | `FileNotFoundError`, or a "no static/meta.json for model …" style error on a path under the gitignored dir | missing store | guard the tests, skipping by the name of what is missing |
   | anything out of a lane documented as never-skipping, needing services *and* the store | the lane cannot pass in a worktree at all | deselect it from the default run |

   Read the lane's own docstring before deciding. A suite that says "a green run
while the map serves nothing is worse than no suite" is telling you it is meant to be
run explicitly, not by default.

3. **Link the store only as a diagnostic.** `ln -s` it in, re-run, read the residual
   failures. This separates "needs the store" from "genuinely broken" — and it is
   **not** the acceptance criterion. An episode's worktree never has the store, so a
   fix that only holds with it linked in leaves the loop exactly as broken.

4. **Deselect, never weaken.** A lane that cannot pass in a worktree is removed from
   the default run, not made to skip:

   ```toml
   [tool.pytest.ini_options]
   addopts = "-m 'not <lane>'"
   ```

   **The last `-m` wins**, so `uv run pytest -m <lane>` still overrides `addopts` — the
lane keeps every property it had, including failing loudly when its service is down.
Deselecting a lane from the default run is not skipping a test.

   **Node/Bun has no marker filter — the script *name* is the deselect mechanism.**
   sideclaw's check discovers steps by the canonical script names `format`, `lint`,
   `typecheck`, `test`, so a workspace whose `test` script is the live lane is
   discovered and run by every episode. Rename it (`e2e/package.json`: `test` → `e2e`)
   and repoint the root script at the new name in the same commit — including any
   `--filter <pkg> test` call inside it, which fails as `Script "test" not found in
   package "<pkg>"` if only one side is renamed. CI keeps calling the root script, so
   the lane still runs there unchanged; a repo with **no** `test` script anywhere gets
   `passed: true` with the step simply absent. Verify both directions with a real check
   job, not by reading the config.

5. **Update the documentation in the same commit.** The marker description and the
   repo's own validate table must name the standalone command. A documented command
   that no longer matches the real one is the next session's trap, and a brief asking
   for this sync is part of the fix, not a nicety.

6. **Prove both directions, and report the exact counts.**

   ```bash
   uv run pytest -q              # green — report passed/skipped/deselected
   uv run pytest -m <lane> -q    # lane still runs; still fails loudly with its service down
   ```

7. **Prove it with the check the handler runs.** A hand-run pytest is evidence about
   the repo; the handler's own check step is evidence about the loop, and it is the
   only thing that shows the next episode will open a PR. Run it against the same
   fresh worktree, **with no store linked in**:

   ```bash
   curl -s -X POST http://127.0.0.1:7705/api/jobs \
     -H 'content-type: application/json' \
     -d '{"tool":"check","params":{"cwd":"/tmp/<repo>-verify"}}'
   ```

   It returns `{"id": "<full-uuid>", "status": "..."}` immediately — the submit call is
not the answer. Poll `curl -s "http://127.0.0.1:7705/api/jobs/<full-uuid>"` every ~25 s;
a full Python + TypeScript check runs 4–10 minutes.

   - **Poll with the full UUID.** A truncated 8-character id answers
     `{"ok":false,"error":"job not found"}`, which reads like a missing job rather than
     a bad argument — easy to mistake for "sideclaw pruned it".
   - `GET /api/jobs` lists ids with live `progress.turns` and `progress.lastAction` —
     use it to tell a long job from a wedged one, and to find an id you did not keep.
   - Read `.result.passed` and `.result.steps[]` (`typecheck`, `lint`, `test`, `fallow`,
     each with its own `passed`). `.result.summary` is one line and is quotable verbatim.
   - The tool discovers the ecosystem itself, so a repo with both a Python and a
     TypeScript side gets both exercised in one job — a better proof than the test
     command alone. It is read-only and takes no tier.

8. **Clean up.** `git worktree remove --force /tmp/<repo>-verify`.

## Pitfalls

- **A host-coupled lane can have more than one blocker, and the first one hides the
  rest.** Fixing the visible failure (a pinned image that speaks an API the daemon
  refuses) only advances the run to the *next* host collision — a published host
  port already held by an unrelated local service (a dev server, a LaunchAgent).
  Fix one, re-run, read the new failure; do not ship a one-line brief off a single
  reproduction. A brief naming only the first blocker is incomplete and the episode
  will abort or land `checks_failed` on the second.
- **A suite that takes longer than the check runner's per-command cap reports a
  false failure.** sideclaw's `check` caps each command at 180s and records
  `timed out after 180s` as a failed step; a green suite that needs ~250s therefore
  looks red. Run the lane under a longer cap (`gtimeout 300 <cmd>`) and say so in
  the brief, or the implement episode's own check will withhold the PR.
- **The acceptance criterion is the fresh worktree, not the live checkout.** A green
  run in the live tree — where the store exists — is not evidence about anything an
  episode will experience.
- **A lane's "never skips" doctrine is not an argument for leaving it in the default
  run.** Those are two different properties: it must never skip *when it runs*, and it
  must not run by default in an environment where it cannot pass. Honour both.
- **Do not weaken a test to make a suite green.** Guarding a test that needs an
  absent store (skip, naming what is missing) and deselecting a lane that needs live
  services are both honest; a blanket skip or a loosened assertion is not.
- **Do not change production behaviour to make a test pass.** If a test can only pass
  by changing what the code does, that is a finding to report, not a fix.
- **A lane that is green but slow is the same loop as a lane that is red.** sideclaw's
  check caps each command at 180s and records the kill as a failed step, so a suite
  needing ~250s reports `timed out after 180s — likely a watch-mode runner or a hung
  process` and withholds the PR, on a suite that passes. A brief that fixes the
  *content* of such a lane (a pin, a port) and leaves the lane in the default run has
  not fixed the loop — prove it with a check job against a worktree carrying exactly
  that change before calling it done. Deselect it (§4) rather than raising the cap,
  which is not yours to change.
- **A partially-landed brief is the normal shape.** The main fix can be on master and
  verified while a named sub-requirement of the same brief — a marker description, a
  validate table, a doc line — never landed. Diff the brief's full requirement list
  against what actually landed before calling the item done.
- **Check master before letting an in-flight item finish.** An item still
  `investigating` can be asking for work that already landed; running it to the verdict
  either re-derives one for finished work or manufactures a `needs_human` card at its
  deadline. `git log` for a commit matching the brief's ask is the check.
- **`git worktree list` includes the agents' own worktrees**, and a commit sitting in
  one is not on master. A worktree parked at master's SHA with a clean status means
  that episode's work was already merged — not that it is still pending.
