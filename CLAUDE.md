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
| `skills/{name}/` | `~/.hermes/skills/{name}/` | symlink per skill (argo-api, infrastructure, tasks, capture, schedule, work, weather, slack, garmin-health, strength) |
| `USER.md` | `~/.hermes/memories/USER.md` | copied — Hermes writes to it |

**Claude Code per-repo skills** (committed at `.claude/skills/`, not symlinked — auto-loaded by Claude Code when started inside this repo):
- `/hermes-validate` — slash command to test Hermes routing + fix SOUL.md / SKILL.md
- `/hermes-update` — slash command to pull upstream Hermes, re-apply local patches, restart the gateway

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

`skills/argo-api/SKILL.md` endpoint tables are regenerated from `https://argo.jkrumm.com/api/openapi/json` by the homelab `/docs` skill. The argo API tags relevant to Hermes — **Garmin Health, Strength, Productivity, Infrastructure, External Data, System, M365, Atlassian, GitLab** — are exposed at `GET /` for agent self-orientation. Domain skills (infrastructure, tasks, capture, schedule, work, weather, slack, garmin-health, strength) are updated in the same pass if their endpoints changed.

**Work surface (IU) — `work` skill.** Argo wraps four upstream systems behind a single curated read-only REST surface, all consumed by the Hermes `work` skill:

- **M365** (Outlook calendar, Teams chats + channels, curated `/m365/important` alerts feed, `/m365/team` roster + repo registry — the cross-system identity hub).
- **Atlassian / Jira** (`/atlassian/jira/{me, my-issues, current-sprint, sprints, backlog, search, issue/:key, users/search}`) — full ticket + sprint + backlog access plus JQL escape hatch.
- **Atlassian / Confluence** (`/atlassian/confluence/{spaces, search, pages/:id, pages/:id/children, recently-updated}`) — CQL search + page body in rendered HTML.
- **GitLab** (`/gitlab/{me, users/search, users/by-username, merge-requests, projects/:id/merge-requests/:iid + approvals + discussions, projects/:id/commits + releases, events/recent}`) — cross-project MR view, per-MR approval state + threaded discussions, per-project commits + releases. MRs auto-extract `jiraKeys` for direct Jira pivots.

The skill is **personal-orientation only** — read-only across every system, never writes, never speaks for or pings teammates. Team-facing assistance (Greenkeeper / standup automation) is a separate Hermes Agent (not yet deployed). The skill's SKILL.md owns: identity model (`/m365/team` `members[]` + `repos[]`), MR↔Jira link via `jiraKeys`, structured "is MR blocked" check (5 conditions), and the recurring-question playbook ("what's on my plate", "what needs my review", "is X blocked", "Confluence context for Y").

**What's wired into briefings vs ad-hoc-only.** The morning briefing surfaces exactly three work signals: (1) today's Outlook calendar (merged with personal calendar under `:office:` prefix in the schedule section), (2) Jira sprint commitments — `:briefcase: Work — Sprint & Reviews`, (3) GitLab MRs needing action (ready-to-merge + needs-review, also in the Work section). The evening report keeps only tomorrow's merged calendar (wind-down tone forbids pressure-piling). **Everything else on the work surface is ad-hoc-only** — `/m365/important` (curated Teams alerts), `/m365/chats` + `/teams/.../channels/.../messages`, `/atlassian/confluence/*`, `/gitlab/events/recent`, `/gitlab/.../commits + releases` — never wired into briefings, never into the watchdog (watchdog is personal apps + infra alerts only). Errors: `503 M365 not authenticated …` → tell the user to run `bun m365:auth:prod` from `~/SourceRoot/argo`. `503` on `/gitlab/*` or `/atlassian/*` → corresponding PAT expired.

**Split: garmin-health vs strength.** Garmin Health owns passive measurements (`/daily-metrics`, `/recovery`, `/training-load`, `/fitness-direction`, `/activities`, `/weight-log`, `/user-profile`). Strength owns active lifting (`/workouts`, `/workout-sets`, `/exercises`) plus the 13-endpoint `/workouts/summary/*` analytics suite (e1RM, INOL, ACWR per-exercise, MEV/MAV/MRV landmarks, deload-signal, readiness). The cross-skill bridge is `/workouts/summary/readiness` — it joins Garmin recovery + strength fatigue debt and lives in `strength`. Note `weight-log` + `user-profile` are tagged Garmin Health in the live OpenAPI even though they're physically distinct from daily metrics; respect that grouping in cross-references.

**API secret:** `op://common/api/SECRET` (account `tkrumm`) — wired in `.env.tpl`.

## Local Modifications to Upstream

Re-apply after `hermes update`:

- `~/.hermes/hermes-agent/tools/tts_tool.py` — thin client over `localai-helper:8001/v1/tts/synthesize`; replaces 1600-line multi-provider original. Source: `patches/tts_tool.py`. Re-apply: `cp ~/SourceRoot/hermes-agent/patches/tts_tool.py ~/.hermes/hermes-agent/tools/tts_tool.py`
- `~/.hermes/hermes-agent/tools/tts_fast_tool.py` — NEW tool (additive, auto-discovered by `registry.discover_builtin_tools`). Thin client over `localai-helper:8001/v1/tts/synthesize/fast` (Supertonic-3, English-only, polish on). Distinct tool from `text_to_speech` so the LLM can pick speed vs. quality per turn. Source: `patches/tts_fast_tool.py`. Re-apply: `cp ~/SourceRoot/hermes-agent/patches/tts_fast_tool.py ~/.hermes/hermes-agent/tools/tts_fast_tool.py`
- `~/.hermes/hermes-agent/gateway/platforms/slack.py` — three changes, all in `patches/slack-cannot-reply-to-message.patch`. Re-apply: `cd ~/.hermes/hermes-agent && git apply ~/SourceRoot/hermes-agent/patches/slack-cannot-reply-to-message.patch`. **Patch applies cleanly to v0.12** — all context lines unchanged in upstream.
  - `format_message()` pre-steps: normalize `*` list markers to `-`, strip backticks from inline code containing emoji shortcodes. **Not upstream.**
  - `_resolve_thread_ts` synthetic-thread guard: detect synthetic `thread_id == reply_to` (no real `thread_ts`) → return `None`. **Not upstream.** v0.12 added a similar guard but gated on `reply_in_thread: false` only — our config uses `reply_in_thread: true`, so v0.12's guard is a no-op for us.
  - `send()` retry: on `cannot_reply_to_message`, drop `thread_ts` and retry chunk as plain channel message. **Not upstream.**
- `~/.hermes/hermes-agent/cron/scheduler.py` — skip `resolve_channel_name` for raw Slack channel IDs in `_resolve_single_delivery_target`. Source: `patches/scheduler-skip-resolver-for-slack-ids.patch`. Re-apply: `cd ~/.hermes/hermes-agent && git apply ~/SourceRoot/hermes-agent/patches/scheduler-skip-resolver-for-slack-ids.patch`. Without this, `--deliver slack:<C…ID>` fails with `channel_not_found` for any channel that has exactly one thread session in the directory (prefix-match collision against compound `C…:thread_ts` entries).
- `~/.hermes/hermes-agent/run_agent.py` — broaden `_try_refresh_anthropic_client_credentials` skip-condition from Azure-only to all third-party Anthropic-compatible endpoints. Source: `patches/run-agent-third-party-endpoint-token-refresh.patch`. Re-apply: `cd ~/.hermes/hermes-agent && git apply ~/SourceRoot/hermes-agent/patches/run-agent-third-party-endpoint-token-refresh.patch`. Without this, every `messages.create()` call invokes `resolve_anthropic_token()` which prefers `~/.claude/.credentials.json` OAuth token over `ANTHROPIC_API_KEY`, swaps the client's IU key for the OAuth token, and the next request 401s on the IU endpoint with "Authorization parsing failed" / "invalid x-api-key". v0.12 only excluded `azure.com` from the refresh; our IU endpoint (`unified-endpoint-main.app.iu-it.org/anthropic`) needs the same exclusion. The patch swaps the literal `azure.com` check for `_is_third_party_anthropic_endpoint(base_url)`, which already handles all non-`anthropic.com` hosts.
- `~/.hermes/hermes-agent/toolsets.py` — expose `text_to_speech_fast` as part of the `tts` toolset. Source: `patches/toolsets-expose-text-to-speech-fast.patch`. Re-apply: `cd ~/.hermes/hermes-agent && git apply ~/SourceRoot/hermes-agent/patches/toolsets-expose-text-to-speech-fast.patch`. Without this, the new tool is registered in `tools/registry.py` but the toolset definition in `toolsets.py` only lists `text_to_speech`, so `model_tools.get_tool_definitions` filters out `text_to_speech_fast` before sending the LLM-facing schema list. The LLM literally never saw the second tool existed and could not pick it even with explicit "fast TTS" triggers in the user message.
- `~/.hermes/hermes-agent/tools/cronjob_tools.py` — extend `_scan_cron_prompt` with an argo allowlist so the assembled-prompt scanner (added in v0.13.0, May 7 2026) stops flagging legitimate `curl -H "Authorization: Bearer $HOMELAB_API_KEY" "https://argo.jkrumm.com/..."` shapes carried by every bundled argo skill. Source: `patches/cronjob-tools-allowlist-argo-bearer.patch`. Re-apply: `cd ~/.hermes/hermes-agent && git apply ~/SourceRoot/hermes-agent/patches/cronjob-tools-allowlist-argo-bearer.patch`. Without this, **every** cron with skills loaded (morning briefing, evening report, anything calling argo) fails with `Blocked: prompt matches threat pattern 'exfil_curl_auth_header'`. The patch sanitizes argo-only markdown bash fences plus any single-line argo curl before the exfil scan runs, but leaves any fence containing a non-argo host intact so real exfil to a different host still triggers. Co-located evil curls in the same fence as argo curls still get caught because the fence-sanitizer skips fences with a foreign host alongside argo.
- `~/.hermes/hermes-agent/agent/auxiliary_client.py` — respect `api_mode: anthropic_messages` in the `provider == "custom" + explicit_base_url` branch. Source: `patches/auxiliary-client-anthropic-mode-respect.patch`. Re-apply: `cd ~/.hermes/hermes-agent && git apply ~/SourceRoot/hermes-agent/patches/auxiliary-client-anthropic-mode-respect.patch`. Without this, auxiliary tasks (`title_generation`, `compression`, `approval`) configured with `base_url: ${ANTHROPIC_BASE_URL}` get their `/anthropic` suffix unconditionally rewritten to `/v1` by `_to_openai_base_url`, then `_maybe_wrap_anthropic` can no longer detect the Anthropic Messages surface, and the OpenAI client hits `/v1/chat/completions` against an `/anthropic`-only gateway → 404 "Endpoint not found" on every auxiliary call. The IU unified endpoint at `unified-endpoint-main.app.iu-it.org/anthropic` serves Anthropic Messages but **not** OpenAI chat completions. With the patch, `api_mode: anthropic_messages` skips the URL rewrite so `_maybe_wrap_anthropic` correctly wraps the client in `AnthropicAuxiliaryClient`.

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
`HERMES_SKILLS` in the Makefile, run `make setup`. If the skill should appear in scheduled briefings, also wire it into the relevant cron prompt (`cron/*.prompt.txt`) and re-sync `cron/jobs.json`.

**Adding a CC slash command for Hermes:** create `.claude/skills/{name}/SKILL.md`. Auto-loaded by Claude Code when started inside this repo — no symlink, no Makefile change needed.

**Patches:** when fixing bugs in upstream Hermes, save the diff under `patches/`
and document the re-apply command in this file.
