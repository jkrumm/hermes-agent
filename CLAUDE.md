# hermes-agent — Hermes Agent Instructions

## What This Repo Is

VCS source of truth for Johannes's Hermes Agent setup. Mac Mini-only deployment.
Everything in this repo is symlinked into `~/.hermes/` — edit at either end,
git always sees the change here.

Companion repo: `~/SourceRoot/dotfiles` — Claude Code dotfiles + the
`localai/` audio stack (mlx-audio, fish-s2-pro, helper). The `localai-helper`
plist template lives there; `make setup` here renders it. **dotfiles must be
cloned alongside hermes-agent** for `make setup` to succeed.

**After any edit: commit here.**

## Symlink Map

`make setup` writes the following symlinks:

| File here | Live path | Notes |
|-|-|-|
| `config.yaml` | `~/.hermes/config.yaml` | symlink — edit here, live immediately |
| `.env.tpl` | `~/.hermes/.env.tpl` | symlink |
| `SOUL.md` | `~/.hermes/SOUL.md` | symlink |
| `cron/` | `~/.hermes/cron/` | symlink — Hermes-driven (LLM) cron jobs |
| `scripts/` | `~/.hermes/scripts/` | symlink — Hermes cron pre-run scripts (security check requires they live under `HERMES_HOME/scripts/`). Also holds host-level shell scripts. |
| `hooks/` | `~/.hermes/hooks/` | symlink — add hooks here |
| `skills/{name}/` | `~/.hermes/skills/{name}/` | symlink per skill (argo-api, infrastructure, tasks, capture, schedule, weather, slack) |
| `USER.md` | `~/.hermes/memories/USER.md` | copied — Hermes writes to it |
| `cc-skills/hermes-validate/` | `~/SourceRoot/.claude/skills/hermes-validate/` | symlink — Claude Code slash command for validating Hermes routing |
| `cc-skills/hermes-update/` | `~/SourceRoot/.claude/skills/hermes-update/` | symlink — Claude Code slash command for updating the upstream Hermes repo |

**Host-level scripts (called by macOS `crontab`, not symlinked):**
- `scripts/hermes-liveness.sh` — every 5 min, checks gateway state + Slack connection, pings `$UPTIME_PUSH_HERMES` on success.
- `scripts/hermes-backup.sh` — daily 03:00, rsyncs `~/.hermes/` → `homelab:/mnt/hdd/backups/hermes/`, pings `$UPTIME_PUSH_BACKUP` on success.

**Hermes cron pre-run scripts (executed by `hermes-agent` before each cron run, *not* by macOS crontab):**
- `scripts/briefing-context.py` — reads `briefing-state.json` and emits `BRIEFING_CITY` + `BRIEFING_SUPPRESSED` for the morning briefing prompt. Calls `briefing-coverage.py` as subprocess. Output is appended as `## Script Output` block.
- `scripts/briefing-coverage.py` — full TickTick backlog + open GitHub items; emits `COVERAGE_AVAILABLE`, `TICKTICK_BACKLOG`, `TICKTICK_HIGH_PRIO_DATELESS`, `GITHUB_OPEN_BY_REPO`, `GITHUB_FRESH_48H`, `GITHUB_TOTAL` blocks. Called by `briefing-context.py`.
- `scripts/watchdog-poll.py` — polls UptimeKuma, Docker (homelab + vps), GitHub, Slack `#alerts`; reconciles against `~/.hermes/watchdog.db`. Emits `NEW=`, `REMINDERS=`, `RESOLVED=` blocks for the watchdog cron prompt.
- `scripts/watchdog-summary.py` — read-only snapshot of open watchdog items from `watchdog.db`; consumed by `briefing-context.py` for the morning briefing Infrastructure section.
- `scripts/briefing-state.json` — *gitignored* runtime config (city + vacation flag). Edit locally; never commits. Seeded from `briefing-state.example.json` on first `make setup`.
- `skills/capture/state.json` — *gitignored* runtime cache for the capture skill (GitHub repos + TickTick projects). Refreshed on miss via `gh repo list jkrumm` and `/ticktick/projects`. Seeded empty from `state.example.json` on first `make setup`.

## Homelab API Integration

`skills/argo-api/SKILL.md` endpoint tables are regenerated from `https://argo.jkrumm.com/api/docs/json` by the homelab `/docs` skill. Domain skills (infrastructure, tasks, capture, schedule, weather, slack) are updated in the same pass if their endpoints changed.

**API secret:** `op://common/api/SECRET` (account `tkrumm`) — wired in `.env.tpl`.

## Local Modifications to Upstream

Re-apply after `hermes update`:

- `~/.hermes/hermes-agent/tools/tts_tool.py` — thin client over `localai-helper:8001/v1/tts/synthesize`; replaces 1600-line multi-provider original. Source: `patches/tts_tool.py`. Re-apply: `cp ~/SourceRoot/hermes-agent/patches/tts_tool.py ~/.hermes/hermes-agent/tools/tts_tool.py`
- `~/.hermes/hermes-agent/gateway/platforms/slack.py` — three changes, all in `patches/slack-cannot-reply-to-message.patch`. Re-apply: `cd ~/.hermes/hermes-agent && git apply ~/SourceRoot/hermes-agent/patches/slack-cannot-reply-to-message.patch`. **Patch applies cleanly to v0.12** — all context lines unchanged in upstream.
  - `format_message()` pre-steps: normalize `*` list markers to `-`, strip backticks from inline code containing emoji shortcodes. **Not upstream.**
  - `_resolve_thread_ts` synthetic-thread guard: detect synthetic `thread_id == reply_to` (no real `thread_ts`) → return `None`. **Not upstream.** v0.12 added a similar guard but gated on `reply_in_thread: false` only — our config uses `reply_in_thread: true`, so v0.12's guard is a no-op for us.
  - `send()` retry: on `cannot_reply_to_message`, drop `thread_ts` and retry chunk as plain channel message. **Not upstream.**
- `~/.hermes/hermes-agent/cron/scheduler.py` — skip `resolve_channel_name` for raw Slack channel IDs in `_resolve_single_delivery_target`. Source: `patches/scheduler-skip-resolver-for-slack-ids.patch`. Re-apply: `cd ~/.hermes/hermes-agent && git apply ~/SourceRoot/hermes-agent/patches/scheduler-skip-resolver-for-slack-ids.patch`. Without this, `--deliver slack:<C…ID>` fails with `channel_not_found` for any channel that has exactly one thread session in the directory (prefix-match collision against compound `C…:thread_ts` entries).
- `~/.hermes/hermes-agent/run_agent.py` — broaden `_try_refresh_anthropic_client_credentials` skip-condition from Azure-only to all third-party Anthropic-compatible endpoints. Source: `patches/run-agent-third-party-endpoint-token-refresh.patch`. Re-apply: `cd ~/.hermes/hermes-agent && git apply ~/SourceRoot/hermes-agent/patches/run-agent-third-party-endpoint-token-refresh.patch`. Without this, every `messages.create()` call invokes `resolve_anthropic_token()` which prefers `~/.claude/.credentials.json` OAuth token over `ANTHROPIC_API_KEY`, swaps the client's IU key for the OAuth token, and the next request 401s on the IU endpoint with "Authorization parsing failed" / "invalid x-api-key". v0.12 only excluded `azure.com` from the refresh; our IU endpoint (`unified-endpoint-main.app.iu-it.org/anthropic`) needs the same exclusion. The patch swaps the literal `azure.com` check for `_is_third_party_anthropic_endpoint(base_url)`, which already handles all non-`anthropic.com` hosts.

## Setup

```bash
make setup        # idempotent — symlinks, helper plist, cron, CC skills
make status       # verify everything is in place
```

Prerequisites:
1. `hermes` CLI installed (see README.md §2)
2. `~/SourceRoot/dotfiles` cloned (helper plist template lives there)
3. 1Password CLI authenticated as `tkrumm`

## Editing Rules

**Adding a Hermes skill:** create `skills/{name}/SKILL.md`, add `{name}` to
`HERMES_SKILLS` in the Makefile, run `make setup`.

**Adding a CC slash command for Hermes:** create `cc-skills/{name}/SKILL.md`,
add `{name}` to `CC_SKILLS` in the Makefile, run `make setup`.

**Patches:** when fixing bugs in upstream Hermes, save the diff under `patches/`
and document the re-apply command in this file.
