---
name: carrier-mergeability-preflight
description: "Use when a blocked PR may not be mergeable. Preflight it."
version: 1.0.0
metadata:
  hermes:
    tags: [pr, merge-blocked, warden, superseded, review, re-derive, preflight]
    related_skills: [warden-blocked-items, superseded-branch-triage, review-round-convergence, claude-dispatch]
---

# A blocked PR is not always a review problem

Trigger: a Warden card in `merge_blocked`/`needs_human` reading "still blocked after N
revisions", a dispatch verdict offering "land it as-is, or re-scope the brief", or any
request to merge, revise or follow up an agent-opened PR.

The trap: the review verdict is the *visible* reason and the revision budget is the
loop's own bookkeeping, so the natural next move is another round or another brief.
Neither can land a branch that was cut from a master which has since moved — and the
ledger has no field that says so, because it only records review outcomes.

## Procedure

1. **Read the PR by number, never from a list.** Lists are search-index reads and lie
   under lag; the pull API is the truth about the carrier itself:

   ```bash
   gh api repos/<owner>/<repo>/pulls/<n> \
     --jq '{draft,state,mergeable,mergeable_state,base:.base.ref,head:.head.sha}'
   ```

2. **Measure the distance to the default branch**, in the repo's checkout:

   ```bash
   cd ~/SourceRoot/<repo> && git fetch -q origin
   git rev-list --left-right --count origin/master...origin/<branch>   # behind / ahead
   git merge-tree --write-tree origin/master origin/<branch> | head    # the conflicted paths
   ```

   `merge-tree` prints the conflicted paths — that list is the diagnosis, not the count.

3. **Classify the conflict before choosing a fix.**

   | What you see | What it is | Disposition |
   |-|-|-|
   | `mergeable`, no conflicts | an ordinary carrier | normal path: revise (new `run <repo> --tier implement`) or hand the owner the merge |
   | conflicts on paths master has **split, moved or renamed**, and the branch *imports* modules that no longer exist | superseded by the repo's own restructure, not by a newer branch | re-derive from master; the old branch becomes the specification |
   | conflicts on the branch's own files, paths intact | a real conflict | owner merge or one fix round, as the card's playbook says |

   Two tells for the middle row: `mergeable_state: dirty`, and the conflicted paths
   existing at a *different* path on master (`git ls-tree --name-only origin/master <dir>`).
   When the branch's imports are gone, resolving the text still leaves a file that
   cannot run.

4. **Re-derive, and hand over the spec rather than the diff.** File
   `run <repo> --tier implement` with a brief that carries: what is broken (with the
   empirical cases you measured), each class the fix must hold, the acceptance commands,
   the one residual you deliberately accept, and the old head SHA explicitly marked
   **reference only — do not carry it verbatim, it is based pre-split; port it onto
   master's current paths**. A successor that copies the diff re-introduces the dead
   imports; one that works from the spec lands on current paths. Push the closure work you
   did on the dead branch anyway — it is what the brief cites.

5. **Close both cards, in this order.** The parked item
   (`close <event-id> --why "<what blocked it, why the carrier is unmergeable, which
   successor item carries the work>"`), then the alert/self-audit card that pointed at it —
   `close` is the right verb there too, because its ask ("land it as-is") no longer exists.
   Leaving it open keeps re-reminding the owner about an impossible decision.

## Pitfalls

- **`gh pr list` is a search-index read; `gh pr view <n>` can fail to resolve a PR that
  exists.** Both have answered wrong for a PR the pull API returned as open the same
  minute. Never tell anyone a PR is gone, closed or absent from a list miss.
- **Do not mark an unmergeable carrier ready (`gh pr ready`), and never ask the owner to
  merge it.** Un-drafting advertises a PR he cannot act on, and its stored review verdict
  covers a head that no longer applies to the tree master now has.
- **Do not spend a further review round on a stale base.** Rounds spent is a cost, not
  evidence of progress; when master moved the paths, every round is unwinnable and a
  sharper brief buys nothing.
- **Do not propose raising the revision budget for one non-converging item.** A cap that
  fired because the carrier was dead is not a mis-sized cap, and it is the owner's call
  in any case — the item needs a re-derivation, not a bigger budget.
- **A review finding can be false on its own terms — check the data flow before briefing
  it.** Whether the guarded decision is computed inside the guard's window, and whether
  any caller re-reads the guarded resource after the guard returns, is readable in one
  pass over the callers. Say what you refuted, and write the residual into the docstring
  so the next round does not re-raise it, instead of shipping a patch that pretends to
  widen a window it cannot widen.
- **Verify a class closure in a test helper with a before/after probe.** Materialise the
  pre-fix file as a second module (`git show HEAD:<path> > $SCRATCH/old.py`, load with
  `importlib.util.spec_from_file_location`) and drive both versions through the same
  fixture, printing the outcome — two lines of output is what makes "the class is closed"
  a measurement instead of a claim.
