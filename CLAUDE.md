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
| `skills/{name}/` | `~/.hermes/skills/{name}/` | symlink per skill (homelab-api, infrastructure, tasks, capture, schedule, weather, slack) |
| `USER.md` | `~/.hermes/memories/USER.md` | copied — Hermes writes to it |
| `cc-skills/hermes-validate/` | `~/SourceRoot/.claude/skills/hermes-validate/` | symlink — Claude Code slash command for validating Hermes routing |
| `cc-skills/hermes-update/` | `~/SourceRoot/.claude/skills/hermes-update/` | symlink — Claude Code slash command for updating the upstream Hermes repo |

**Host-level scripts (called by macOS `crontab`, not symlinked):**
- `scripts/hermes-liveness.sh` — every 5 min, checks gateway state + Slack connection, pings `$UPTIME_PUSH_HERMES` on success.
- `scripts/hermes-backup.sh` — daily 03:00, rsyncs `~/.hermes/` → `homelab:/mnt/hdd/backups/hermes/`, pings `$UPTIME_PUSH_BACKUP` on success.

**Hermes cron pre-run scripts (executed by `hermes-agent` before each cron run, *not* by macOS crontab):**
- `scripts/briefing-context.py` — reads `briefing-state.json` and emits `BRIEFING_CITY` + `BRIEFING_SUPPRESSED` for the morning briefing prompt. Output is appended as `## Script Output` block.
- `scripts/briefing-state.json` — *gitignored* runtime config (city + vacation flag). Edit locally; never commits. Seeded from `briefing-state.example.json` on first `make setup`.
- `skills/capture/state.json` — *gitignored* runtime cache for the capture skill (GitHub repos + TickTick projects). Refreshed on miss via `gh repo list jkrumm` and `/ticktick/projects`. Seeded empty from `state.example.json` on first `make setup`.

## Homelab API Integration

`skills/homelab-api/SKILL.md` endpoint tables are regenerated from `https://api.jkrumm.com/docs/json` by the homelab `/docs` skill. Domain skills (infrastructure, tasks, capture, schedule, weather, slack) are updated in the same pass if their endpoints changed.

**API secret:** `op://common/api/SECRET` (account `tkrumm`) — wired in `.env.tpl`.

## Local Modifications to Upstream

Re-apply after `hermes update`:

- `~/.hermes/hermes-agent/tools/tts_tool.py` — thin client over `localai-helper:8001/v1/tts/synthesize`; replaces 1600-line multi-provider original. Source: `patches/tts_tool.py`. Re-apply: `cp ~/SourceRoot/hermes-agent/patches/tts_tool.py ~/.hermes/hermes-agent/tools/tts_tool.py`
- `~/.hermes/hermes-agent/gateway/platforms/slack.py` — `format_message()` pre-steps: normalize `*` list markers to `-`, strip backticks from inline code containing emoji shortcodes
- `~/.hermes/hermes-agent/gateway/platforms/slack.py` — `_resolve_thread_ts` synthetic-thread guard + defensive retry-without-thread on `cannot_reply_to_message` in `send()`. Mirrors upstream commits `4b5a88d71` and `41d9d0807` semantics. Source: `patches/slack-cannot-reply-to-message.patch`. Re-apply: `cd ~/.hermes/hermes-agent && git apply ~/SourceRoot/hermes-agent/patches/slack-cannot-reply-to-message.patch`. **Remove once Hermes v0.12+ ships** — both fixes will be upstream.
- `~/.hermes/hermes-agent/gateway/config.py` — bridge `reply_in_thread`, `reply_broadcast`, `reply_to_mode` from `slack:` YAML section into platform `extra` dict (upstream still only bridges `require_mention`, `allow_bots`, `free_response_channels` as of 0.11.0). Note: `reply_to_mode` is consumed by telegram/discord only, not Slack — dropped from `slack:` section in `config.yaml`.
- `~/.hermes/hermes-agent/cron/scheduler.py` — skip `resolve_channel_name` for raw Slack channel IDs in `_resolve_single_delivery_target`. Source: `patches/scheduler-skip-resolver-for-slack-ids.patch`. Re-apply: `cd ~/.hermes/hermes-agent && git apply ~/SourceRoot/hermes-agent/patches/scheduler-skip-resolver-for-slack-ids.patch`. Without this, `--deliver slack:<C…ID>` fails with `channel_not_found` for any channel that has exactly one thread session in the directory (prefix-match collision against compound `C…:thread_ts` entries).

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
