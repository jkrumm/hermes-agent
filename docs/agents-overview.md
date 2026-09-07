# Agents overview — status across every Claude Code / herdr agent

sideclaw (`http://localhost:7705`, the same daemon `scripts/hermes-cc.sh` uses for
the dispatch bridge) tracks every Claude Code / herdr agent running across every
project and summarizes each into a one-word recommendation (`answer`, `continue`,
`ship`, `review`, `merge`, `close`, `stale`, `watch`). This feature surfaces that
summary through three read-only surfaces — nothing here ever steers an agent.

## The three surfaces

| Surface | What | Where |
|-|-|-|
| Conversational | "what are my agents doing", "wo steht `<project>`" | `skills/agents/SKILL.md` — reads `/api/overview.txt`, refreshes on request |
| Scheduled Slack digest | a ping only when something changed since the last run — silent otherwise | `scripts/agents-overview.py --slack-body`, run every 30 min by `scripts/agents-cron.py` (job `72aa2fb36307`, registration below) |
| Morning briefing | an "Agenten & Projekte" section, ≤ 6 lines, German | `scripts/agents-overview.py --briefing`, called from `scripts/briefing-context.py`, rendered per `cron/morning-briefing.prompt.txt` |

**The Slack digest never reposts a persistent, unchanged item — including a
standing `answer` item.** Silence is gated purely on `delta()` finding a change
since the last run (new agent, changed recommendation, disappeared agent); an
agent stuck on `answer` for days speaks once, when it first becomes `answer`,
and then goes quiet again every 30-min cycle until something actually changes.
The morning briefing (`render_briefing()`) re-surfaces every non-quiet
recommendation daily regardless of `delta()`, which is what keeps a forgotten
standing question from vanishing for good.

## Needs you (human queue)

`data.humanQueue` (sideclaw, 2026-09-07) is the mini's ask-human queue —
`[{id, askedAt, question, cmd?}]`, work that needs a PRESENT human (a
biometric `op`, an ACL push, `make human-queue`). It renders as a "Needs you"
section at the top of both the digest and the briefing; every entry counts as
a delta the moment it appears or is drained, and its ids ride the fingerprint
so a new ask alone wakes the digest. An agent in state `needs_you` is **always**
listed, whatever its recommendation — `summary.needsYou` counts by state, and a
digest whose header says "1 need you" must show that one item (a 2026-09-07 bug
counted one and listed none because the body filtered on recommendation alone;
`_is_needs_you()` is now checked independently of the actionable-recommendation
filter). When sideclaw is unreachable end to end, the digest is not silent:
once per day a warning line goes to `#agents` via stdout (the no_agent runner
delivers it) so "no digest" and "sideclaw is down" stop looking identical —
Kuma does not watch this path, this line is the health signal.

## Refresh is consumer-driven, not clock-driven

Neither surface refreshes on a fixed clock — each decides for itself whether
the LLM overview pass (`overview` job) is worth its own model call:

- **The morning briefing refreshes when the cached overview is stale.** After
  `fetch()`, if `data.overview` is null or its `ageMs` is older than
  `HERMES_AGENTS_BRIEFING_MAX_AGE_S` (default 7200s = 2h), `--briefing` calls
  `refresh()` before rendering. If that refresh fails, it renders the cached
  data anyway and appends one line noting how old the verdicts are, rather
  than blocking the briefing on sideclaw.
- **The digest cron refreshes only when something actually moved.** Before
  ever touching the model, `--slack-body` fetches the deterministic
  `GET /api/agents` snapshot (same shape as `/api/overview`, minus the LLM
  fields) and hashes it with `fingerprint()` — sha256 over the sorted
  `(agent.id, agent.state, agent.lastActivityAt, project.name,
  project.git.dirty, project.git.ahead)` rows. If that fingerprint matches
  the one saved from the previous run, it exits silently: no refresh, no
  state write, no output. Only a changed fingerprint triggers the existing
  `refresh()` → `delta()` → `render_slack()` path. On an idle night this
  costs zero model calls, every cycle.

## Read-only, by design

This feature never sends keys to a herdr pane and never opens a dispatch — it only
calls sideclaw's `GET /api/overview[.txt]` and, for the Slack digest, `POST
/api/jobs {"tool":"overview"}` to trigger a fresh summarization pass. Steering an
agent (answering it, nudging it, opening a new episode) stays `claude-dispatch`'s
job. `scripts/agents-overview.py`'s functions are pure given an overview snapshot —
`fetch`/`refresh` are the only network calls, everything else (`delta`,
`render_slack`, `render_briefing`) is unit-tested in `tests/test_agents_overview.py`
with no network at all.

## State file

`~/.hermes/agents-overview-state.json` — the last overview snapshot seen by
`--slack-body`, plus its `fingerprint` (see above), used by `delta()` and the
fingerprint comparison to decide whether anything changed since the previous
run. Gitignored runtime state, like `briefing-state.json`; deleting it just
means the next run treats every current agent as new (so it speaks once, then
goes quiet again on the following run if nothing changed) and always refreshes
once to re-establish a baseline fingerprint. Written atomically (temp file +
rename).

## Registering the Slack digest cron

Registered 2026-09-07 as job `72aa2fb36307` (see the registry in `docs/scheduled-jobs.md`).
The steps, kept for a re-install:

1. Create the Slack channel `#agents`, invite the Hermes bot, and record its
   channel ID in this repo's `README.md` Channel Architecture table (the same
   place every other channel — `#alerts`, `#watchdog`, etc. — is documented).
2. Register the job (schedule is a **positional** argument, not `--schedule`;
   `--script` takes a bare filename under `~/.hermes/scripts/`, not a `scripts/`-
   prefixed path — verified against `hermes cron create --help` on this machine):

   ```bash
   hermes cron create "*/30 * * * *" --name "Agents overview" \
     --script agents-cron.py --no-agent --deliver slack:C0BVDE5R562   # registered 2026-09-07 as job 72aa2fb36307
   ```

3. Verify with `hermes cron list` — it should show `Script: agents-cron.py`,
   `Mode: no-agent (script stdout delivered directly)`.

`scripts/agents-cron.py` is deliberately a thin loader (mirrors
`scripts/dispatch-sweep-cron.py`'s shape) that imports `agents-overview.py` and
calls `main(["--slack-body"])` — `hermes cron create --script` runs the referenced
file through `cron/lifecycle_guard.py`, which fails closed on a long file or one
whose comments quote command lines (see CLAUDE.md § "Dispatch Bridge"). Keep the
entry point thin; put logic in the imported module.

## Rendering: Block Kit, escaping, the fallback rule, `--post-full`

The `#agents` digest posts as Slack Block Kit, not plain mrkdwn.
`render_slack_blocks(cur, changes, *, full=False)` is the pure builder (no
network) — `header` (counts), one `section` per project (`*name*
\`branch[*if dirty]\`` then one line per agent: emoji + title + standing,
plus an indented `↳ _blocker_` line when set), `divider`s between projects,
and a trailing `context` line with the overview's age, model, change count
and time. `full=False` (the cron digest) shows only agents whose
recommendation is actionable (answer/ship/merge/review) **or** whose id is
tagged in `changes` (`delta()` appends a trailing `[id:...]` to each entry
for exactly this) — so a newly-changed but non-actionable agent (e.g. ->
`close`) still shows up, while a persistent unchanged `watch`/`continue`
agent doesn't. `full=True` (`--post-full`) shows every agent with any
recommendation. Projects sort with any `answer` agent first, then
ship/merge/review, then the rest; capped at `BLOCKS_MAX` (50) total blocks
— lowest-priority projects are dropped first, replaced by a trailing
`… and N more projects` context block.

**Escaping.** Titles, standings and blockers come from agent transcripts —
attacker-influenced — so `&`, `<`, `>` are always escaped before being
placed in mrkdwn text, closing off both accidental markup and a `<@user>`
mention forgery.

**Posting and the fallback rule.** `post_blocks(channel, blocks,
text_fallback, token)` calls `chat.postMessage` directly (bearer token,
`unfurl_links: false`). `--slack-body` still computes the plain mrkdwn body
via `render_slack()` first — silence (empty string) is still the normal
case when nothing changed. When there IS something to post: if
`resolve_slack_token()` finds a token and `post_blocks()` reports
`ok: true`, the script prints **nothing** to stdout (the no_agent runner
would otherwise deliver the mrkdwn body a second time) and logs the outcome
to stderr only. If the token is missing or the post fails, it prints the
mrkdwn body to stdout exactly as before, so delivery still happens through
the runner's own no_agent path.

**Token resolution.** `SLACK_BOT_TOKEN` is Tier-1-stripped from every
subprocess the gateway spawns (`tools/environments/local.py`'s
`_ALWAYS_STRIP_KEYS` — the same treatment as `GITHUB_TOKEN`), so a
cron-run `--slack-body`/`--post-full` never sees it via `os.environ`.
`resolve_slack_token()` mirrors `watchdog-poll.py`'s `resolve_secret()`
pattern: inherited env first, else `secrets-run read op://hermes/slack/bot-token`
against the encrypted cache.

**`--post-full`** posts the `full=True` overview to `#agents` (or
`HERMES_AGENTS_CHANNEL`) on demand, regardless of whether anything changed,
with no state write — used from the skill ("post the overview to #agents")
and for screenshots:

```bash
python3 ~/SourceRoot/hermes-agent/scripts/agents-overview.py --post-full
```

## Env override

`HERMES_AGENTS_SIDECLAW_BASE` — override the sideclaw base URL (default
`http://localhost:7705`), same pattern as `hermes-cc.sh`'s
`HERMES_CC_SIDECLAW_BASE`. `HERMES_AGENTS_CHANNEL` — override the target
Slack channel for both `--slack-body` and `--post-full` (default
`C0BVDE5R562`).
