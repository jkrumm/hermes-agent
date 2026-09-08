# Dispatch Bridge — Hermes hands work to Claude Code

**The claim:** Hermes should never do repo work, and Claude Code should never
watch for it. Hermes observes and decides; Claude Code executes bounded episodes
inside one repo; a single dispatch record ties the two together. Everything else
in this document follows from that split.

**What shipped.** All five phases (investigate-only handler → bounded client →
sweeper → `author`/`implement` tiers → `merge`) built and verified against
`jkrumm/dispatch-scratch` between 2026-08-02 and 2026-08-03: an `implement`
episode producing a pushed branch and draft PR in 24s, an `author` episode
filing an issue, a failing episode leaving the live checkout byte-identical
with worktree/branch/directory all gone, a push attempt under the worker's own
env failing in under a second, read-tier worktree isolation holding with no
branch or directory left behind, the sweeper correctly rendering a
`merged`-vs-open verdict, the nudge-not-verdict wake path working end to end,
and a dispatched repo's own hostile `.claude/settings.json` failing to run a
hook or override the push-credential guard. See hermes-agent CLAUDE.md §
"Dispatch Bridge" and sideclaw CLAUDE.md § "Dispatch Tool" for what runs today,
including the deviations and decisions recorded below.

## Why this exists

Hermes finds things — a red monitor, an OTEL error burst, a stray skill, a GitHub
issue going stale. It routes them well (`capture` already decides GitHub-issue vs
TickTick correctly). Then it stops, because triage needs to *read the repo* and
gpt-5.6-luna with a `terminal` tool is the wrong instrument for that.

The capability gap is not intelligence, it is **context**. Every repo on the mini
carries a `CLAUDE.md`, `.claude/skills/`, `.claude/rules/`, and inherits the
global rule hierarchy. That context is Claude-shaped and Hermes cannot borrow it.
So don't try: point Claude Code at the repo and let it use its own.

## Mental model

```
observation  →  dispatch  →  episode  →  verdict  →  artifact
  (Hermes)      (record)     (Claude)    (record)    (issue/PR/note)
```

**One state machine, four projections.** There is exactly one `dispatches` row
per unit of delegated work. Slack, `watchdog.db`, GitHub and the briefings are
*views* of that row — none of them is an independent mechanism, and none of them
writes state. This is the property that keeps "integrate in all directions" from
becoming four half-synchronised notification paths.

| Projection | Reads | Shows |
|-|-|-|
| Slack thread | `origin_channel` + `origin_thread_ts` | progress and verdict, where it was asked |
| `watchdog.db` events | `origin_event_id` | incident carries its dispatch; digest stops re-reminding |
| GitHub | `artifact_url` | the issue or PR the episode produced |
| Morning briefing | open dispatches | what's still running, what landed overnight |

### Two doors, both one-way

Integration "in all directions" must not mean a cycle. It doesn't:

- **Hermes → Claude Code** — the dispatcher (this document). Carries a brief in,
  a verdict out.
- **Claude Code → Hermes** — already exists, unchanged. A Claude Code session
  reads Hermes's world through **argo** (`argo.jkrumm.com`, all the state) and
  talks to Hermes through the **gateway HTTP API** (`:8642`, bearer-gated,
  OpenAI-compatible — see CLAUDE.md § Gateway HTTP Exposure).

A dispatched episode must **never** dispatch. That is the one recursion rule, and
it is enforced structurally: the episode's brief never carries the dispatch
bearer, and `hermes-cc.sh` refuses to run when `CLAUDE_CODE_SESSION` is set.

## Tiers

Same pipeline, same record, three permission profiles. Not three features.

| Tier | Session | Artifact | Gate | Typical duration |
|-|-|-|-|-|
| `investigate` | `readOnly`, `--json-schema` verdict | a verdict object | none | 30s–3min |
| `author` | `readOnly`; the HANDLER files the issue | GitHub issue | none | 1–4min |
| `implement` | write | branch + **draft PR** | `--why` **and** `--confirm` | 10–40min |

Every tier runs in a handler-managed worktree, torn down when the episode ends —
see the deviations below for why the read tiers need one too.

`investigate` also has a narrow reach into two normally-`deny`d secret-bearing
repos (`dotfiles-private`, `homelab-private`) via the `sensitive` policy flag —
see *Decisions* below, § `sensitive` is a narrow, explicit carve-out of `deny`.

**`implement` always ends in a PR, in every repo, including direct-to-master
ones.** This deviates from the repo's normal convention on purpose: a human wrote
the direct-to-master rule for their own commits, not for an unattended agent's.
The episode never merges and never pushes to a default branch — landing the PR is
the separate `merge` verb.

### `--auto-from-item` — the triage loop's own door into `implement`

`GATED_TIERS=(implement)` still means a Slack-signed `--confirm` for Hermes's
conversational path. `scripts/triage.py` has no Slack round-trip to click one
into, so `dispatch <repo> --tier implement --auto-from-item <event_id>` is a
second, narrower door — see `docs/triage.md`'s *Closing the loop* for the full
chain this feeds (steps 6-10: verdict → implement → validate → merge →
deploy → verify). Every precondition is re-checked against `watchdog.db` at
call time, never trusted from argv: a `verdict`-state `triage_items` row for
that `event_id`, its linked investigate dispatch `done` with a parsed verdict
reading `nextAction: implement` and `confidence: high`, the repo on the
command line matching the verdict's own recorded repo, the repo resolving
normally through policy (not denied, not sensitive, within its tier
ceiling), and the implement budget having room. **Be honest about what this
is and is not**: unlike `--confirm`'s signed approval artifact, nothing here
is cryptographically bound — it is a precondition the caller cannot
fabricate CHEAPLY (every fact it checks is a row a real, already-completed
read-only episode wrote earlier), not a proof of origin. The threat it
closes is the loop being WRONG (a stale item, a low-confidence verdict, a
repo mismatch) — not the loop being HOSTILE, the same threat model
`--confirm`'s own paragraph above already disclaims for a compromised
Hermes. Once validated, it stands in for `--confirm` on that one
invocation — `awaiting_confirm()` and the `require_signed_approval` call
both treat a validated `--auto-from-item` as equivalent to a click.

`dispatch` also takes `--model <id>`, a plain passthrough into sideclaw's own
`dispatch` job body (`server/lib/routing.ts`'s `withModel()` handles
validation/routing) — not a closed allowlist, since a model id is not a
path, a command or a URL. Used by triage.py's step-7 validation episode,
which deliberately runs on a DIFFERENT model (`claude-opus-5[1m]`, probed
live — see `docs/triage.md`) than the `claude-sonnet-5` default that wrote
the implement episode it reviews.

## Three deviations from the original design, all deliberate

**The session never creates the artifact; the handler does.** The original design
had `author` run `gh issue create` and `implement` push its own branch. Built the
other way round: the worker session holds **no GitHub credential at all**, and
`dispatch-git.ts` — running in the sideclaw process, never in a session — resolves
the token, commits, builds the push refspec and calls the API. The reason is the
same one this document gives for fencing the brief: the prompt is assembled from
untrusted material, so anything the session can reach, an injected brief can
reach. Handing it a token to push with would have made every other bound
advisory. As a bonus, "never merges, never pushes to a default branch" becomes a
property of `pushBranch` (explicit default-branch check, `dispatch/` namespace
check, single-branch refspec, no force flag) instead of a line in a prompt.

**A handler-managed `git worktree add`, not the CLI's `--worktree`.** The handler
has to know the worktree path to inspect the diff, apply the ceilings and tear it
down on every exit path including a throw; `--worktree` hands that lifecycle to
the CLI. Creating it explicitly also made the isolation claim *testable*: dirty
the worktree, fail the run, watch the live checkout stay clean and the worktree,
branch and directory all disappear.

**The read tiers get a worktree too.** The original design gave one only to
`implement`, on the reading that a read-only session cannot damage anything. That
reading is wrong: `readOnly: true` removes Edit and Write, not `Bash`. So an
`investigate` or `author` episode ran in the **live checkout** with a shell,
holding a brief assembled from material anyone can write — a GitHub issue title
reaches the watchdog digest, and a dispatched episode then reads the attacker's
full body via `gh`. One injected `sed -i` and the edit lands in a repo other
agents are working in and that deploys to the VPS on push. The third-party
marking in the digest is instruction-level: it labels the content, it does not
stop an episode acting on it, and neither does `--confirm`, which these two
tiers do not have.

They now get `createReadWorktree` — a copy of **HEAD**, deleted in the same
`finally`. Cut from HEAD rather than the default branch because a read tier is
answering a question about *this* checkout and has no artifact to rebase; that
also means no identity, no fetch and no GitHub API, so `investigate` still works
in a repo whose origin is not GitHub or missing. `DispatchWorktree.pushable`
marks the difference, because `salvage` pushes whatever a failed session left
behind and a read tier's leftovers must never become a branch.

Two honest limits. The claim is isolation of the **working tree** only: the
worktree shares `.git` and nothing confines the session's `Bash` to the
filesystem below it — what it buys is that the natural spelling of an injected
write lands somewhere nobody reads. And an episode no longer sees untracked or
gitignored files (`cron/jobs.json`, `briefing-state.json`, a local `.env`);
`_common.md` tells it to report that dependency rather than conclude the file is
missing.

**One thing this design did not anticipate.** `~/.gitconfig` on the mini includes
`~/.gitconfig-headless`, which points the GitHub credential helper at the offline
secrets cache. So *any* process running as this user can push — including a
read-only session, which still has `Bash`. Scrubbing credential-shaped env vars
does nothing about it, because the credential never travels through the
environment. Every tier now runs with `GIT_DENY_CREDENTIALS_ENV`
(`GIT_CONFIG_GLOBAL=/dev/null` plus the terminal-prompt / askpass / ssh fallbacks
closed), verified by measurement: a push under that env fails in under a second
with "terminal prompts disabled", while `git log` is unaffected. This was a
pre-existing hole in the `investigate` tier, not something the write tiers
introduced.

## The dispatch record

Lives in `~/.hermes/watchdog.db` — the mini's one durable Hermes store, which
already holds the incident events a dispatch links back to. New table, no
migration of `events`:

```sql
CREATE TABLE dispatches (
  id                INTEGER PRIMARY KEY AUTOINCREMENT,
  job_id            TEXT NOT NULL UNIQUE,   -- sideclaw job id
  tier              TEXT NOT NULL,          -- investigate | author | implement
  repo              TEXT NOT NULL,
  brief             TEXT NOT NULL,
  why               TEXT,                   -- required for implement
  origin_channel    TEXT,                   -- Slack projection
  origin_thread_ts  TEXT,
  origin_event_id   INTEGER,                -- watchdog projection → events.id
  status            TEXT NOT NULL,          -- queued|running|done|failed|interrupted
  verdict_json      TEXT,
  artifact_url      TEXT,                   -- GitHub projection
  merged_at         TEXT,                   -- denormalized, ALTER TABLE on every connect
  created_at        TEXT NOT NULL,
  finished_at       TEXT,
  reported_at       TEXT                    -- NULL ⇒ the sweeper still owes a message
);
```

`reported_at` is the whole delivery contract: NULL means the sweeper still owes
a message. A `--wait` that returns a terminal verdict stamps it, because handing
the verdict to a live turn *is* the delivery; `status` deliberately does not,
since a poll tells nobody. `artifact_url`/`merged_at` are denormalized out of the
verdict into their own columns by **both** settlers (`hermes-cc.sh`'s
`sync_record`, `dispatch-sweep.py`) — `CREATE TABLE IF NOT EXISTS` no-ops on an
existing table, so the `ALTER TABLE`s run on every connect. sideclaw prunes jobs
after 24h: `status` falls back to the row's `verdict_json` on a 404, and the
sweeper counts consecutive 404s per row (`poll_misses`) — three in a row →
status `lost`, one notice, never retried again.

## Component split

**sideclaw owns the episode. Hermes owns the lifecycle.** Both halves are useful
to other consumers, which is why neither lives in the other.

### sideclaw — the `dispatch` job tool

`server/jobs/handlers/dispatch.ts` + `server/skills/dispatch.md`, registered as a
job tool and exposed over MCP. It gets everything sideclaw already does for
`check`/`review` for free: launchd durability, bun:sqlite persistence with
`recover()` on boot, the global concurrency cap, `idleMs` wedge detection, and
`SIDECLAW_WORKER_BACKEND=max`. `runSession` already takes exactly the right
options — `{ cwd, jsonSchema, maxTurns, readOnly, timeout }`.

This is a **general sideclaw capability**, not a Hermes-private path: once it
exists, any Claude Code session gets `mcp__sideclaw__dispatch` and can hand a
scoped episode to another repo without leaving its own.

What is genuinely new in sideclaw: write-mode sessions with worktree isolation
and a git push. `check`/`review` are read-only, so the branch/PR path has no
precedent there and needs its own care (git identity via `~/.gitconfig-headless`,
`op://mini/github/token`).

**The push bounds are the handler's, and that includes the secret scan.** Before
`implement` pushes, `diffRefusalReason` refuses a diff that touches
`.github/workflows|actions`, exceeds 40 files or 2000 lines, or whose **added
lines** match `SECRET_PATTERNS`. The last one is not left to the repo's own
`pre-commit` hook — which is also why the commit is `--no-verify`: a hook is
repo-controlled code and an implement episode may be running in a repo whose hook
it just wrote, so a check the audited party supplies is not a check. It scans the
diff and not only the PR body, because the code is the durable half — a pushed
branch is permanent and, unlike a description, cannot be edited away. Added lines
only, so a credential the base already carried does not disable the tier in the
repo that needs fixing; a secret merely *moved* between files is the limit that
buys. A refused diff is discarded and the verdict says why: a successful run with
no artifact, not a failure.

### hermes-agent — the bounded client

Mirrors `hermes-ops.sh` exactly, because that pattern is already proven here:

- **`scripts/hermes-cc.sh`** — closed verb set (`dispatch`, `status`, `list`,
  `merge`, `cancel`), no free-form paths, `--why`+`--confirm` on `implement` and
  `merge`, `--json` contract, audit log to `~/Library/Logs/hermes-cc.log`, tests
  under `tests/`.
- **`config/dispatch-repos.json`** — tracked policy: one root, a `deny` list, a
  `defaultTier`, and per-repo tier overrides. Repos are discovered under the root
  rather than enumerated — see *Decisions* below for why the old enumeration
  rotted.
- **`skills/claude-dispatch/SKILL.md`** — when to reach for which tier, and the
  hard rule that infra mutation is `homelab-ops`, never this.
- **`scripts/dispatch-sweep.py`** — `no_agent` cron, every 5 min. Reads open
  dispatches, polls `GET localhost:7705/api/jobs/:id`, posts finished ones into
  their origin thread, stamps `reported_at`. **No LLM in the return path** — the
  verdict is schema-shaped, so formatting is deterministic and free.

## The merge verb — where the human stopped being on GitHub

Every other verb produces a *proposal* a human reads before it means anything.
`merge <job-id>` lands one, unattended (owner decision, 2026-08-02). It inverts a
design statement sideclaw's own `openPullRequest` makes in a comment — *"un-drafting
is not something the episode can do for itself"* — so the question is what
carries the weight the click used to.

Four things do, and the fourth is the one that generalizes:

1. **Addressing.** The argument is a job id. The pull request is read out of the
   `dispatches` row, so no shape of caller input names a PR — exactly the property
   the repo argument has, for the same reason: an injected brief cannot reach the
   thing being acted on.
2. **Eligibility is derived, not listed.** A repo in
   `dotfiles/config/pr-required-repos.json` — the single source of truth the
   branch-protection hook and `github-config.sh` already share — can never be
   auto-merged. This was the alternative to a second allowlist, and the reason is
   the same one that killed the repo inventory (below): a list that must be edited
   when a repo changes status is a list that is wrong most of the time. Here there
   is nothing to edit. Adding a repo to that file removes its auto-merge in the
   same commit that starts requiring review, and the two can never disagree.
3. **Re-checked against the current head, not the inspected one — re-keyed
   2026-09-08.** Base is the default branch, head is a `dispatch/…` branch in
   this same repo (never a fork), no `.github/workflows|actions` path,
   sideclaw's own 40-file/2000-line episode ceilings still hold as a
   **backstop**, and `mergeable` is `true` (a real conflict signal). The
   **primary** gate is now `config/triage-policy.json`'s `repos.<repo>` entry:
   EVERY changed path must match its `autoMergePaths` glob list (a repo absent
   from `repos`, or with none declared, refuses outright — no implicit allow),
   and the head commit's CI check-runs must either all conclude
   `success`/`neutral`/`skipped` or the repo must explicitly set
   `noCiRequired: true`. **What this replaced, and why**: `mergeable_state ==
   "clean"` used to stand in for "CI passed" — measured wrong, since GitHub
   reports `clean` whenever a repo has ZERO required checks (`vps` has no
   `.github/workflows` at all), so that condition was passing with nothing
   having run. A repo with zero check-runs and no `noCiRequired` acknowledgement
   now FAILS this gate, which is the whole point of the inversion. The step-7
   validation (see `docs/triage.md`) must also read `dispatches.validation_status
   == 'confirmed'` — a missing, disagreeing, or errored review blocks the merge,
   never read as a pass. The merge call **pins the head SHA**, so a push landing
   between inspection and merge fails the merge rather than riding it.
4. **The order of operations is a bound.** Un-drafting happens *after* every
   check, so a PR that fails one is never left ready-for-review as a side effect
   of being refused — and `--confirm`'s absence stops it before that point, which
   is why the plan output can honestly say nothing changed on GitHub.

Its ceiling is 3/day (`HERMES_CC_MERGE_BUDGET`), tighter than the 5 `implement`
episodes that can produce candidates: not everything that gets written should
land. Its audit mode is `merged` and not `opened` — grepping the log for what
actually reached a default branch is the reason the log exists. The GitHub
credential goes in as a curl config on **stdin, never argv** — this machine runs
triage that reads `ps` output, so a token in the process table is a real leak
path, and a test asserts it never appears there.

**Deploy rides the same call, OFF by default.** On a successful merge,
`cmd_merge` checks the repo's own `autoDeploy` (default **false** — ships
reviewed but inert everywhere) and `deploy` key (a closed allowlist,
`deploy_argv()` — the policy names a KEY, never a command, same principle as
the repo argument itself). Seeded with exactly one: `hyperdx-apply` → `ssh
vps "cd ~/vps && make hyperdx-apply ENV=prod"`. The outcome (`attempted`,
`ok`, and — for `observability/alerts/*.json` paths — the expected
`name`/`threshold`/`thresholdType` fetched at the merge SHA) rides in the
merge response's `deploy` field, which `scripts/triage.py`'s step-10
liveness check later reads back against. See `docs/triage.md`'s *Closing the
loop* for the full chain and how to turn `autoDeploy` on.

**What this does not solve.** `--confirm` is still instruction-level, and now it
gates the most consequential verb in the script. The bounds above are structural
and hold against a confused agent; none of them holds against an agent that has
decided to lie, because it can pass `--confirm` itself. That was accepted
knowingly — the mitigation is the signed approval artifact, below.

## Return path, derived not chosen

**A dispatch reports where it was born, and deposits its artifact where the
artifact belongs.** No per-call decision:

- Born in a Slack thread → progress and verdict land in that thread.
- Born from a watchdog event → the event carries `dispatch_id`; the digest
  reports outcome instead of re-reminding.
- Produced an issue or PR → the detail lives there; Slack gets a pointer, not a
  transcript.

Two delivery mechanisms, one message body:

| Duration | Mechanism |
|-|-|
| under ~3 min (`investigate`) | Hermes polls in-turn and answers in the thread it is already in |
| longer (`author`, `implement`) | the 5-min sweeper posts into `origin_thread_ts` |

**A sweeper-delivered verdict does not enter the thread's session context.**
`plugins/platforms/slack/adapter.py` drops the bot's own messages on ingest to
prevent echo loops, keyed on the sender's user id — which a `chat.postMessage`
with the Hermes bot token carries. So a sweeper-delivered verdict is visible to a
human but invisible to the session. The compensation is in the skill: when a
thread references a dispatch, Hermes re-reads it with `hermes-cc.sh status
<job-id>`. The dispatch record is the durable copy; the Slack message is only a
notification.

**At-least-once for the verdict, at-most-once for the nudge.** Because the
verdict posts as Hermes's own bot (dropped by ingest), a `done` + `implement` +
`artifactUrl` + unmerged dispatch also gets a nudge via argo's Slack API (posting
as the HomeLab bot, which Hermes *does* ingest), so Hermes can decide whether to
`merge`. The nudge carries only bridge-owned fields (job id, repo, tier, artifact
URL), never episode prose — a sentinel test asserts it, and a `merged_at` row
rewrites the header/artifact/next line so it never says "review this draft PR"
for one already merged. The nudge fires strictly after `reported_at` is stamped,
best-effort, never raising — a nudge that gated the stamp would re-send the
verdict *and* re-wake Hermes on the next sweep.

## Bounding

The dangerous composition is an **LLM-authored brief** plus a **write-capable
session**. Hermes reads untrusted input all day — Slack, GitHub issue bodies,
OTEL logs, web pages — so a prompt injection that reaches a brief must not reach
arbitrary code execution.

1. **A repo is named, never pathed**, and resolved under one confined root with a
   `deny` list and a per-repo tier ceiling. The name must be a single segment
   (`.`, `..` and dotted names refused) and the resolved checkout's parent must
   BE the root, so neither a traversal nor a symlink reaches outside it. No
   free-form paths, ever.
2. **The brief is data, never command.** Passed as a file, never interpolated
   into a shell string — the `rd bg` base64 lesson, one level up.
3. **`implement` needs `--why` and `--confirm`.** `--confirm` means Johannes
   confirmed, which in Slack means Hermes had to ask first — see *the signed
   approval artifact* below for what actually backs that now.
4. **Worktree isolation** on every tier (see *deviations* above), so a bad
   episode never touches the live checkout other agents on the mini are using.
5. **The episode never merges and never pushes to a default branch.** Branch +
   draft PR only. Landing it is the separate `merge` verb, which the episode
   cannot call.
6. **No secrets in a brief.** The episode resolves its own via `secrets-run`.
7. **A daily dispatch budget** in `hermes-cc.sh`. `--max-budget-usd` is API-only
   and does **not** cap a Max session, so the ceiling has to be structural:
   `maxTurns`, timeout, sideclaw's concurrency cap, and a per-day count (20/day,
   ≤5 `implement`, ≤3 `merge`, 170s `--wait` cap — under the `terminal` tool's
   180s default, so an in-turn verdict is delivered in-turn).

   **The ceilings are reported on the way up, not only when they refuse.** Every
   reporting path — dispatch, the `--dry-run` plan, `status`, `list` — carries a
   `budget` object with both counts, and a `budget.warning` naming the env var
   once one is close. The first build computed the counts only inside the
   refusal path, so a bound nobody can see approaching read as the tool
   breaking, not as a budget. Counts are re-read after the row is inserted so a
   caller's number includes its own dispatch. Raising a ceiling stays Johannes's
   call — `HERMES_CC_{DAILY,IMPLEMENT,MERGE}_BUDGET`, and `claude-dispatch`
   forbids the agent composing an invocation that sets any of them.
8. **Audit log on every invocation**, including refusals and dry runs — five
   modes: `opened`, `planned`, `dry-run`, `refused`, `merged`.

## Cost

Max quota is the binding constraint, not tokens-as-money. The cheap filter is
Hermes deciding *whether* an episode is worth opening — it holds the state, so it
is the right place to make that call. Measured floor for a trivial `-p` run on
the mini: 3.0s wall, ~25k cache-creation tokens (system prompt + `CLAUDE.md`
discovery). `--bare` would cut that and is **unusable**: it hard-disables OAuth,
flipping billing to API credits. Default model `sonnet` for every tier; `opus`
only on explicit request.

## Not this bridge

- **Infra mutation.** `hermes-ops.sh` owns restart/redeploy/uk-sync with its own
  verb set and tiering. A dispatch that wants to restart a container is a bug.
- **Anthropic's own Slack integration.** It works on Max — but it clones from
  GitHub into an Anthropic cloud VM: no tailnet, no `secrets-run` cache, no
  `~/.claude/skills`, one PR per session. It cannot reach homelab, vps, `brain`,
  or any local-only repo. Possibly a complement for pure GitHub-code issues;
  never a replacement. **Claude Tag is Team/Enterprise only** — unavailable on
  Max, so that door is closed entirely.
- **Long-lived interactive sessions.** A dispatch is an episode with a verdict.
  Mid-run steering ("actually do X instead") is `rd bg` + `rd say`, which already
  exists and is the right tool for that shape.

## Decisions — why each bound is shaped this way

**Repo resolution replaced an enumeration, and the enumeration is the lesson.**
The first cut (2026-08-02) was a per-repo inventory where absence meant denial,
and it rotted — 22 repos listed against 30 on disk, three of them unreachable
since they were cloned, with no way to tell a stale omission from a deliberate
one. Discovery under a confined root plus an explicit `deny` keeps the denials
meaningful and stops the file needing an edit per clone. What did not change is
the property that matters: a path never crosses the interface. Composing one
from caller input is a step the old map lookup never took, so `resolve_repo`
carries the weight now — the name must be a single segment (the old
`[A-Za-z0-9_.-]` class admitted `.`/`..` harmlessly as dict keys and would not
have as path components), and the resolved checkout's parent must **be** the
resolved root, so a symlink planted in the root cannot point out of it. Both are
regression-tested. `dotfiles-private`/`homelab-private` are denied and stay
denied; `brain` is **not** — it moved to `tiers.investigate` on 2026-08-15
(read-only, worktree-isolated, the one path that loads the vault's own rule
hierarchy).

**`sensitive` is a narrow, explicit carve-out of `deny`, not a second door.**
sideclaw shipped `sensitive: true` (`fe40d30`, `docs/dispatch-security.md` §
Sensitive dispatch on that side): a repo opted in gets `investigate` and only
`investigate`, with the returned verdict scanned by the same
`scanForSecrets`/`SECRET_PATTERNS` that already guard issue and PR bodies —
a match withholds the verdict behind a notice and keeps the full text in an
owner-only `0600` file on the mini rather than leaking it. Until this change
`hermes-cc.sh` never sent `sensitive` and `dispatch-repos.json`'s `deny` check
ran before any tier logic and was absolute, so the capability was unreachable
from Hermes — the one mechanically-fixable gap two independent adversarial
reviews both found: an `homelab-private/uptime-kuma` alert flapping on its own
retry cadence, and a dead 1Password ref, were both permanently undiagnosable
because the repo that would answer either question was denied outright.

`dispatch-repos.json` now carries `"sensitive": ["dotfiles-private",
"homelab-private"]` **in addition to** `deny` — both names stay listed in
`deny`, so a reader who greps only `deny` still sees the denial and the
default reachable from `deny` alone is unchanged: refusal at every tier.
`sensitive` narrows that refusal for a caller that explicitly asks, and only
for `investigate`; `resolve_tier` refuses `author`/`implement` against a
sensitive repo by name ("a filed issue or a pushed branch has no safe
artifact path in a secret-bearing repo"), not by falling through to the
generic ceiling message. A name in `sensitive` that is **not** also in `deny`
is refused as a malformed policy (exit 2) — the same contradiction class as a
name in both `deny` and `tiers`, and checked the same way, before discovery
ever runs. `hermes-cc.sh` submits `"sensitive": true` on the job body only for
those two repos; sideclaw re-checks the same investigate-only restriction
independently (`assertSensitiveTierAllowed`) rather than trusting the flag on
its own — defence in depth on both sides of the bridge, not a single point of
trust.

**There is no `implement` allowlist, deliberately.** One existed for about a day
(`hermes-agent`, `sideclaw`, `usage-tracker`, the scratch target) and went the
same way the repo inventory did: a list that must be edited before the tool can
do its job is a list that will be stale exactly when it is needed. So an
unattended episode can file a world-readable issue, or open a draft PR, on a
public repo with no human gate — also an owner decision. What bounds `implement`
is the shape of the tier (isolated worktree, `dispatch/…` branch, draft PR,
`--why` **and** `--confirm`) rather than a roster of names, and nothing reaches a
default branch without the separate `merge` verb. Worst unattended outcome is a
draft PR nobody wanted, which costs one click.

**`--confirm` became a signed artifact instead of an instruction (2026-08-03).**
It started as a flag on the same invocation, set by the same agent it
constrains — plainly not a bound. Now the plan branch posts **Approve/Deny
buttons** into the origin channel; the click lands in the gateway, which signs it
with an **Ed25519 key minted at startup, held in RAM only**
(`plugins/dispatch-approval/`, public half at `~/.hermes/dispatch-approval.pub`)
and **runs the approved verb itself** — the plan row stores the argv (minus the
`--confirm`/`--wait` flags and minus the `--brief-file`/`--context-file`
*paths*) plus the brief and context **bytes**; Approve re-runs `hermes-cc.sh …
--confirm` in a subprocess (the same signature check as a hand-typed
`--confirm`) and posts the outcome via `hermes send`. The point is not "who
clicked" — it is that a click is not text. All Slack senders here are trusted
(see `allow_bots`, below); the residual risk is hostile *content* relayed by a
trusted one, and injected prose cannot mint a signature or cause a Slack
interaction payload to exist. Every column of `dispatch_approvals` is writable
by this uid, the agent's included, so only the signature is consulted — the
forged-row case is the centre of `tests/test_dispatch_approval.py`.

Bound to `verb|repo|tier|brief|why|context`, single-use, 30-min TTL, **fails
closed** on no plugin / no key / no gateway / expired / spent / hash mismatch; a
gateway restart voids pending approvals. The budget is checked before the gate
spends the row, so an over-budget click refuses with the approval intact.
**The one bug this has had:** `register()` runs in every process that discovers
plugins — a CLI call, a cron subprocess — and the first build published the
public key unconditionally, so a non-gateway process could overwrite it with a
key nothing would ever sign with. Symptom: a visible Approve click, a validly
signed row, and `--confirm` still refusing as *"has not been clicked yet"*. Two
properties close it: publish only when argv says `gateway run`, and republish on
the way to signing whenever the file on disk is not ours. Tell:
`grep 'published public key'` vs `Wired 2 plugin action handler` in
`~/.hermes/logs/agent.log` — a publish with no matching wire line means a
non-gateway process overwrote the key. Enable once with
`hermes plugins enable dispatch-approval`.

**`merge` is deliberately NOT gated on the signed approval — reverted after
about an hour on 2026-08-03.** It was gated briefly on the argument that the
implement approval covers the *change* and not the *diff*, which did not exist
yet when it was approved. Reverted the same day: a second click per PR trains
the rubber stamp this design already warns about, and it buys little against the
bounds the verb already carries (job-id lookup, every implement-time check
re-run against the current head, a pinned head SHA, its own 3/day ceiling).
Gating `dispatch` is what earns its keep, because that is where an unattended
episode starts writing from a brief that may trace to third-party text.

**`slack.allow_bots: all` is deliberate — do not "fix" it (owner decision,
2026-08-02).** Anything that can post in the workspace can reach an agent that
can now merge to a default branch. Raised as a hole and rejected: HomeLab, VPS
and Argo all post from inside the tailnet, they are Johannes's own infra, and
gating them would break the self-healing premise the bridge exists to serve.
`allow_bots` is load-bearing for live auto-triage — Hermes ingesting an
UptimeKuma alert in `#alerts` and answering it — which the watchdog's own
argo-API read of `#alerts` does not depend on at all. **The trust boundary is
the workspace, not the human/bot distinction**; the real exposure is hostile
*content* relayed by a trusted sender, which is why `watchdog-poll.py` and
`briefing-coverage.py` mark non-`jkrumm` GitHub items as third-party instead of
authenticating the messenger.

**Tests.** `tests/test_hermes_cc.py` (134 cases, stubbed job server and stubbed
GitHub — never a real one of either), `tests/test_dispatch_approval.py` (21
checks on the signed gate, centred on the forged-row case),
`tests/test_raw_agent_guard.py` (51/51 blocked, 42/42 allowed) and
`tests/test_repo_write_guard.py` (71/71 blocked, 55/55 allowed) — the guards
that make the bridge non-optional, detail in `docs/guards.md`. Run with
`~/.hermes/hermes-agent/venv/bin/python3`. **The other half is tested in
sideclaw**: `sideclaw/tests/` (`bun test`, mutation-verified) covers worktree
isolation and its post-crash sweep, the diff-refusal ladder, the added-lines
secret scan, `pushBranch`'s refusals against a local bare `origin`, the nonce
fence around the untrusted brief, and the salvage discrimination — count owned
by sideclaw, not restated here since it already drifted once.

> **The GitHub credential is `op://mini/github/token`, and it needs three
> permissions.** `Contents: write` (the branch push) **plus** `Issues: write`
> and `Pull requests: write` (the artifact). A token holding only the first
> pushes the branch and then fails at the last step with GitHub's own opaque
> "Resource not accessible by personal access token"; `describeGithubFailure` in
> sideclaw's `dispatch-git.ts` rewrites it to name both. sideclaw's `gho_`
> `GITHUB_TOKEN` fallback is a token class retired from the git credential path
> elsewhere for expiring silently — the op:// ref is tried first and the
> fallback must not quietly become the real dependency.
