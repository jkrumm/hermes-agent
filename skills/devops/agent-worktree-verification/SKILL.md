---
name: agent-worktree-verification
description: Use when verifying an agent's branch in a worktree.
version: 1.0.0
metadata:
  hermes:
    tags: [worktree, verify, dispatch, sideclaw, checks_failed, gitignored, env, canonical-set]
    related_skills: [agent-branch-recovery, preexisting-red-check-recovery, fresh-worktree-test-lanes, agent-worktree-test-hygiene, agent-pr-handoff]
---

# Verifying an agent's branch in a worktree

Before you land, re-dispatch or close an agent's branch, you have to answer one
question: **does this branch actually pass?** A throwaway `git worktree add` is
not the environment the episode ran in, and a green run in the live checkout is
evidence about nothing — it has the store, the `.env` and usually a pile of dirty
files from an interactive agent.

Getting this wrong is expensive in both directions: phantom failures make you
re-dispatch a branch that was fine, and a false green makes you land a red one.

## Procedure

1. **Cut the worktree at the branch, not at master.**

   ```bash
   cd ~/SourceRoot/<repo>
   git worktree add --detach /tmp/<repo>-verify <branch-ref>
   ```

2. **Give it the gitignored environment the episode had.** sideclaw
   materializes untracked/gitignored files into an episode's worktree (bounded);
   `git worktree add` copies nothing. Repos that load config from a gitignored
   `.env` (Bun reads it from the repo directory, cwd-based) fail a whole block of
   their suite on missing configuration — a double-digit failure count that reads
   like a broken diff.

   ```bash
   cp ~/SourceRoot/<repo>/.env /tmp/<repo>-verify/.env
   ```

   **If the count drops from double digits to one, the rest were your worktree's
   artifact, not the branch's.** Say which is which; never report the phantom
   ones as the branch's failures.

3. **Run the repo's full canonical set, not the touched suite.** The handler's
   check step runs `format`/`format:check`, `lint`, `typecheck`, `test` over the
   whole tree — a green run of the one file the diff touches is not the check
   that gates the episode. Read the scripts out of `package.json` (or the
   Makefile) rather than guessing names.

4. **Re-run the failing step at pristine master, with nothing added.** This is
   the only way to separate "the branch is red" from "the repo was already red":

   ```bash
   git worktree add --detach /tmp/<repo>-pristine master
   ```

   Red there and green on the branch = pre-existing, and the branch is clean. A
   pre-existing red step withholds the PR for **every** episode in that repo.

5. **Verify the diff is the fix and nothing else.** `git diff master...<ref>
   --stat`, then the changed files in full. The worker's report is a claim; the
   diff is the proof.

6. **Clean up both worktrees.** `git worktree remove --force /tmp/<repo>-verify
   /tmp/<repo>-pristine`.

## Pitfalls

- **Never leave the shell `cd`'d into a worktree.** sideclaw tears its own
  worktrees down at episode end and the terminal session's cwd persists, so every
  later command fails with `cd: … No such file or directory` and exit 126 — which
  reads like a broken tool rather than a stale cwd. Pass an explicit `workdir`, or
  `cd` back out.
- **A hand-built worktree is not the episode's worktree.** Missing `.env`, absent
  store, absent build output — each produces failures that belong to your
  worktree, not the branch.
- **A green live checkout proves nothing.** It is the one environment the episode
  never sees.
- **Do not read a failure count before you have read what it died on.**
  Fixture-shaped errors (`FileNotFoundError`, a missing-config error, a
  missing-chunk error) are environment; assertion failures are the diff.
- **`git worktree list` includes the agents' own worktrees**, and a commit
  sitting in one is not on master. A worktree parked at master's SHA with a clean
  status means that episode's work already landed — not that it is still pending.
- **Do not clean up an episode's branch before its artifact exists.** On a
  `checks_failed` episode the branch is the only artifact; the worktree is torn
  down and the job is pruned from sideclaw within a day.
