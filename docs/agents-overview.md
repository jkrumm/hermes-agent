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
| Scheduled Slack digest | a ping only when something changed since the last run — silent otherwise | `scripts/agents-overview.py --slack-body`, run every 30 min by `scripts/agents-cron.py` (registration below, not yet installed) |
| Morning briefing | an "Agenten & Projekte" section, ≤ 6 lines, German | `scripts/agents-overview.py --briefing`, called from `scripts/briefing-context.py`, rendered per `cron/morning-briefing.prompt.txt` |

**The Slack digest never reposts a persistent, unchanged item — including a
standing `answer` item.** Silence is gated purely on `delta()` finding a change
since the last run (new agent, changed recommendation, disappeared agent); an
agent stuck on `answer` for days speaks once, when it first becomes `answer`,
and then goes quiet again every 30-min cycle until something actually changes.
The morning briefing (`render_briefing()`) re-surfaces every non-quiet
recommendation daily regardless of `delta()`, which is what keeps a forgotten
standing question from vanishing for good.

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
`--slack-body`, used by `delta()` to decide whether anything changed since the
previous run. Gitignored runtime state, like `briefing-state.json`; deleting it
just means the next run treats every current agent as new (so it speaks once, then
goes quiet again on the following run if nothing changed).

## Registering the Slack digest cron

Not registered yet — do this by hand once the `#agents` channel exists:

1. Create the Slack channel `#agents`, invite the Hermes bot, and record its
   channel ID in this repo's `README.md` Channel Architecture table (the same
   place every other channel — `#alerts`, `#watchdog`, etc. — is documented).
2. Register the job (schedule is a **positional** argument, not `--schedule`;
   `--script` takes a bare filename under `~/.hermes/scripts/`, not a `scripts/`-
   prefixed path — verified against `hermes cron create --help` on this machine):

   ```bash
   hermes cron create "*/30 * * * *" --name "Agents overview" \
     --script agents-cron.py --no-agent --deliver slack:<AGENTS_CHANNEL_ID>
   ```

3. Verify with `hermes cron list` — it should show `Script: agents-cron.py`,
   `Mode: no-agent (script stdout delivered directly)`.

`scripts/agents-cron.py` is deliberately a thin loader (mirrors
`scripts/dispatch-sweep-cron.py`'s shape) that imports `agents-overview.py` and
calls `main(["--slack-body"])` — `hermes cron create --script` runs the referenced
file through `cron/lifecycle_guard.py`, which fails closed on a long file or one
whose comments quote command lines (see CLAUDE.md § "Dispatch Bridge"). Keep the
entry point thin; put logic in the imported module.

## Env override

`HERMES_AGENTS_SIDECLAW_BASE` — override the sideclaw base URL (default
`http://localhost:7705`), same pattern as `hermes-cc.sh`'s
`HERMES_CC_SIDECLAW_BASE`.
