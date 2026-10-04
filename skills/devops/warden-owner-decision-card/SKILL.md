---
name: warden-owner-decision-card
description: "Use when a Warden card hands the owner a decision."
version: 1.0.0
metadata:
  hermes:
    tags: [warden, needs-human, validation, decision, review, verification, report]
    related_skills: [warden, warden-blocked-items, warden-verdict-disposition, superseded-branch-triage, runtime-claim-verification]
---

# Warden's owner-decision card

A `needs_human` card whose note reads *"Needs your decision on N item(s)"* is the loop
handing over a judgement it is not allowed to make. The item is not stuck, nothing is
retrying, and it auto-dismisses at `item.state_deadline` — there is nothing to un-stick.

The deliverable is not the ask forwarded to Johannes. It is the ask **resolved to a
recommendation**: every question answered from evidence, plus the one fact that changes
his next move. Re-posting the card's own prose is the failure mode.

## Procedure

1. **Read the live item, never the card.**

   ```bash
   curl -s http://127.0.0.1:7735/items/<event_id>
   ```

   `state`, `note`, `state_deadline`, `transitions`, `dispatches[]`.
2. **Get the full review payload from the executor, not the projection.** The item
   payload's `dispatches[].verdict` carries only `summary` / `nextAction` /
   `confidence` / `recommendation`. A `review` job's `blocking[]`, `discussions[]`,
   `improvements[]` (each with `file`, `line`, `angle`) and `testGaps[]` exist only at

   ```bash
   curl -s http://127.0.0.1:7705/api/jobs/<validation_job_id>   # → result.{blocking,discussions,improvements,testGaps}
   ```

   Read them there. The card's note truncates, and the item projection never held
   them — summarizing the card's paraphrase is how a real discussion item gets lost.
3. **Re-verify the artifact is still current before relaying anything.** A review of
   an artifact that moved underneath it is a review of a different artifact.

   ```bash
   cd ~/SourceRoot/<repo>
   gh pr view <n> --repo jkrumm/<repo> --json state,isDraft,mergeable,headRefName,additions,deletions
   git fetch -q origin
   git log --oneline origin/master..origin/<head>                                  # the PR's own commits
   git log --oneline $(git merge-base origin/master origin/<head>)..origin/master    # what landed meanwhile
   ```

   Then enumerate the files changed on BOTH sides with a per-file
   `git diff --quiet <merge-base> <a> -- <file>` / `... <b>` loop — that set is what a
   rebase round has to reconcile. `mergeable: CONFLICTING` is not in the note and
   outranks it: a review can truthfully report "no blocking issues" on a PR that can
   no longer merge, and whose hunks a peer commit on the default branch already
   superseded. Lead with that fact instead of the review's questions.
4. **Answer each discussion item instead of forwarding it.** Each is a checkable
   hypothesis, usually one of two shapes:
   - *"does this fix reach the process that actually does the work?"* → read the
     tool's own docs for which process executes the step and whether it inherits the
     caller's environment (a client-side step inherits it; a detached daemon runs
     with its own env), then probe the resolver in a stripped environment:

     ```bash
     env -i HOME="$HOME" PATH=/usr/bin:/bin bash -c 'source <script>; echo $VAR; echo $PATH'
     ```

     Sourcing is the cheap probe: a script that guards its bootstrap
     (`[[ ${BASH_SOURCE[0]} != $0 ]]`) defines its resolution and returns, so nothing
     heavy runs. A tool that resolves its own toolchain and prepends it to PATH does
     not depend on the caller at all — then the repo-side value of the change is the
     pre-flight assertion, not the PATH export, and say so.
   - *"is this copy/list still wrong or drifting?"* → settle it by diffing the two
     lists and report the **order**, not just existence: two candidate lists that
     both resolve today still disagree about which copy wins under a login vs a
     non-login PATH. When the wrapped third-party tool resolves itself and the source
     cannot be imported, "accept the copy plus a mechanical guard" is a legitimate
     answer — name it as the alternative to dropping the list, with the cost of each.
5. **Report once.** Verdict first; second, the stale-artifact fact if there is one
   (it is what changes his next move); then one recommendation per question as the
   stated default; then the single contingent action.

## Rules

- **Never re-dispatch to unstick a decision card.** The loop stopped on purpose;
  a duplicate episode burns budget and the per-repo lock serializes it anyway. The
  decision comes first, then one round that folds it in.
- **The question is never "is the finding true in the abstract" but "is it still true
  of the artifact's base".** Commits landing on the default branch between the review
  and now are the common reason a card reads as live work when it is stale.
- **"No blocking issues" does not mean mergeable.** Blocking findings, the path-scope
  merge gate and conflict state are independent axes; report the one that stops the
  work, and check whether the repo is even in `triage-policy.json`'s `repos`.
- **Do not write the policy decision.** Adding a merge scope, lifting a tier cap or
  accepting a held pin is the owner's; name it as a decision, never apply it.
- **An improvement is not a blocker.** Rows in `improvements[]` are not findings that
  block — fold the ones that belong in the same round into one line, do not
  enumerate all of them.
- **One question, only when it changes work.** If one option is clearly right, state
  it as the default and proceed; ask only when the readings lead to different work.
- **Never end on "Soll ich …?".** Close with the contingent action: what you will do
  on his word, and what stays his.
