---
name: branch-lineage-verification
description: Use when a PR may patch a branch the host never runs.
version: 1.0.0
metadata:
  hermes:
    tags: [git, checkout, deploy, verification, lineage, warden, sideclaw]
    related_skills: [warden, claude-dispatch, agent-claim-verification, live-checkout-reconciliation]
---

# Branch lineage — verify a fix against the checkout the host runs

An automated pipeline (Warden/sideclaw, any agent loop) works from the
**published default branch**: it fetches, cuts a worktree, opens a PR. The host
in front of you usually executes a **working copy** that can be ahead of that
branch on local-only commits — an in-flight wave/refactor line, a hotfix, a
migration. When the two have diverged, the paths a verdict or brief cites and
the code actually running are *different files*: the PR can patch a file the
live line deleted, leaving the running copy unfixed. "PR #N fixes it" is not a
verified statement until you have checked the lineage.

## Procedure

1. **Establish the lineage before believing either side.** The live line is
   whatever the service actually executes — typically `~/SourceRoot/<repo>`
   under LaunchAgents/systemd, not a clone elsewhere.

   ```bash
   cd ~/SourceRoot/<repo>
   git status -sb                          # ahead/behind vs origin/<branch>
   git branch -a --contains HEAD           # is the local line on any remote at all
   git ls-tree origin/master <path>        # does the file the PR patches exist there
   git log -1 -- <path-on-the-live-line>   # is the live line's own copy guarded?
   grep -rn '<symbol>' --include=*.py src tests | head -20   # where does it live now
   ```

2. **Read the fix's own base and files against that.** `gh pr view <n> --json
   baseRefName,headRefOid` plus `gh pr diff <n>` names the file the episode
   patched; the `git ls-tree` above tells you whether the live line still has
   it. Both can be internally correct and still target different files.

3. **Find the deploy verb that will run after the merge and read its argv.**
   For Warden, the repo's key in `~/SourceRoot/warden/scripts/clients/rollout.py`
   (code owns the argv); otherwise the Makefile target or deploy script. Its
   shape decides what divergence costs — see the rules below.

4. **Check nobody is live in that checkout before you consider touching it.**
   `herdr pane list` gives every pane's `cwd` and `agent_status`
   (`working`/`idle`/`done`); the repo's wave ledger/mailbox names the occupying
   wave. A live agent in the checkout takes the hand-fix off the table.

## Rules

- **An `ahead` count beside a `behind` count means diverged, and the deploy
  verb decides the consequence.** A rollout of `git pull --ff-only` can never
  fast-forward a diverged checkout, so the merge's deploy step fails and the
  item lands `needs_human` however clean the PR is — report that, never "the fix
  landed". A rollout of `reset --hard` / `checkout -f` instead *discards* the
  unpushed line: check the argv before calling any merge safe.
- **Unpushed work lives only on that disk.** `git branch -a --contains HEAD`
  listing nothing but the local branch means no remote copy exists; recommend
  pushing the line before anything merges into it, because the pending push and
  the merge touch the same files and will conflict on a file the fix edited and
  the line deleted.
- **Never hand-land a fix in a checkout another agent is live in.** A wave's
  verification evidence is pinned to the commit it was taken at, so a commit you
  add voids it; and the wave lead's own working tree is in the way. Report the
  sequencing instead of committing.
- **An episode that notices the split may still patch the published twin.** A
  verdict can name paths that exist only on the unpublished line while the
  implement run — correctly, for its base — patches the pre-refactor file. That
  is not a fix for the running code; say which file the live line needs it in.
- **Pipeline stages land on their own clock.** After a verdict reading
  `nextAction: implement` at `confidence: high`, the loop dispatches implement at
  its next tick (Warden's loop interval is 600 s) and the PR can be up minutes
  later. Poll the item (`/items/<id>` → `implement_job`, `pr_url`) rather than
  re-dispatching or announcing the outcome before the PR exists.

## Report shape

Verdict first, then one line per finding: the file the PR patches, the file the
live line runs and whether the guard exists there, the divergence with what the
deploy verb does to it, and the sequencing recommendation — push the line first,
then land the fix against the post-move file. Name what you deliberately did not
touch (the occupied checkout) and why. No step-by-step narration of the commands.
