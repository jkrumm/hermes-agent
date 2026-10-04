# Measuring a claim against live state

_Use when a claim must be checked against live state._

Use when a review finding, a blocked PR's note, or a fix you are about to brief concerns **live
state** — a race, a run identity, a guard that must skip rather than fail, a cache, a sync writer —
and the decision (which invariant to keep, which round to file next, whether to fix it at all) turns
on a number you do not have. An argument about such a property is unwinnable; a count over the live
population ends it in one sentence.

The trap this skill exists for: **the agent worktree sees none of it.** An episode's worktree is cut
fresh, has no `data/`, nothing listening on the port, and its suite skips exactly those lanes — so a
green `pytest` there proves nothing about the behaviour under discussion, and "I reproduced it once"
is an anecdote that loses the next review round.

## Procedure

1. **Get the code under discussion into a scratch worktree, not the live checkout.**

   ```bash
   git -C ~/SourceRoot/<repo> fetch origin 'refs/pull/<n>/head:refs/remotes/origin/pr<n>'
   git -C ~/SourceRoot/<repo> worktree add --detach <scratch>/<repo>-pr<n> origin/pr<n>
   ```

2. **Enumerate the population from the repo's own discovery code** — its model/variable/case lister,
   its registry walker — never a hand-picked sample: the count must cover the whole class the
   claim is about.

3. **Call the branch's own helper directly** from a probe script, with the checkout's venv, so you
   measure the code under review and not a paraphrase of it:

   ```bash
   cd <scratch>/<repo>-pr<n>
   ~/SourceRoot/<repo>/.venv/bin/python <scratch>/probe.py
   # probe.py: sys.path.insert(0, "tests/<subdir>"), import the helper, loop the population
   ```

4. **Point a live lane at the real data root through the repo's own env var** where one exists
   (`WEATHERORB_DATA_ROOT`-style), so nothing is copied and the live tree stays the control:

   ```bash
   <data-root env var>=/Users/jkrumm/SourceRoot/<repo>/data \
     ~/SourceRoot/<repo>/.venv/bin/python -m pytest tests/<subdir> -q
   ```

5. **Probe both rules** — the one the review demands and the one you intend to keep — so the brief
   carries a before/after rather than a promise.

6. **Clean up and prove it**: `git worktree remove --force <path>`, then
   `git -C ~/SourceRoot/<repo> update-ref -d refs/remotes/origin/pr<n>`, then `git worktree list` and
   `git status -s` — the live checkout must be untouched.

## Reporting rules

- **Give the fraction, not the story.** "Raises on 9/9 live cases, 5/9 when scoped to the compared
  unit" settles a round; "reproduced locally" does not.
- **Name the harness in the reply** — which command, which data root — so the next session re-runs it
  instead of re-arguing it.
- **An unobservable demand is a residual, not a fix.** Before briefing a finding, ask whether the
  property it wants can be read from the system at all: a service that reads the same tree cannot
  give a second opinion on that tree, and "assert the API names the same run" is void when its
  response carries no run field. Say "cannot be asserted, by construction" with the reason and
  document it in the code; do not spend an episode attempting it.
- **A measurement that kills the current direction is a result, not a failure.** Report it as the
  reason the contract changes — smaller, never stricter — with the retired demand written down.

## Pitfalls

- **An editable install resolves the package to the live checkout**, so a worktree run can mix
  trees: the test-local helper comes from the worktree, the package from the checkout. If the code
  you are measuring lives in the package, run from the live checkout instead and say which tree
  answered.
- **A green suite in a fresh worktree is not evidence about live state** — the lanes that matter skip
  there. Always say which run produced a number.
- **Never edit the live checkout to run a probe.** A probe that dirties shared state is worse than no
  probe; the scratch worktree plus the env var exists so the live tree stays the control.
- **Check the carrier's own mergeability before choosing a fix route**: `gh pr view <n> --json
  isDraft,mergeable,mergeStateStatus`. A `CONFLICTING` carrier has drifted from master, so the fix
  belongs on current master as a re-derivation (a fresh tracked dispatch), not as a commit on the
  branch.
