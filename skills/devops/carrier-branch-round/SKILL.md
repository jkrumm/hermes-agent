---
name: carrier-branch-round
description: "Use when a PR already carries the change; land the round."
version: 1.0.0
metadata:
  hermes:
    tags: [pr, rebase, conflict, review-findings, hand-fix, worktree, merge-gate, blast-radius, ledger]
    related_skills: [blocked-agent-pr-handfix, warden-owner-decision-card, code-probe-verification, agent-worktree-test-hygiene]
---

# A round on an existing carrier branch

A change that was already dispatched never gets a clean second dispatch. The first
episode cut its worktree from the **default branch** and its tier forbids touching
another branch, so "continue that PR" is structurally impossible for it: a re-dispatch
re-derives the change as a **second PR** and buys its own review round for a diff of a
few lines, while the first carrier lingers. And on a repo whose merge gate is the
owner's click, a direct commit to the default branch both doubles the change and walks
around that gate.

So when a carrier exists, the round lands on **that branch**: rebase it, fold the
findings, re-verify, hand over the merge. This skill is the round itself — the
`merge_blocked` + *blocking*-finding case is `blocked-agent-pr-handfix`, the decision
card behind it is `warden-owner-decision-card`, and the merge stays the owner's
(`./scripts/warden merge <job-id> --why "…" --confirm`, or the Argo Merge click: the
job id is the **implement** dispatch's, not the PR number).

## When this is the right lane

- A review returned `0` blocking findings — only `improvements[]` and a `discussions[]`
  item — and the branch can no longer merge.
- A card says the branch needs a fix, and the fix is small and on lines the branch just
  wrote (a copied predicate, an overstated docstring, an unbounded scan).
- The PR came back dirty because the default branch moved underneath it.

Not for: re-deriving a change (that is a fresh dispatch), a finding that expands scope,
or a policy / credential / live-data decision, which stays the owner's.

## Procedure

1. **Read the branch's state before writing anything.** `gh pr view <n> --json
   state,isDraft,mergeable,mergeStateStatus,headRefName`, and read the review payload
   from the executor rather than the card (`curl -s
   http://127.0.0.1:7705/api/jobs/<review-job-id>` →
   `result.{blocking,discussions,improvements,testGaps}`). `mergeable: CONFLICTING` is
   not in the card's note and **outranks every finding in it** — a review can truthfully
   report "no blocking issues" on a PR that cannot land.
2. **Work in a repo-local worktree** at the branch head —
   `git worktree add --detach .claude/worktrees/<name> origin/<branch>` — never the live
   checkout. A repo whose harness execs a venv resolved from its own path needs the live
   venv symlinked in (`ln -sfn ~/SourceRoot/<repo>/.venv .venv`) or every shim-driven test
   fails on a missing interpreter.
3. **Reproduce each finding on the head, test-first.** Add the test that fails for the
   stated reason and watch it fail, then fix. A test that passes on both sides proves
   nothing; a suite count is a fact to report, never a number to edit.
4. **Measure a blast-radius finding instead of arguing it** — section below.
5. **Rebase onto the moved base** (section below), then **fold the docs that now lie**:
   the history section, the state summary, a README line describing pre-fix behaviour
   travel in the same commit as the code.
6. **Verify, then push.** Run the repo's own target (it may chain lint ahead of the
   tests), amend the follow-up into the existing commit (`--amend`, not a stack), push
   with `git push --force-with-lease`, and read it back on the **new head sha**:
   `gh pr view <n> --json headRefOid,mergeable,mergeStateStatus` → `MERGEABLE`/`CLEAN`
   plus a symbol grep at that sha (`gh api …/contents/<path>?ref=<sha>`).
7. **Mark it ready** (`gh pr ready <n>`): a draft PR cannot be merged, which turns
   "please merge" into a dead end on a repo whose only merge gate is the owner.
8. **Report**: what the round changed, the test count, the measured number if a blast
   radius was in question, the read-back, and the one command the owner runs. Say plainly
   that the commit is **post-review** whenever the head moved past the reviewed sha — the
   stored verdict covers the old head, so he is merging something no reviewer saw.

## Measuring a blast-radius finding

When the finding is "merging this changes live data in bulk, with no preview", prose
cannot answer it — a number can. Run the **branch's own function**, never a re-typed copy
(which reproduces your reading of the code, not the branch's behaviour), against a
read-only copy of the live store.

**Copy the store read-only.** For the warden ledger, `VACUUM INTO` from a read-only
handle is the repo's own snapshot mechanism; never a bare `cp` of an open WAL database,
which captures the main file and its `-wal` at different instants:

```python
import sqlite3
src = sqlite3.connect("file:/Users/jkrumm/.warden/warden.db?mode=ro", uri=True)
src.execute("VACUUM INTO ?", (copy_path,))
src.close()
```

**Mirror the branch's module beside its siblings.** Warden's loop module imports its
siblings by path relative to `__file__` (`ledger.py`, `intents.py`, `api.py`,
`slack_client.py`, `clients/`) and inserts its own directory on `sys.path`, so a copy at a
scratch path dies on `ModuleNotFoundError` — the copy must sit in a directory that holds
the siblings:

```bash
BR=origin/<branch>; mkdir -p /tmp/probe
cd ~/SourceRoot/warden/scripts && for f in *.py; do ln -s "$PWD/$f" /tmp/probe/"$f"; done
ln -s "$PWD/clients" /tmp/probe/clients
git -C ~/SourceRoot/warden show "$BR:scripts/triage.py" > /tmp/probe/triage.py
git -C ~/SourceRoot/warden show "$BR:config/triage-policy.json" > /tmp/probe/policy.json
```

Take the branch's policy with it: a branch that adds a rule carries its own file, and
measuring against the old policy reports the wrong number. Import with the **repo's** venv
python (the pinned one — the box's default `python3` is not the interpreter the loop runs)
and point the module's env at the copy, never at the live ledger or the live cursor store:

```python
os.environ["WARDEN_DB"] = copy_path
os.environ["WARDEN_TRIAGE_POLICY"] = policy_copy_path
os.environ["WARDEN_HOME"] = probe_home        # cursors/state, not ~/.warden
sys.path.insert(0, "/Users/jkrumm/SourceRoot/warden/scripts")   # if `clients` will not import
spec = importlib.util.spec_from_file_location("triage_probe", "/tmp/probe/triage.py")
```

Importing is safe: everything with side effects lives under the module's `main()` guard.

**Measure the state delta, then where the rows land.** Call the function under review on
the copy, diff `(event_id → state)` before and after, then run the *next* pass and bucket
the affected rows by `(state, repo, verb)`. "3 rows revive" is weaker than "3 revive, 1
maps to `homelab`" — the destination is the part the owner can act on. Print each affected
row's id and a truncated title next to the number.

**Turn the number into a mechanism.** The measurement answers the question once; the code
has to answer it every time. The shape that does: an explicit per-pass bound whose
remainder is named on stderr and left in the terminal state (waiting, never dropped), plus
a dry-run that prints the rows it would move instead of moving them. Then the preview is a
flag the owner can run himself.

## Rebasing onto a moved base

- **Enumerate the real conflicts first**: `git merge-tree --write-tree <merge-base>
  origin/<head>` prints one `CONFLICT` line per file and auto-merges the rest. On a repo
  with an append-only history file, expect that file plus the state summary and nothing
  else — a 3000-line source file merges clean when the commits that landed meanwhile were
  elsewhere in it.
- **In a rebase, `--ours` is the NEW BASE and `--theirs` is the commit being replayed** —
  the inverse of a merge, and backwards it silently discards the branch's content:
  `git rebase origin/master` → `git checkout --ours -- <state files>` → `git add` →
  `git rebase --continue`.
- **Re-author the branch's history section under the next free number** rather than
  replaying it: it was written against an older file, and its number has usually been taken
  by a section that landed meanwhile. Then `grep -rn` for the **old number** across the
  tree — comments, docstrings and tests cite section numbers, and two sections sharing one
  is the error the next session inherits.
- **The base's side of a memory file is the superset.** Keep the branch's copy of a
  history/summary file and you throw away every section that landed meanwhile.

## Pitfalls

- **`policy["ignore"]` is a list of strings, not of rule dicts.** Feeding it to the rule
  matcher raises `TypeError: string indices must be integers`; the ignore check is
  `any(fnmatch.fnmatch(t, pat) for t in targets for pat in policy["ignore"])`.
- **Never run the module's `--run`/`main()` against the copy to "see what happens".**
  `run()` dispatches episodes, posts to Slack and shells out; call the one function under
  review. Re-run on a fresh copy after every code change, or you measure your own residue.
- **An "is it idempotent" check must count transitions per pass.** A later pass moves rows
  the earlier one did not, so comparing terminal state sets across passes proves nothing.
- **Never commit to the default branch while a carrier is open.** Two carriers of one
  change, one of which the loop keeps re-reviewing, plus a bypassed merge gate.
- **Never re-dispatch to "continue" a PR.** The episode's worktree is cut from the default
  branch; the honest options are a fresh change from master or this round.
- **A finding can be stale by a whole round.** Verify it against the current head — a
  defect has been reported as blocking while the head already carried its fix and a
  boundary test for it.
- **Do not silently expand the diff.** A blocker plus a few `improvements[]` is one
  commit's worth of scope; a finding that needs a design call, a policy change or a live
  data edit is named as open work, never folded in.
- **`mergeable: UNKNOWN` right after a push is not a refusal** — mergeability is computed
  asynchronously; re-poll a few seconds later.
- **Leave the tree you were not asked to touch alone.** A scratch worktree, a venv symlink
  and a probe copy are not part of the change; remove them (or let the repo's own
  worktree-prune reclaim them) before the merge.

## Report shape

German, verdict first, 3–6 lines: what the round changed in one clause, the test count,
any measured number, the read-back (`MERGEABLE`/`CLEAN` on which sha), the one command the
owner runs, and the post-review caveat in a clause. Name the mechanism (the moved base,
the shared predicate, the per-pass bound), not the state name. No narration of the calls.
