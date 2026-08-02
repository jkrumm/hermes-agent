# Dispatch Bridge — Hermes hands work to Claude Code

STATUS: Phases 1-3 built and committed (2026-08-02). Phase 4 (`author`/`implement`) not started.
See hermes-agent CLAUDE.md § "Dispatch Bridge" and sideclaw CLAUDE.md § "Dispatch Tool"
for what actually shipped, including the deviations recorded below.

**The claim:** Hermes should never do repo work, and Claude Code should never
watch for it. Hermes observes and decides; Claude Code executes bounded episodes
inside one repo; a single dispatch record ties the two together. Everything else
in this document follows from that split.

## Why this exists

Hermes finds things — a red monitor, an OTEL error burst, a stray skill, a GitHub
issue going stale. It routes them well (`capture` already decides GitHub-issue vs
TickTick correctly). Then it stops, because triage needs to *read the repo* and
DeepSeek-V4-Flash with a `terminal` tool is the wrong instrument for that. Today
the loop closes only when Johannes opens Claude Code by hand.

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
| `investigate` | `readOnly` (`Read,Bash,Grep,Glob`), `--json-schema` verdict | a verdict object | none | 30s–3min |
| `author` | `readOnly` + `gh issue create` | GitHub issue | none | 1–4min |
| `implement` | write, `--worktree`, branch push | branch + **PR** | `--why` **and** `--confirm` | 10–40min |

`investigate` is the tier that fixes the stated pain and it needs no approval
theatre — a read-only session in a git repo cannot lose anything.

**`implement` always ends in a PR, in every repo, including direct-to-master
ones.** This deviates from the repo's normal convention on purpose: a human wrote
the direct-to-master rule for their own commits, not for an unattended agent's.
Never merge, never push to a default branch.

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
  created_at        TEXT NOT NULL,
  finished_at       TEXT,
  reported_at       TEXT                    -- NULL ⇒ the sweeper still owes a message
);
```

`reported_at` is the whole delivery contract. A finished dispatch with
`reported_at IS NULL` is an unpaid debt; the sweeper pays it and stamps it. A
missed notification is retried on the next sweep instead of being lost — which is
why this polls rather than taking a webhook.

## Component split

**sideclaw owns the episode. Hermes owns the lifecycle.** Both halves are useful
to other consumers, which is why neither lives in the other.

### sideclaw — new `dispatch` job tool

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

### hermes-agent — the bounded client

Mirrors `hermes-ops.sh` exactly, because that pattern is already proven here:

- **`scripts/hermes-cc.sh`** — closed verb set (`dispatch`, `status`, `list`,
  `cancel`), no free-form paths, `--why`+`--confirm` on `implement`, `--json`
  contract, audit log to `~/Library/Logs/hermes-cc.log`, tests under `tests/`.
- **`config/dispatch-repos.json`** — tracked allowlist, repo → max tier.
  Absence is a denial. `dotfiles-private` and `homelab-private` are absent and
  stay absent.
- **`skills/claude-dispatch/SKILL.md`** — when to reach for which tier, and the
  hard rule that infra mutation is `homelab-ops`, never this.
- **`scripts/dispatch-sweep.py`** — `no_agent` cron, every 5 min. Reads open
  dispatches, polls `GET localhost:7705/api/jobs/:id`, posts finished ones into
  their origin thread, stamps `reported_at`. **No LLM in the return path** — the
  verdict is schema-shaped, so formatting is deterministic and free.

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

**ANSWERED at build time (2026-08-02), and the answer is the less convenient one.**
Compound `slack:<C>:<thread_ts>` targets are real — `cron/scheduler.py` parses them via
`_parse_target_ref`, and the channel directory already lists live ones. Delivery works:
the sweeper uses `hermes send --to slack:<C>:<thread_ts>`, which reuses gateway
credentials and needs no LLM.

But a message delivered that way does **not** enter the thread's session context.
`plugins/platforms/slack/adapter.py:5381` drops the bot's own messages on ingest to
prevent echo loops, keyed on the sender's user id — which a `chat.postMessage` with the
Hermes bot token carries. Verified empirically: a threaded send succeeded and produced
zero ingest events in the gateway log.

So a sweeper-delivered verdict is visible to a human but invisible to the session. The
compensation is in the skill: when a thread references a dispatch, Hermes re-reads it with
`hermes-cc.sh status <job-id>`. The dispatch record is the durable copy; the Slack message
is only a notification.

## Bounding

The dangerous composition is an **LLM-authored brief** plus a **write-capable
session**. Hermes reads untrusted input all day — Slack, GitHub issue bodies,
OTEL logs, web pages — so a prompt injection that reaches a brief must not reach
arbitrary code execution.

1. **Closed repo allowlist**, per-repo max tier. No free-form paths, ever.
2. **The brief is data, never command.** Passed as a file, never interpolated
   into a shell string — the `rd bg` base64 lesson, one level up.
3. **`implement` needs `--why` and `--confirm`.** `--confirm` means Johannes
   confirmed, which in Slack means Hermes had to ask first. That is the gate.
4. **Worktree isolation** on `implement`, so a bad episode never touches the live
   checkout other agents on the mini are using.
5. **Never merge, never push to a default branch.** Branch + PR only.
6. **No secrets in a brief.** The episode resolves its own via `secrets-run`.
7. **A daily dispatch budget** in `hermes-cc.sh`. `--max-budget-usd` is API-only
   and does **not** cap a Max session, so the ceiling has to be structural:
   `maxTurns`, timeout, sideclaw's concurrency cap, and a per-day count.
8. **Audit log on every invocation**, including refusals and dry runs.

## Cost

Max quota is the binding constraint, not tokens-as-money. The cheap filter is
Hermes deciding *whether* an episode is worth opening — it holds the state, so it
is the right place to make that call. Measured floor for a trivial `-p` run on
the mini: 3.0s wall, ~25k cache-creation tokens (system prompt + `CLAUDE.md`
discovery). `--bare` would cut that and is **unusable**: it hard-disables OAuth,
flipping billing to API credits.

Default model `sonnet` for every tier. `opus` only on explicit request.

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

## Build phases

| Phase | Lands | Proves |
|-|-|-|
| 1 | sideclaw `dispatch` handler (`investigate` only) + MCP tool | the episode contract and the schema-shaped verdict |
| 2 | `hermes-cc.sh` + `claude-dispatch` skill + `dispatches` table + in-turn poll | Hermes can triage in a Slack thread |
| 3 | `dispatch-sweep.py` cron + the watchdog and briefing projections | the return path closes without a human polling |
| 4 | `author` and `implement` tiers, worktree + PR path | delegated code change with a review gate |

Phase 1 and 2 together are the thing that removes the daily friction. Phase 4 is
the one that can go wrong, and it goes last on purpose.

## Verified during design (2026-08-02)

- `claude -p` runs from a plain non-login `bash -c` on the mini with
  `CLAUDE_CODE_OAUTH_TOKEN` from `op://mini/claude/oauth-token`: 3.0s, Max auth,
  no keychain, no herdr. **`dotfiles/scripts/remote-dev.sh:325-333` and the
  global CLAUDE.md are stale** — they still state the herdr indirection is
  required for auth. It was, before that ref existed.
- CLI 2.1.220 carries every primitive this design needs: `--json-schema`,
  `--session-id <uuid>`, `--resume`, `--fork-session`,
  `--output-format stream-json`, `--permission-mode`, `--allowedTools`,
  `--worktree`, `--agents`.
- sideclaw is live on `:7705` with `SIDECLAW_WORKER_BACKEND=max`;
  `POST /api/jobs` gates on `isJobTool(body.tool)`, so a new tool is a
  registration plus a handler.
