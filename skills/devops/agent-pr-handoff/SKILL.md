---
name: agent-pr-handoff
description: Use when an agent-opened PR needs a human merge.
version: 1.0.0
metadata:
  hermes:
    tags: [pr, merge-gate, draft, handoff, warden, dispatch, review, ci]
    related_skills: [warden-lifecycle-gates, warden-verdict-disposition, dispatch-liveness-verification, agent-branch-recovery]
---

# An agent-opened PR that needs a human to merge it

A dispatch episode that reaches `implement` opens a **draft** PR and stops. Whether
the chain then merges it or refuses is a gate, not a verdict on the work — and in
both cases the PR is the deliverable and a human is the only one who can land it.
This skill is the last mile: confirm the PR is real and green, make it mergeable,
name the gate that stopped the automation, and hand it off.

Reading an item's state is `warden`; mapping a `note` to the gate that wrote it is
`warden-lifecycle-gates`; a branch with no PR at all is `agent-branch-recovery`.

## Procedure

1. **Follow the chain at the executor, not at the card.** The item's `state` is a
   projection; the episode's status is at sideclaw.

   ```bash
   curl -s http://127.0.0.1:7735/items/<event_id>      # state, note, transitions[], dispatches[]
   curl -s http://127.0.0.1:7705/api/jobs/<job_id>     # status, progress, result
   ```

   `transitions[]` is the audit trail: `investigating → verdict → implementing →
   validating → merged|merge_blocked`. Each step is a different job id in
   `dispatches[]`, so read the row for the step you are asking about.

2. **Run the chain in the background, not in a foreground poll loop.** investigate →
   verdict → implement → validate is tens of minutes of queued episodes (a single
   implement episode measured ~12 min, its review another ~10). A foreground loop dies
   at the tool's foreground timeout and loses the transitions in between. Write the
   poll to a script, start it as a tracked background process with completion
   notification, and print only on change.

3. **Read the review verdict's own semantics before calling a merge wrong.** Step 7
   confirms on `outcome: clean`, **or** on `outcome: actionable` with an **empty**
   `blocking` list. Advisory findings (dependency hygiene, a `fallow` suggestion) are
   not blockers, so an `actionable` review that still went on to merge is correct.
   Any non-empty `blocking`, or `needs-human`, refuses.

4. **Identify the gate that refused, then decide whether it is a defect.** A refusal
   is final — never retry around it, never merge on github.com. The common benign one
   is the **human-review gate**: repos listed in `~/.claude/pr-required-repos.json`
   (tracked in `dotfiles/config/`, read by the branch-protection hook and
   `scripts/github-config.sh`) are never auto-merged, and the item lands
   `merge_blocked` naming that file. Nothing is wrong; the chain ran correctly.

5. **Flip the draft — that is the one write that makes the PR actionable.** The merge
   path is what calls `mark_ready_for_review()`, so a PR blocked before that call is
   still a draft and cannot be reviewed or merged.

   ```bash
   gh pr ready <n> --repo <owner>/<repo>
   gh pr view <n> --repo <owner>/<repo> --json isDraft,state,mergeable,mergeStateStatus,statusCheckRollup
   ```

   Handoff state is `isDraft: false`, `mergeable: MERGEABLE`, `mergeStateStatus:
   CLEAN`, every check green.

6. **Verify the diff is the fix and nothing else.** `gh pr diff <n> --repo …` plus
   `gh pr view <n> --json files` — the file list and line counts should match what the
   brief scoped. A generated artifact the suite rewrites on teardown belongs out of
   the diff; if it is in there, say so rather than quietly reporting a clean PR.

7. **Verify through the episode and CI, not by re-running the suite.** The implement
   episode's `result.evidence` carries the pass count and exit code it measured in its
   own worktree, and the PR's `statusCheckRollup` shows the same lane green in CI. Read
   both and quote the numbers. A local re-run adds nothing and costs minutes.

8. **Report the handoff as a handoff.** Verdict first, then the URL, then the gate and
   what is left for him. "PR #N is ready to merge, CI green, Warden will not merge it
   because <gate>" is the sentence. Never present a ready PR as landed work, and never
   present the gate as a failure of the episode.

## Pitfalls

- **A draft PR is invisible to a reviewer.** An episode that opened its PR and then hit
  a merge gate leaves it in draft; report the URL only after flipping it, or say
  explicitly that it is still a draft.
- **`merge_blocked` on a human-review repo is the expected terminal state, not a
  finding.** Do not re-dispatch, do not abort the item, do not "unblock" it.
- **The card lags the ledger.** A Slack card is re-rendered only on a state change, so
  it can show `investigating` while the item is already `validating`. Read the item.
- **Take the branch head from `--json headRefOid`.** `gh pr view --json commits`
  does not list the head first; using its first entry silently described a 1-commit
  branch that was actually 11 commits and 55 behind master.
- **An old agent PR on a fast-moving repo is usually half-already on master.**
  Before calling a rebase small, check each new module for a master-side equivalent
  (`git cherry -v` for patch-equivalence, then compare blobs per file and grep
  master for master's own version of the same idea). Here the parse offload, PDF
  extraction, the semaphore, the round loop and the academic sources had all been
  re-landed by later PRs, so the real decision was *scoping* (keep only the parts
  master lacks) rather than the rebase mechanics — and that is the sentence the
  owner needs, not the conflict count.
- **A `pending` job is queued, not wedged.** sideclaw admits
  `SIDECLAW_JOB_CONCURRENCY` (default 3) at a time; check
  `GET http://127.0.0.1:7705/api/jobs/health` for `running`/`pending`/`max` before
  calling anything stuck. A long queue is not a hang.
- **A green CI check is not the acceptance criterion the brief named.** The brief's
  criterion is usually a specific local command's own numbers; quote both, and say
  which one you did not re-run.
