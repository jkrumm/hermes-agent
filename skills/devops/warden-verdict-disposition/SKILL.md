---
name: warden-verdict-disposition
description: Use when a Warden dispatch verdict needs a disposition.
version: 1.0.0
metadata:
  hermes:
    tags: [warden, verdict, disposition, close, abort, triage, state-machine]
    related_skills: [defect-report-verification, stalled-dispatch-forensics, warden-digest-triage, claude-dispatch]
---

# Warden verdict disposition

A dispatch verdict is a **claim plus an opinion**, and the item it landed on is
still open. Verifying the claim (that is `defect-report-verification`) does not
close the item. Warden's state machine consumes exactly one verdict shape, so
every other one ages silently into a card that reads like a fresh ask.

## The one verdict the loop consumes

`maybe_auto_implement()` advances an item **only** when the folded verdict reads
`nextAction: implement` at `confidence: high` and the repo's ceiling allows it.
Every other verdict — `none`, `issue`, `human`, and `implement` below `high` —
leaves the item sitting in state `verdict` with **nothing polling it**. `verdict`
carries a 24 h deadline that expires to `needs_human`; that card then looks to the
owner like a new request for him, when nothing changed except the clock.

So `nextAction: issue` does not mean an issue was filed — it means the episode
*thinks* one should be. `nextAction: none` does not mean the item is done. Both
mean **you** own the disposition.

## Procedure

1. **Read the item, not the card.**

   ```bash
   curl -s http://127.0.0.1:7735/items/<event_id>
   ```

   `state`, `note`, `transitions`, and the verdict off `dispatches[].verdict`.
   The card is a projection from the last state change.
2. **Establish whether the finding is already handled before relaying it as
   work.** For `nextAction: issue`, check the issue exists and what state it is
   in — `gh issue view <n> -R <owner>/<repo> --json state,stateReason,closedAt`
   plus its comments. A maintainer comment recording a design direction and saying
   *"keeping this open, not scheduled"* means the issue's stated purpose is already
   fulfilled; there is nothing to dispatch. For a claim that a doc or code half
   shipped, check the artifact on the default branch (`git log -1 -- <path>`).
   - **An ancestry claim is about the live checkout, not about the remote.** Read
     tiers cut their worktree at the checkout's `HEAD` (`createReadWorktree` in
     sideclaw's `dispatch-git.ts`; the implement tier fetches and cuts from
     `origin/<default>` instead), so a high-confidence *"X is not on master"* can be
     true only of a checkout that lags `origin/master`. Before acting on any
     `git merge-base --is-ancestor <sha> master` / `git ls-tree -r master` evidence,
     run `git -C <repo> fetch origin` and re-check against `origin/<default>`; the
     tell is a `dispatch.worktree` line in `~/Library/Logs/sideclaw.jsonl` with
     `baseRef=HEAD` and a base OID older than the remote tip.
3. **Decide the disposition, then write it.**

   | Verdict / situation | Disposition |
   |-|-|
   | `implement` at `high`, ceiling allows | nothing — the loop takes it |
   | `implement` but the repo is capped below it | the loop already landed `needs_human`; that card is correct, leave it |
   | `issue`, and the issue is genuinely new | offer `capture`; do not file it unasked |
   | `issue`/`none`, and the finding is already tracked or already done | **close the item** |
   | the episode is still in flight and should not be | `abort` |

4. **Close it with the reason in the note.**

   ```bash
   env -u CLAUDECODE ~/.hermes/scripts/hermes-cc.sh close <event-id> --why "<reason>"
   ```

   `close` writes the loop's own transition shape and refuses any in-flight state
   (`implementing`/`validating` — `abort` is that verb). `--why` becomes the item's
   `note`, so write the discharge reason, not a restatement of the verdict: name
   that the work is already tracked or already shipped, and that the GitHub issue
   stays open as the tracker. A recurring signature reopens the item, so closing is
   not a mute.
5. **Verify the write landed.** Re-read `/items/<event_id>`: `state: closed` plus
   a new `verdict → closed` row in `transitions`. A verb that exited 0 is not proof
   the row moved.

## Pitfalls

- **A stale live checkout makes a verdict confidently wrong, and the re-dispatch
  inherits it.** When the checkout lags, every read tier during that window reads
  the lag — the same wrong base produces the same wrong verdict, however many times
  you re-file it. Fast-forward the checkout first (`git -C <repo> merge --ff-only
  origin/<default>` — a clean tree refuses the merge rather than conflicting), then
  file, then verify the new episode's base OID in the job's `dispatch.worktree` log
  line. Repos whose work is pushed from agent/dispatch worktrees (weatherorb) lag
  routinely; repos worked in place (sideclaw, warden) do not. A `close --why`
  written on the stale premise is append-only and cannot be rewritten — correct the
  record on the GitHub issue and say in the report that the item's note is superseded.
- **`env -u CLAUDECODE` is not optional from inside a session.** The CLI refuses
  to run nested inside a Claude Code session; without the unset it exits on a
  recursion guard instead of doing the work.
- **A `needs_human` card is not automatically an ask.** It is also where the 24 h
  `verdict` deadline dumps everything the loop could not act on. Before relaying one
  as work for the owner, check whether the underlying thing is already done — the
  card is only re-synced on the next state change, so it can be hours stale.
- **A `needs_human` card citing a repo tier cap can be stale — the cap is a policy
  value and nothing re-evaluates the card when it changes.** `triage.py`'s
  auto-implement path writes `investigation concluded implement, but repo 'X' is
  capped at tier 'investigate' … apply the fix by hand` and comments that "the cap
  never lifts on its own". It can: an owner edit to `config/dispatch-repos.json`
  lifts it, and no pass revisits `needs_human` against the policy afterwards — the
  card keeps its old note until the 7 d expiry, and its reminder fires at 24 h
  asking for hand work that is no longer needed. Before relaying one, re-run the
  gate yourself: `resolve_tier('implement', resolve_repo('<repo>'))` from warden's
  own venv, plus `make check-policy`. If it now passes, the card is stale — close
  the item naming the lifting commit, and re-open the work as a fresh `run <repo>
  --tier implement` (the old item's `dispatch_job` verdict is still `nextAction:
  implement` at `confidence: high`, so reuse its recommendation in the new brief).
  Do not try to un-stick the old item in place: `needs_human` is not a state
  `maybe_auto_implement()` reads.
- **A `merge_blocked` step-7 card can be blocked by warden's own policy file, not by the validation finding.** `lifecycle/merge.py`'s `merge_gate_check()` refuses any repo with no `autoMergePaths` in `config/triage-policy.json` ("no autoMergePaths declared for 'X' — path scope is the primary merge gate now"), and that fires *before* the validation status is even read. So a repo absent from that file can never merge, however clean its step-7 review was — every item on it piles up in `merge_blocked` with a note naming a code defect that is real but not the reason it is stuck. Confirm the gate directly with `merge <job-id> --why probe --dry-run` (read-only, prints the refusal) before treating the validation finding as the blocker, and report both: the defect the review found, and the policy gap that would stop it landing anyway. Adding `autoMergePaths` is a policy decision with real blast radius (it auto-merges agent PRs into that repo) — name it, do not write it.
- **The fix often lives in a different repo than the issue.** An issue filed on
  repo A can be a defect *in* repo B (a renderer reading a probe's JSON that repo
  A emits). The item's `repo` is A, so A's ceiling gates it — and when A is capped
  at `investigate` the verdict folds to `needs_human` with "apply the fix by hand"
  even though the fix is perfectly implement-reachable in B. That card is correct,
  not a bug: read the verdict's `recommendation` for the file paths it names, make
  the change in B yourself, then close the item with the commit hash in `--why`.
  Do not re-dispatch to A (it will refuse again) and do not open a second item on B
  for a verdict that already told you what to write.
- **Never probe a GitHub write scope with a real POST.** `gh api
  repos/o/r/issues/N/comments -X POST -f body=probe` *creates the comment* on a
  public issue — it does not test the scope and fail. Read `X-OAuth-Scopes` off any
  GET's response headers instead, and if a probe comment does land, delete it with
  `gh api repos/o/r/issues/comments/<id> -X DELETE` and verify the count.
- **Closing is not dismissing and not resolving.** `closed` means a human decided
  the item needs no further action; it is not a claim the defect is fixed. Say
  which one you mean.
- **A failed implement episode disqualifies the item from auto-implement for good.**
  `maybe_auto_implement()`'s eligibility query requires `implement_job IS NULL`, and a
  pre-flight death — e.g. the repo had no `origin` remote at the time, so the episode
  never started — leaves `implement_job` set on the row. The item then sits in `verdict`
  with nothing polling it and decays to `needs_human` on its 24 h deadline, where the card
  reads like a fresh ask for hand work. The stale `implement_job` is the tell, not the
  verdict text. Do not hand-fix the code to work around it: re-file the fix as a fresh
  `run <repo> --tier implement` item carrying the verdict's recommendation as the brief,
  and `close` the old one naming the new item.
- **Do not close an item whose episode is still running.** `close` refuses, and
  that refusal is correct. `abort` cancels the episode *and* closes the item.
- **`nextAction: issue` on an already-open issue is the common shape.** These repos
  are public and the owner files his own issues, so an episode re-deriving an
  existing issue's content is a duplicate, not a finding. Check the tracker first
  and say plainly that the issue already exists.
