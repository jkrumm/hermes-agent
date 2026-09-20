---
name: agent-branch-recovery
description: Use when an agent episode pushed a branch but opened no PR.
version: 1.0.0
metadata:
  hermes:
    tags: [warden, sideclaw, dispatch, checks_failed, branch, worktree, gitignored, verify, close]
    related_skills: [warden, warden-digest-triage, claude-dispatch]
---

# Recovering an agent episode that ended without a PR

A dispatch episode can do its job and still produce **no PR**. Warden's
`poll_implement_jobs()` routes on the job's typed `result.outcome`, and three of
those outcomes mean "the work exists on a branch, nobody landed it":

| `outcome` | Warden state | What actually happened |
|-|-|-|
| `checks_failed` | `needs_human` | the repo's checks were red **before push**, so no PR was opened |
| `branch_no_pr` | `merge_blocked` | branch pushed, PR creation failed |
| `salvaged` | `needs_human` | sideclaw could not get a structured verdict out of the session |

A **fourth** shape reaches `merge_blocked` with no `outcome` at all: the
`implementing` state's own 2 h deadline (`STATE_DEADLINES` in `triage.py`,
`_DeadlineRule("poll_implement_jobs", 2, STATE_MERGE_BLOCKED, …)`). A long
implement episode — a repo whose own `check` lane runs the full suite, 60+ turns —
can still be running when the clock fires, and `poll_implement_jobs()` has **no
path back from `merge_blocked`**. The card then reads `deadline expired: sat in
'implementing' for its full 2h … Moved to 'merge_blocked' by the clock, not by a
decision` while the job finishes minutes later with `pr_opened` and a real PR.
**Read the job before believing that note**, and close the item by hand once the
PR exists — the loop will not pick it up again.

**Re-running the item is the wrong move** — it reproduces the same verdict
against the same wall and burns a second episode. The branch is the artifact.
Your job is to fetch it, verify it, land it and close the item.

## 1. Read the verdict, never the card note

`checks_failed` writes this note:

```
implement <job>: the repo's checks failed before push (branch <b>): <summary[:300]>
```

That `<summary>` is the **verdict's own one-line summary** — an episode that did
its job writes a positive statement there ("Fixed: … 72 tests pass"). The card
therefore reads like a finished item that inexplicably stopped, and the word
`checks_failed` is the only signal that it did not. **Never conclude from the
note.** Read the full verdict and the branch out of it:

```bash
curl -s "http://127.0.0.1:7735/items/<event_id>"      # dispatches[].verdict
curl -s "http://127.0.0.1:7705/api/jobs/<job_id>"     # .result.{outcome,branch,verdict}
```

The prose field (`verdict.verdict` / `result.verdict`) is where the episode
states *why* the checks were red; `summary` never is. sideclaw prunes terminal
jobs at 24 h / 200 rows, so read the job while it is still there — the ledger's
`dispatches.verdict_json` is the durable copy.

## 2. Fetch the branch by full refspec

The branch is not in your local remote-tracking set, and a wildcard source with a
non-wildcard destination is an invalid refspec (`fatal: invalid refspec`). Name
both sides:

```bash
cd ~/SourceRoot/<repo>
git fetch origin 'refs/heads/<branch>:refs/remotes/origin/<short-name>'
git rev-parse --short origin/<short-name>   # confirm it landed before relying on it
```

## 3. Read the diff before believing the verdict

`git diff master...<ref> --stat`, then the changed files in full. A worker's
report is a claim; the diff is the proof. Check every line it says it changed.

## 4. Reproduce the failure with the environment the episode lacked

**`checks_failed` on an `implement` item is usually a worktree environment gap,
not a red diff.** sideclaw materializes untracked/gitignored files into the
episode's worktree only up to a bound (`MAX_COPY_BYTES` 100 MB /
`MAX_COPY_FILES` 5000, `dispatch-git.ts`), so a repo whose tests need a
multi-gigabyte gitignored store (a model/observation `data/` tree, a built asset
dir) fails its suite on missing fixtures in *every* episode — no PR, and an item
that lands `needs_human` looking like a code problem.

Give the worktree the store, then run the repo's own test target:

```bash
git worktree add --detach /tmp/<repo>-verify <ref>
ln -s ~/SourceRoot/<repo>/<gitignored-dir> /tmp/<repo>-verify/<gitignored-dir>
cd /tmp/<repo>-verify && uv run pytest -q --tb=line -rf
```

## 5. Prove the residual failures are pre-existing

Repeat the **failing subset** in a second worktree at pristine `master`, same
symlink. Identical failures on both = the diff is green and the item was
mis-routed. Report both counts (`3 failed, 1853 passed` on each) — that is the
evidence, not an assertion. Fixture-shaped failures are the tell:
`FileNotFoundError` / `GridUnavailableError` on paths under the gitignored dir.

## 6. Land it and close the item

If master is an ancestor, the branch is a fast-forward:

```bash
git merge --ff-only origin/<short-name> && git push origin master
cd ~/SourceRoot/warden && ./scripts/warden close <event_id> \
  --why "<what landed, where, and what you verified>"
```

`close` is the **CLI verb** for resolving an item by hand — the `warden` skill is
read-only and cannot do it, and `abort`/`revert` take an event id, not a job id.
The `--why` is the durable record; put the commit hash and the verification in it,
not a restatement of the card. Then clean up: `git worktree remove --force <path>`
and delete the pushed `dispatch/…` branch once merged.

## 7. Name the structural fix, not just the instance

If the cause was a gitignored store or a test target that cannot run in a
worktree, **every future episode in that repo hits the same wall.** Say so in the
report and offer the durable fix as its own episode — a `conftest` skip for
data-dependent tests, or a repo validate target that excludes them. The loop keeps
producing `checks_failed` items until that lands.

## Pitfalls

- **A repo with no `origin` remote cannot be fixed by any worktree `implement`
  episode — on `warden` this is permanent.** `resolveRepoIdentity()`
  (`sideclaw server/jobs/handlers/dispatch.ts` → `dispatch-git.ts`, run for every
  tier that is not `investigate` and not `workspace: in-place`) shells
  `git remote get-url origin` before the session starts, so the job lands
  `failed` in ~40 ms with **no branch, no worktree and no verdict** — and the item
  goes to `merge_blocked` carrying that error. `warden` itself is local-only
  (no remote by design), yet both policy copies list it as `implement`-reachable,
  so its own fixes can never arrive as a PR. Check `git remote -v` in the repo
  before believing a re-dispatch is the remedy; the real options are land it by
  hand (repo convention: append a § to `docs/history/state-log.md` and update
  `STATE.md` in the same commit, direct-to-master) or ask for a
  `workspace: "in-place"` dispatch, which skips identity resolution entirely and
  leaves the edits uncommitted for review. Never report this as "the episode
  failed to fix it" — the episode never ran.

- **A raw NUL byte in the working tree kills the commit, and the error names the
  message, not the file.** An episode that *removes* a NUL byte from a source
  file can still carry one into the commit message it builds, and git rejects the
  whole commit — `args[4] must be a string without null bytes` (Node) or an
  `error: a NUL byte in commit log message not allowed`. The job then reports
  `status: failed`, `lastAction: committing`, `turns: 0`, and **no branch and no
  PR** — the work exists only in sideclaw's salvage bundle. Same tell on the diff
  side: `git diff <base> <ref> -- <file>` says *"Binary files … differ"* for a
  file that is plain text. Find them with a byte scan, not `grep`:
  `git show <ref>:<file> | python3 -c "import sys;print(sys.stdin.buffer.read().count(b'\x00'))"`.
  Recover the salvage bundle, then escape the byte (`\u0000` in a TS/JS string
  literal) rather than dropping the file.
- **Salvage bundle location and shape.** `~/.local/state/sideclaw/salvage/<branch>.bundle`
  — a bare repo. `git clone` it, then `git bundle list-heads` / `git fsck --lost-found`;
  the stash commit is reachable but usually on no named branch. Re-parent it as a
  fresh commit onto the current merge-base (`git commit-tree <tree> -p <base> -m …`)
  instead of reusing the stash commit, so the branch is linear and PR-able.
- **Before landing your own recovery, check the item for an existing branch or PR.**
  A parallel session (or a late-finishing episode) can recover the same salvage and
  open a second PR for one item. `gh pr list --state open` plus
  `git branch -r --contains <sha>`; if two exist, keep the complete one, comment the
  supersede reason on the other, and close it — two open PRs for one issue is noise.
- **Build the verification worktree under `~/SourceRoot/`, never `/tmp`.** colima
  mounts only `/Users` into its VM, so a `/tmp` worktree's bind-mounted paths
  (`${PROJECT_ROOT}/e2e/mock-oidc`) resolve to nothing inside the container and
  the suite dies with `Module not found "/mock-oidc/server.ts"` — which reads
  like a broken diff and is purely a mount artifact. `~/SourceRoot/.wt/<repo>-verify`
  is the safe location.
- **rollhook's `test:e2e` cannot run on this host at all, so a `checks_failed`
  there is a false negative.** Traefik v3.3's Docker provider cannot read
  colima's daemon — `client version 1.24 is too old. Minimum supported API
  version is 1.44` on a loopback — so `localhost:9080/version` never answers and
  `e2e/setup/global.ts`'s 30 s readiness wait throws
  `Service did not become ready within 30000ms`. Reproduce it in a second
  worktree at pristine `master` before treating it as the diff's fault; the same
  suite is green in CI. Land on the repo's other gates (`lint`, `typecheck`,
  `check:basalt`) plus the PR's own CI run instead.
- **A `checks_failed` can be the box's toolchain, not the tree.** Check the
  local tool against the repo's CI pin before blaming a file
  (`preexisting-red-check-recovery` has the procedure): weatherorb's whole TS
  lane was red on pristine `master` under Bun 1.1.7 while CI pins 1.4.0, and
  `bun upgrade` turned it green with no source change — leaving only the
  hand-opened PR. When the fix is environmental, put it in the PR body and the
  close `--why`; nothing in the repo records it.
- **A later round's branch contains the earlier rounds' commits — open the PR
  by hand against the default branch, then close the superseded ones.** Round 4
  of a review cycle built on round 3's branch: `gh pr create --draft --base
  master --head <branch>` gives the owner **one** diff for the whole change
  (the branch's parent PR's commits come along), and each earlier PR gets a
  supersede comment plus `gh pr close`. Close the matching ledger items too —
  otherwise the digest re-surfaces three cards for one change.
- **Do not re-dispatch a stuck item.** Same verdict, same wall, one more episode
  spent. Recover the branch instead.
- **`outcome` is the routing fact, the note is prose.** Only `outcome` tells you
  whether work exists; only the verdict's prose tells you why it stopped.
- **A missing store is not a broken repo.** Check whether the failures are
  fixture-shaped and whether they reproduce on pristine `master` before treating
  them as a code defect.
- **Never report a landed branch as "the episode failed".** The episode pushed
  work; it failed to *open a PR*. Say which, and name the commit you landed.
