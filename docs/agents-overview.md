# Agents overview — status across every Claude Code / herdr agent

sideclaw (`http://localhost:7705`, the same daemon `warden` reaches through the
`scripts/hermes-cc.sh` exec shim for the dispatch bridge) tracks every Claude Code / herdr agent running across every
project and summarizes each into a one-word recommendation (`answer`, `continue`,
`ship`, `review`, `merge`, `close`, `stale`, `watch`). This feature surfaces that
summary through read-only surfaces — nothing here ever steers an agent.

## The surfaces

| Surface | What | Where |
|-|-|-|
| Conversational | "what are my agents doing", "wo steht `<project>`" | `skills/agents/SKILL.md` — reads `/api/overview.txt`, refreshes on request |
| Morning briefing | an "Agenten & Projekte" section, ≤ 6 lines, German | `scripts/agents-overview.py --briefing`, called from `scripts/briefing-context.py`, rendered per `cron/morning-briefing.prompt.txt` |
| On-demand Slack post | "post the overview to #agents" (or a screenshot request) | `scripts/agents-overview.py --post-full`, posts Block Kit via `chat.postMessage`, no schedule, no state |

**Retired: the scheduled Slack digest.** `scripts/agents-overview.py
--slack-body`, run every 30 min by cron job `72aa2fb36307`, was paused
2026-09-08 18:45 after reposting the same blocked pane ~35 times in two days
and retired 2026-09-11. Its code (`render_slack()`, the `fetch_agents()`/
`fingerprint()`/`delta()` change-detection chain, the once-per-day
unreachable warning, the state file) was removed from the script 2026-09-12
once nothing referenced it any more — see `docs/scheduled-jobs.md` for the
retirement history and how to recreate it from git if ever needed. Replaced
by Warden's card board in `#agents` (one deduplicated `chat.update`d card per
item), the same sideclaw snapshot in the herdr overview pane, this file's
morning-briefing surface, and Argo's `/agents` page and Warden board. The
morning briefing (`render_briefing()`) re-surfaces every non-quiet
recommendation daily, which is what keeps a forgotten standing question from
vanishing for good.

## Needs you (human queue)

`data.humanQueue` (sideclaw, 2026-09-07) is the mini's ask-human queue —
`[{id, askedAt, question, cmd?}]`, work that needs a PRESENT human (a
biometric `op`, an ACL push, `make human-queue`). It renders as a "Needs you"
section at the top of the briefing and at the top of the `--post-full`
overview. An agent in state `needs_you` is **always** listed in the
briefing, whatever its recommendation — `summary.needsYou` counts by state,
and a render whose header says "1 need you" must show that one item
(`_is_needs_you()` is checked independently of the actionable-recommendation
filter).

## Refresh is consumer-driven, not clock-driven

The briefing does not refresh on a fixed clock — it decides for itself
whether the LLM overview pass (`overview` job) is worth its own model call.
After `fetch()`, if `data.overview` is null or its `ageMs` is older than
`HERMES_AGENTS_BRIEFING_MAX_AGE_S` (default 7200s = 2h), `--briefing` calls
`refresh()` before rendering. If that refresh fails, it renders the cached
data anyway and appends one line noting how old the verdicts are, rather
than blocking the briefing on sideclaw. `--post-full` never refreshes — it
posts whatever the cached overview currently holds.

## Read-only, by design

This feature never sends keys to a herdr pane and never opens a dispatch — it
only calls sideclaw's `GET /api/overview[.txt]` and, when the cached overview
is stale, `POST /api/jobs {"tool":"overview"}` to trigger a fresh
summarization pass. Steering an agent (answering it, nudging it, opening a
new episode) stays `claude-dispatch`'s job. `scripts/agents-overview.py`'s
render functions are pure given an overview snapshot — `fetch`/`refresh` are
the only network calls, everything else (`render_briefing`,
`render_slack_blocks`) is unit-tested in `tests/test_agents_overview.py` with
no network at all.

## Rendering: Block Kit, escaping, `--post-full`

`render_slack_blocks(cur)` is the pure Block Kit builder (no network) for the
`--post-full` overview — `header` (counts), one `section` per project (`*name*
\`branch[*if dirty]\`` then one line per agent: emoji + title + standing,
plus an indented `↳ _blocker_` line when set), `divider`s between projects,
and a trailing `context` line with the overview's age, model and time. It
shows every agent that has any recommendation. Projects sort with any
`answer` agent first, then ship/merge/review, then the rest; capped at
`BLOCKS_MAX` (50) total blocks — lowest-priority projects are dropped first,
replaced by a trailing `… and N more projects` context block.

**Escaping.** Titles, standings and blockers come from agent transcripts —
attacker-influenced — so `&`, `<`, `>` are always escaped before being
placed in mrkdwn text, closing off both accidental markup and a `<@user>`
mention forgery.

**Posting.** `post_blocks(channel, blocks, text_fallback, token)` calls
`chat.postMessage` directly (bearer token, `unfurl_links: false`). On
failure it returns `False` and `--post-full` reports the failure and exits
non-zero — there is no fallback delivery path once posting is the whole
point of the command.

**Token resolution.** `SLACK_BOT_TOKEN` is Tier-1-stripped from every
subprocess the gateway spawns (`tools/environments/local.py`'s
`_ALWAYS_STRIP_KEYS` — the same treatment as `GITHUB_TOKEN`), so a
cron-run `--post-full` never sees it via `os.environ`.
`resolve_slack_token()` mirrors warden's `watchdog-poll.py` `resolve_secret()`
pattern: inherited env first, else `secrets-run read op://hermes/slack/bot-token`
against the encrypted cache.

```bash
python3 ~/SourceRoot/hermes-agent/scripts/agents-overview.py --post-full
```

## Env override

`HERMES_AGENTS_SIDECLAW_BASE` — override the sideclaw base URL (default
`http://localhost:7705`), same pattern as `warden`'s
`WARDEN_SIDECLAW_BASE`. `HERMES_AGENTS_CHANNEL` — override the target
Slack channel for `--post-full` (default `C0BVDE5R562`).
