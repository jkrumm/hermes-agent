# Verifying an agent episode's claimed result

_Use when relaying a dispatched agent's claimed result._

The class: an episode (Warden item, sideclaw `dispatch`/`check`/`review` job) reports
an outcome — a verdict, a green suite, a PR — and you must relay it or act on it.
**The claim and the artifact are different things, and only one of them is evidence.**
A card's note, a brief's asserted measurement and a PR body are all prose written by
the thing being checked.

Reading Warden's own status is the `warden` skill (its HTTP API, never the database).
This is the step before acting: deciding whether the thing you were handed is true.

## Procedure

1. **Read the job store, not the card.** The ledger holds the real result:

   ```python
   import sqlite3, os, json
   con = sqlite3.connect(f"file:{os.path.expanduser('~/.local/share/sideclaw/jobs.db')}?mode=ro", uri=True)
   con.row_factory = sqlite3.Row
   for r in con.execute("select * from jobs where id like ?", (job_prefix + '%',)):
       d = dict(r)          # params, status, result (JSON), error, progress, created_at, finished_at
   ```

   `result` carries `summary`, `verdict`, `confidence`, `nextAction`, `outcome`,
   `artifactUrl`, `branch`, and `steps[]` with a `passed` per step. The folded
   verdict for a Warden item is `GET http://127.0.0.1:7735/items/<event_id>` — read it
   through the `warden` skill, never the ledger file. Use `mode=ro` + `uri=True` and never the
   macOS `/usr/bin/sqlite3` CLI — it has no `-uri` and dies `unable to open
   database file (14)`.

2. **A brief's "measured evidence" is a claim, not a fact.** A brief that says a
   direction was *measured* ("verified both directions", "reproduced green at
   ~183s") is asserting it, and the run it cites may not be in the store. Grep the
   job store for the run that would have produced it before repeating the number.
   If only the counter-direction is recorded, say which direction is unverified —
   and do **not** re-dispatch to re-derive it; that spends an episode on a claim
   you can settle by reading.

3. **Reproduce by hand before calling a fix verified.** See the recipe below. A
   hand-run is evidence about the repo; the handler's own `check` is evidence about
   the loop. You want both, and they are not interchangeable.

4. **Verify the artifact outside the agent's own words.**

   ```bash
   gh pr view <n> -R <owner>/<repo> --json state,isDraft,mergeable,mergeStateStatus,files,url
   gh pr checks <n> -R <owner>/<repo>
   gh pr list -R <owner>/<repo> --state open --json number,title,headRefName,mergeStateStatus
   ```

   `mergeStateStatus: CLEAN` plus per-check `pass` is the evidence; the PR body is
   not. `reviewDecision: ""` on a repo with no reviewers configured is normal, not
   a missing approval.

5. **Report what you verified yourself, separately from what you read.** Verdict
   first, then the artifact URL, then the numbers you produced. "Verified: check job
   `passed: true` all 5 steps; standalone lane 10 files / 89 tests exit 0" is a
   different sentence from "the episode says it is green".

## Reproducing a lane by hand on this host

```bash
mkdir -p ~/SourceRoot/.hermes-wt
cd ~/SourceRoot/<repo> && git worktree add --detach ~/SourceRoot/.hermes-wt/<repo>-verify <ref>
cd ~/SourceRoot/.hermes-wt/<repo>-verify
bun install --frozen-lockfile                      # a fresh worktree has no node_modules
ROLLHOOK_SECRET=… gtimeout 420 bun run <lane> > /tmp/<repo>-lane.log 2>&1; echo "EXIT=$?"
# read the suite's own totals: Test Files / Tests / Duration / EXIT
cd ~/SourceRoot/<repo> && git worktree remove --force ~/SourceRoot/.hermes-wt/<repo>-verify
```

Run it as a **background** terminal and poll the log — a full docker-compose e2e
stack is 4–5 minutes. `grep -n "Test Files\|Tests \|EXIT=\|Error" <log>` is the read.

## Pitfalls

- **Cut the worktree under `$HOME`, never `/tmp`.** Colima mounts only the home
  directory into its VM (`colima ssh -- mount` shows one virtiofs entry for
  `/Users/<you>`), so a compose file that bind-mounts `${PROJECT_ROOT}/…` resolves
  to nothing under `/tmp` and the container exits at startup
  (`dependency failed to start: container … exited (1)`). That reads like a broken
  lane and is really the worktree's location. `/tmp` is fine for a lane that never
  starts a container; it is wrong for one that does.
- **A fresh worktree has no `node_modules`.** Install from the frozen lockfile
  before hand-running a JS lane, or the runner dies before any test with
  `failed to load config from …/vitest.config.ts`. A check job that passed is no
  evidence about your hand-run: the job installs into the `cwd` it was handed, so a
  green job in *its* worktree says nothing about a different directory.
- **Wrap the lane in `gtimeout` above the runner's per-command cap.** A green suite
  that outruns the cap is recorded as a timed-out *failed* step, so a bare run
  reproduces the false negative you are trying to disprove.
- **A test suite's own totals are the acceptance number** — files, tests, exit
  code. "It passed" without them is not a verification, and a flaky file (a timing
  assertion) is worth naming rather than averaging away.
- **Discovery-by-script-name is an LLM mapping, so a rename reduces rather than
  eliminates pickup.** When a fix works by renaming a script out of the canonical
  `test`/`lint`/`typecheck` set, report it as a reduction. Claiming the lane can no
  longer be discovered is a claim the mechanism does not support.
- **Re-read the item before answering a card.** Cards are projections rendered at
  the last state change, and an escalation ("still waiting on you — 24 h in
  `merge_blocked`") can arrive after the state already moved. `curl -s
  http://127.0.0.1:7735/items/<event_id>` first; the transitions are the history.

## The `merge_blocked` handoff on a PR-required repo

A repo listed in `~/.claude/pr-required-repos.json` can never be merged by the loop:
the item lands `merge_blocked` with *"requires a human pull-request review … this verb
will not merge there"*. **That is a handoff, not a defect and not a stuck gate** — the
disposition is to say the PR is ready and let him merge it. Do not look for another
way to land it, and never merge on github.com.

What that report must carry, in this order: the URL, the title, the file count, the
draft state, `mergeStateStatus`, and the per-check CI state. Then the one thing that
actually changes his next move:

- **When a newer PR supersedes an older one, say plainly which single PR to
  review.** Check whether the old one is closed (`gh pr view <old> --json state`) and
  verify the supersession rather than repeating it: `git diff origin/master...origin/<branch>
  --stat` shows the combined diff, so "contains the other PR's changes" is checkable.
  Two open PRs carrying the same change is the trap this prevents.
- **Name what you verified yourself** — the check job's step results, the standalone
  lane's file/test counts — and the residual risk the episode itself flagged.
- **An unmerged PR means the underlying break is still live on the default branch.**
  Say so: until it lands, every episode in that repo reproduces the same failure.
