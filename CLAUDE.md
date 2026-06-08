# hermes-agent — Hermes Agent Instructions

## What This Repo Is

VCS source of truth for Johannes's Hermes Agent setup. Mac Mini-only deployment.
Everything in this repo is symlinked into `~/.hermes/` — edit at either end,
git always sees the change here.

Audio (TTS + STT) is served by the **`audio-proxy`** repo (`~/SourceRoot/audio-proxy`),
an OpenAI-compatible LaunchAgent on `127.0.0.1:7716` installed by dotfiles
`make setup`. Hermes only points its native `openai` TTS/STT providers at it in
`config.yaml` — this repo no longer installs or patches any audio service, and
`make setup` here has no `dotfiles` dependency. TTS = Gemini 3.1 Flash (voice
"Charon"), STT = `gpt-4o-transcribe`, both EU-resident via IU.

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
- `scripts/watchdog-poll.py` — polls UptimeKuma, Docker (homelab + vps), GitHub, Slack `#alerts`; reconciles against `~/.hermes/watchdog.db`. Emits `NEW=`, `REMINDERS=`, `RESOLVED=` blocks for the watchdog cron prompt. **Grouped sources** (`slack_alert`, `slack_update`, `hermes_log`) are append-only — recorded via `upsert_grouped`, never disappearance-resolved — so `sweep_stale_grouped()` silently auto-resolves any open grouped event idle for >7d (`GROUPED_TTL_DAYS`), capping DB + briefing-list growth. `hermes_log` signatures skip the optional `[thread]` token after the level and cut the message at ` | ` so a recurring error (e.g. the cron "API call failed" flood) collapses to one signature instead of one per poll.
- `scripts/watchdog-slack.py` — `no_agent` cron entry (every 30 min); thin wrapper that runs `watchdog-poll.py`'s `main(["--slack-body"])` and, on a clean run, pings `$UPTIME_PUSH_WATCHDOG` (self-health heartbeat — a crash/hang trips the "Watchdog last successful run" UK monitor). Ping is a no-op until the secret + UK push monitor exist.
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

Re-apply after `hermes update`: **eight `.patch` files** (each applied with `git apply --3way`; `/hermes-update` carries the loop). All eight are regenerated against the current upstream baseline (**v0.15.1**) so they re-apply cleanly on minor upstream bumps; only a structural rewrite of a touched function needs a hand-rewrite.

> **Retired patch — `auxiliary-client-gpt5-max-completion-tokens` (dropped at v0.15.1).** It forced `max_completion_tokens` for `gpt-5*`/`gpt-4o`/`o-series` models by name in `_build_call_kwargs`. v0.15.1 rewrote that function to **omit `max_tokens` entirely** for non-Anthropic custom endpoints (it only sets it for Anthropic-compat endpoints, where it's mandatory) — so the patch's target block no longer exists, and its defensive goal (never send `max_tokens` to a gpt-5 aux on the IU endpoint → HTTP 503) is now achieved by upstream's omit-by-default behavior. The direct-OpenAI `max_completion_tokens` case is handled by upstream's separate `auxiliary_max_tokens_param` helper. The current config (DeepSeek-V4-Flash auxiliaries, `chat_completions`) never hit this path regardless. Patch file deleted from `patches/`.

- **STT uses the stock upstream tool** — no patch. `tools/transcription_tools.py` (native `openai` STT) is pointed at audio-proxy (`:7716`) purely via `config.yaml` (`stt.openai`). The old localai-helper client patches (`tts_fast_tool.py`) and the `toolsets-expose-text-to-speech-fast` patch were removed when Hermes moved to Gemini Charon via audio-proxy.
- `~/.hermes/hermes-agent/tools/tts_tool.py` — one small local modification on top of the stock native tool: name the saved audio file from audio-proxy's `X-Audio-Title` response header (a short title generated by audio-proxy's `DeepSeek-V4-Pro` prep step) instead of the upstream `tts_<timestamp>.mp3`, so the Slack attachment shows a real name. Source: `patches/tts-tool-audio-title.patch`. Re-apply: `cd ~/.hermes/hermes-agent && git apply ~/SourceRoot/hermes-agent/patches/tts-tool-audio-title.patch`. The patch (a) switches `_generate_openai_tts` to `with_raw_response` so it can read the header alongside the binary body and returns the decoded title, and (b) renames the output file to a sanitized title via a new `_rename_with_title` helper. TTS provider/voice/base_url stay config-driven (`tts.openai` → `:7716`). Without it, voice memos still work but land as `tts_<timestamp>.mp3` in Slack. The title itself is produced in the **audio-proxy** repo (`src/gemini-tts.ts`, `X-Audio-Title` header).
- `~/.hermes/hermes-agent/gateway/platforms/slack.py` — three changes, all in `patches/slack-cannot-reply-to-message.patch`. Re-apply: `cd ~/.hermes/hermes-agent && git apply ~/SourceRoot/hermes-agent/patches/slack-cannot-reply-to-message.patch`. **Patch applies cleanly to v0.12** — all context lines unchanged in upstream.
  - `format_message()` pre-steps: normalize `*` list markers to `-`, strip backticks from inline code containing emoji shortcodes. **Not upstream.**
  - `_resolve_thread_ts` synthetic-thread guard: detect synthetic `thread_id == reply_to` (no real `thread_ts`) → return `None`. **Not upstream.** v0.12 added a similar guard but gated on `reply_in_thread: false` only — our config uses `reply_in_thread: true`, so v0.12's guard is a no-op for us.
  - `send()` retry: on `cannot_reply_to_message`, drop `thread_ts` and retry chunk as plain channel message. **Not upstream.**
- `~/.hermes/hermes-agent/gateway/platforms/base.py` — pass the text reply's anchor (`_reply_anchor_for_event(event)`) to the media senders (`send_voice`/`send_video`/`send_document`) in the response media-dispatch loops, so attached files thread identically to the text reply. Source: `patches/slack-media-inline-reply-anchor.patch`. Re-apply: `cd ~/.hermes/hermes-agent && git apply ~/SourceRoot/hermes-agent/patches/slack-media-inline-reply-anchor.patch`. Without this, the media senders are called with `reply_to=None`, so Slack's `reply_in_thread: false` synthetic-thread guard (which only nulls the message's own ts when it equals `reply_to`) can't fire — TTS audio (and any attachment) lands in a thread while the text reply is inline. Real threads still thread correctly (anchor ≠ thread parent).
- `~/.hermes/hermes-agent/cron/scheduler.py` — skip `resolve_channel_name` for raw Slack channel IDs in `_resolve_single_delivery_target`. Source: `patches/scheduler-skip-resolver-for-slack-ids.patch`. Re-apply: `cd ~/.hermes/hermes-agent && git apply ~/SourceRoot/hermes-agent/patches/scheduler-skip-resolver-for-slack-ids.patch`. Without this, `--deliver slack:<C…ID>` fails with `channel_not_found` for any channel that has exactly one thread session in the directory (prefix-match collision against compound `C…:thread_ts` entries).
- `~/.hermes/hermes-agent/run_agent.py` — broaden `_try_refresh_anthropic_client_credentials` skip-condition from Azure-only to all third-party Anthropic-compatible endpoints. Source: `patches/run-agent-third-party-endpoint-token-refresh.patch`. Re-apply: `cd ~/.hermes/hermes-agent && git apply ~/SourceRoot/hermes-agent/patches/run-agent-third-party-endpoint-token-refresh.patch`. Without this, every `messages.create()` call invokes `resolve_anthropic_token()` which prefers `~/.claude/.credentials.json` OAuth token over `ANTHROPIC_API_KEY`, swaps the client's IU key for the OAuth token, and the next request 401s on the IU endpoint with "Authorization parsing failed" / "invalid x-api-key". v0.12 only excluded `azure.com` from the refresh; our IU endpoint (`unified-endpoint-main.app.iu-it.org/anthropic`) needs the same exclusion. The patch swaps the literal `azure.com` check for `_is_third_party_anthropic_endpoint(base_url)`, which already handles all non-`anthropic.com` hosts.
- `~/.hermes/hermes-agent/tools/tirith_security.py` — early-return `allow` in `check_command_security` when the command is an argo-only pipeline (every URL on `argo.jkrumm.com`, every pipeline-stage program in a safe text-tool set, no shell escape hatches). Source: `patches/tirith-allowlist-argo-pipes.patch`. Re-apply: `cd ~/.hermes/hermes-agent && git apply ~/SourceRoot/hermes-agent/patches/tirith-allowlist-argo-pipes.patch`. Without this, tirith's `[HIGH] Pipe to interpreter` rule fires on **every** `curl https://argo.jkrumm.com/... | python3 ...` (and `| jq` to a lesser degree) the LLM produces — Hermes constantly stops at a Slack approval gate ("Command Approval Required") for completely safe argo calls that pipe JSON to python3 for formatting. The threat tirith protects against ("Downloaded content will be executed without inspection") doesn't apply: argo is bearer-authenticated and serves JSON parsed as data, not executable code. Patch mirrors the cron-scanner allowlist precedent — only argo URLs + a small safe-program set (curl, jq, python3, head, tail, tee, tr, cat, wc, cut, grep, sort, awk, sed, uniq, xargs) are accepted, and any redirect, `$(...)`, backtick, `;`, `&&`, `||`, `&`, `(`, `>` token defers to tirith. Sanity-tested against 19 representative shapes (8 allow, 11 defer including mixed-host, eval, subshell, `sh -c`, redirect).
- `~/.hermes/hermes-agent/tools/cronjob_tools.py` — extend the shared `_strip_cron_safe_constructs` helper with an argo allowlist so the cron-prompt scanners stop flagging legitimate `curl -H "Authorization: Bearer $HOMELAB_API_KEY" "https://argo.jkrumm.com/..."` shapes carried by every bundled argo skill. Source: `patches/cronjob-tools-allowlist-argo-bearer.patch`. Re-apply: `cd ~/.hermes/hermes-agent && git apply ~/SourceRoot/hermes-agent/patches/cronjob-tools-allowlist-argo-bearer.patch`. **v0.15.1 refactor:** upstream split the cron scanner into `_scan_cron_prompt` (raw user prompt — still checks `_CRON_EXFIL_COMMAND_PATTERNS`, incl. `exfil_curl_auth_header`) and `_scan_cron_skill_assembled` (skills-loaded — now uses a looser pattern set that already *drops* the curl/exfil shapes), with the GitHub-auth exemption hoisted into a shared `_strip_cron_safe_constructs` helper both call. The argo allowlist now lives in that **shared helper** (was inline in `_scan_cron_prompt`), so it covers both paths: the still-live `exfil_curl_auth_header` block on the raw-prompt path, plus harmless redundancy on the assembled path. Without it, any cron whose raw prompt carries an argo bearer curl fails with `Blocked: prompt matches threat pattern 'exfil_curl_auth_header'`. The patch sanitizes argo-only markdown bash fences plus any single-line argo curl before the exfil scan runs, but leaves any fence containing a non-argo host intact so real exfil to a different host still triggers. Co-located evil curls in the same fence as argo curls still get caught because the fence-sanitizer skips fences with a foreign host alongside argo. (Behaviorally tested post-update: argo single-line + fence sanitized, evil single-line + mixed fence preserved, GitHub fallback intact.)
- `~/.hermes/hermes-agent/agent/auxiliary_client.py` — respect `api_mode: anthropic_messages` in the `provider == "custom" + explicit_base_url` branch of `resolve_provider_client`: skip the `/anthropic`→`/v1` rewrite that `_to_openai_base_url` would otherwise apply, so `custom_base` keeps the `/anthropic` suffix. Source: `patches/auxiliary-client-anthropic-mode-respect.patch`. Re-apply: `cd ~/.hermes/hermes-agent && git apply ~/SourceRoot/hermes-agent/patches/auxiliary-client-anthropic-mode-respect.patch`. **v0.15.1 nuance:** upstream's `_maybe_wrap_anthropic` now detects the Anthropic surface via `api_mode == "anthropic_messages"` *explicitly* (decoupled from the URL suffix), so detection itself no longer breaks — **but** the patch is still load-bearing because `build_anthropic_client(api_key, base_url)` is handed `custom_base`; if that got rewritten to `/v1` the Anthropic client targets `/v1/messages` on the IU `/anthropic`-only gateway → 404 "Endpoint not found". The patch keeps the correct `/anthropic` base. **Currently defensive/dormant:** the live config routes the brain *and* auxiliaries through `${OPENAI_BASE_URL}` with `api_mode: chat_completions` (DeepSeek-V4-Pro / -Flash), so the `anthropic_messages` branch isn't exercised today — the patch only matters if a model is re-routed through the IU `/anthropic` endpoint. Kept applied (clean, zero cost on the `chat_completions` path).

## Setup

```bash
make setup        # idempotent — symlinks, cron, CC skills
make status       # verify everything is in place (incl. audio-proxy :7716 health)
```

Prerequisites:
1. `hermes` CLI installed (see README.md §2)
2. `audio-proxy` running on `:7716` (from `~/SourceRoot/audio-proxy`, installed by dotfiles `make setup`) — for TTS/STT
3. 1Password CLI authenticated as `tkrumm`

## Editing Rules

**Adding a Hermes skill:** create `skills/{name}/SKILL.md`, add `{name}` to
`HERMES_SKILLS` in the Makefile, run `make setup`. If the skill should appear in scheduled briefings, also wire it into the relevant cron prompt (`cron/*.prompt.txt`) and re-sync `cron/jobs.json`.

**Adding a CC slash command for Hermes:** create `.claude/skills/{name}/SKILL.md`. Auto-loaded by Claude Code when started inside this repo — no symlink, no Makefile change needed.

**Patches:** when fixing bugs in upstream Hermes, save the diff under `patches/`
and document the re-apply command in this file.
