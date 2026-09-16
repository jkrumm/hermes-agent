---
name: warden-lifecycle-gates
description: Use when a Warden item is stuck or a dispatch refused.
version: 1.0.0
metadata:
  hermes:
    tags: [warden, lifecycle, gates, needs_human, schema, merge, dispatch, triage]
    related_skills: [warden, warden-digest-triage, agent-branch-recovery, claude-dispatch]
---

# Warden lifecycle gates

An item's `state` is the *result* of a gate, never the finding. This skill is the
map from a `note` to the gate that wrote it, and to what to verify before
relaying it as outstanding work. Reading Warden's own status is the `warden`
skill; what to do with a digest is `warden-digest-triage`; recovering a branch
that produced no PR is `agent-branch-recovery`.

## The gates, in the order an item meets them

| Gate | Where it is declared | How it presents |
|-|-|-|
| `MAX_OPEN_INVESTIGATIONS` | `triage.py` (env `TRIAGE_MAX_OPEN_INVESTIGATIONS`) | `queued: at MAX_OPEN_INVESTIGATIONS=N, waiting for a free slot` — pacing, not a failure. Overflow waits, never drops. |
| tier ceiling | `config/dispatch-repos.json` **and** sideclaw's `GET /api/dispatch-policy` | `needs_human`, `investigation concluded implement, but repo '<r>' is capped at tier 'investigate' … apply the fix by hand` |
| per-repo in-flight lock | `lifecycle/policy.py` | `deferred: repo '<r>' already has an implement episode in flight (item N) — one at a time per repo` |
| result schema pin | `scripts/clients/sideclaw.py` | `needs_human`, `sideclaw implement result schemaVersion N, warden expects M — refusing to parse` |
| merge path scope | `config/triage-policy.json` `repos.<r>.autoMergePaths` | `merge` refuses: `no autoMergePaths declared for '<r>'` |

Two of these are worth more than the table:

- **A tier ceiling never lifts on its own, so another `run` cannot fix it.** The
  refusal is in the control plane *and* re-asserted at sideclaw's boundary;
  dispatching again produces another verdict, not the change. Report it as a
  hand-fix, and if the two copies disagree (`make check-policy`), that drift is
  the actual finding — the boundary is quietly allowing what the control plane
  forbids.
- **The per-repo lock makes verdict items queue, not fail.** Items whose verdict
  says `implement` sit in `verdict` with that `deferred:` note and retry every
  tick; the note names the item blocking them. Nothing is lost — do not "unstick"
  it by aborting the running one.

## The schema pin is read from the LIVE checkout

`assert_result_schema()` compares a terminal job's `result.schemaVersion` against
`DISPATCH_SCHEMA_VERSION` in `~/SourceRoot/warden/scripts/clients/sideclaw.py` —
a file on disk that the loop re-reads every tick and that **another agent session
may be editing right now**. Bump that constant while the running executor still
serves the old version and every in-flight implement item lands `needs_human`
with the refusal above, whatever the episode actually achieved.

Consequences to hold onto:

- **That note is not a finding about the repo.** The episode can have finished,
  passed its own checks and opened its PR. Read the job
  (`GET http://127.0.0.1:7705/api/jobs/<job_id>` → `result.outcome`,
  `result.artifactUrl`) before believing the card.
- **Source is not live.** The constant in sideclaw's source tree can be ahead of
  the server that is actually answering. Always ask the endpoint:
  `GET /api/dispatch-schema`. The same split exists for ceilings
  (`GET /api/dispatch-policy`) and routing (`GET /api/routing`).
- **Diagnose with the repo's own checks, not by reading the constant.**
  `make check-schemas` and `make check-policy` in `~/SourceRoot/warden` compare
  the pin against the live endpoint and print the disagreement verbatim. A clean
  run means the note is stale history.
- **The fix is one move, not two:** bump the pin *and* reload the executor
  together. A pin bump alone breaks every implement poll in flight. sideclaw's
  reload refuses while jobs run (`FORCE=1` discards them), so land them in the
  same pass or not at all.

## `needs_human` is terminal until its deadline

`reopen_if_needed()` covers `fixed`/`quiet`/`closed`/`dismissed` only. A
`needs_human` row's sole exit is its own 168 h deadline to `dismissed`, so a card
whose cause has since evaporated — a pin that was reverted, a PR that landed, a
fix committed by hand — keeps sitting there looking current.

**Verify the live condition before relaying a `needs_human` card as work.**
Check the repo's `git log` since `item.updated_at`, the PR the verdict named, and
whatever gate wrote the note. If it is resolved, lead with that and say the card
is stale — do not hand back the card's ask.

## `merge` refuses more than it accepts

Every refusal is final; none is a transient error to retry around.

- `--why "<reason>"` is required — it is the audit record, and there is no
  default.
- It refuses a job whose status is not `done`, and a job with no `artifactUrl`
  (`the episode pushed a branch but never opened a pull request`).
- It refuses any repo with no declared `autoMergePaths`: *path scope is the primary
  merge gate now; nothing merges without an explicit declared scope.* A repo with
  no declared scope is therefore **never** auto-mergeable — its PRs are the
  owner's review, and saying so is the correct report.

**Never work around a refusal by merging on github.com.** Report the gate.

## A `merge_blocked` blocker can be a false claim about the host

Step-7 validation is a `review` job reading the **diff**, not the machine. Its
blocking findings are claims about runtime behaviour, and the adversary angle
regularly asserts a host fact it cannot have checked — "cron's non-login `sh`
never sources `~/.profile`, so this export never reaches the call" is exactly
that shape. The diff can be correct and the blocker wrong at the same time.

Before relaying a `merge_blocked` note as work, **verify its host claim on the
host**, not against the diff:

```bash
ssh <host> 'crontab -l | grep -v "^#" | grep -v "^$"'         # does the prefix exist?
ssh <host> 'env -i HOME=/home/<u> PATH=/usr/bin:/bin sh -c ". /home/<u>/.profile; echo \$VAR"'
```

The second command is the decisive one: it reproduces cron's real environment
(no login session, no inherited exports) and shows whether the documented
export actually lands. Run it **with and without** the source line — a variable
that is set in both, or empty in both, means the claim discriminates nothing.

Two outcomes, two different dispositions:

- **The host is already right and the repo never said so** — the real defect is
  documentation, not behaviour. Fix it on the PR branch yourself (a `git
  worktree` on the pushed branch, commit, push to the same branch), then
  `close <event-id> --why "<commit sha> + what it documents"`. Do not re-dispatch
  an implement episode for a doc paragraph.
- **The host is genuinely wrong** — the blocker is real; the fix is a host
  change, which is `homelab-ops`/`sudo-handoff`, not a dispatch.

Either way the merge still needs the owner: a repo with no `autoMergePaths` can
never be landed by `merge`, so "PR is open and verified, awaiting your merge" is
the finished report.

## Verifying a branch an episode pushed (no PR)

Fetch by full refspec, cut a detached worktree, give it what the repo resolves
from its own checkout, then run the repo's own targets:

```bash
cd ~/SourceRoot/<repo>
git fetch origin 'refs/heads/<branch>:refs/remotes/origin/<tmp-name>'
git worktree add --detach /tmp/<repo>-verify origin/<tmp-name>
cd /tmp/<repo>-verify && ln -sfn ~/SourceRoot/<repo>/node_modules node_modules
bun test && bun run typecheck && fallow audit
```

- **`fallow audit` is a real pre-push gate.** It fails on an export with no
  consumer, so an episode that exported a new internal helper gets
  `checks_failed` with every test green. Dropping the `export` is the whole fix
  and a one-line change you can make on the branch yourself.
- A test step that needs infrastructure the worktree cannot have (docker
  compose, a live port) times out and reads as a red diff. Name it as an
  environment gap and say which step passed.

## Finding who else is editing the repo

Concurrent Claude Code sessions are the usual cause of a mid-flight surprise
above. `GET http://127.0.0.1:7705/api/agents` lists every agent by project with
its `state` and last reply — that is how you learn a repo is being edited right
now rather than inferring it from a diff. `GET /api/jobs/health` gives
`running`/`pending`/`draining`; `GET /api/jobs/<id>` gives `progress.turns`,
`lastAction` and `idleMs` for one episode.

## Pitfalls

- **Never re-dispatch to unstick an item.** Every gate here reproduces the same
  refusal against the same wall and spends another episode.
- **The note is prose; the state and the outcome are the routing facts.** Read
  `dispatches[].verdict` / `result.outcome` before concluding anything.
- **Do not cite a daily dispatch budget.** The daily count budgets were removed;
  the surviving limits are concurrency pacing and the per-repo lock.
- **A `queued:` note survives the claim into `investigating`.** The CAS claim
  passes no `note`, so a row can read `waiting for a free slot` while its episode
  is already running. Check `dispatch_job` first; the Slack card hides this.

## Report shape

Verdict first, then name the gate — not the state. "PR #N is open and verified;
item N sits in `needs_human` on a stale schema-pin note that no longer applies"
is the useful sentence. Group items that share one gate into one line, and say
plainly what you did not do (no merge past a missing scope, no re-dispatch).
