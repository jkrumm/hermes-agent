# hermes-agent — Hermes Agent Instructions

## What This Repo Is

VCS source of truth for Johannes's Hermes Agent setup. Mac Mini-only deployment.
Everything in this repo is symlinked into `~/.hermes/` — edit at either end,
git always sees the change here.

Audio (TTS + STT) is served by the **`audio-gateway`** service (`~/SourceRoot/audio-gateway`),
an OpenAI-compatible VPS Docker container at `https://audio-gateway.jkrumm.com/v1` reached
over the tailnet (Cloudflare grey-cloud DNS → VPS over Tailscale). Hermes only points its
native `openai` TTS/STT providers at it in `config.yaml` — this repo no longer installs or
patches any audio service, and `make setup` here has no `dotfiles` dependency. TTS = Gemini
3.1 Flash (voice "Charon"), STT = `gpt-4o-transcribe`, both EU-resident via IU. There is no
local audio service to start; Hermes depends on the remote gateway being reachable over the
tailnet.

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
| `skills/{name}/` | `~/.hermes/skills/{name}/` | symlink per skill — actual dirs are `capture`, `argo-api`, `work`, `karakeep`, `obsidian`, `reading`, `research-gateway` (the former infrastructure/schedule/slack/tasks/weather/garmin-health/strength skills were consolidated into `argo-api/references/*.md` — now incl. `walking-pad.md`; they are no longer separate dirs and were dropped from `HERMES_SKILLS`) |
| `USER.md` | `~/.hermes/memories/USER.md` | copied — Hermes writes to it |

> **Skill trust (v0.16.0+).** Skills are symlinked into `~/.hermes/skills/`, but v0.16.0's skill-security check resolves each skill's *realpath* and warns — and may later **block** — when it lands outside a trusted dir (our symlink targets do). `config.yaml` therefore sets `skills.external_dirs: [~/SourceRoot/hermes-agent/skills]` so the resolved realpath is trusted. The symlink and the external entry resolve to the same path, which `skills_tool` dedups (by realpath on load, by name on listing) — no duplicate-skill collisions. If a future update reintroduces the "skill file is outside the trusted skills directory" warning, confirm this key is still populated.

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

## Secrets — native `secrets.command` over the headless cache (v0.19.0+)

There is **no plaintext `~/.hermes/.env`** and **no launch wrapper**. Hermes resolves its
own secrets at startup through v0.19's `SecretSource` interface, configured in
`config.yaml` under `secrets.command`:

```yaml
secrets:
  command:
    enabled: true
    command: "$HOME/.local/bin/secrets-run export --env-file=$HOME/.hermes/.env.tpl | sed 's/^export //'"
    helper_timeout_seconds: 15
    override_existing: true
```

`secrets-run` is the dotfiles shim that decrypts the age-encrypted offline cache (see
global CLAUDE.md → "Headless secrets"). `.env.tpl` stays the single list of
`KEY=op://vault/item/field` refs — it is now consumed by the `command` source instead of
by an `op run` wrapper. The `sed` exists because `secrets-run export` emits
`export K='V'` while the bulk parser wants bare `K=V` (it strips one quote layer itself).
Measured 0.29s for 26 refs, well inside the budget (the source's default is a tight 3s).

**Why not `secrets.onepassword`** (also shipped in v0.19): it authenticates either via an
interactive `op` session — which **hangs** on this headless mini's biometric prompt, the
exact problem the cache solves — or via a standing `OP_SERVICE_ACCOUNT_TOKEN`. That token
is a *live* credential with continuous read access to its scoped vaults sitting on an
always-on box; the sealed cache is strictly stronger, because its contents are the
explicit `dotfiles-private/headless.refs` allowlist (T0/T1 only, `op://Private/*` refused
at seed time) and it cannot reach anything that wasn't deliberately sealed into it.

**What this replaced:** `scripts/gateway-cache-launch.sh`, a wrapper that `export`ed the
cache into the environment and `exec`'d the gateway, wired in as the launchd
`ProgramArguments`. Its own header documented the fragility that killed it — `hermes
gateway install` regenerates the plist and drops the wrapper. The plist is now stock
(`venv/bin/python -m hermes_cli.main gateway run --replace`), so a reinstall is a no-op.
Bonus: secrets now resolve for **every** hermes invocation (gateway, CLI, cron), not just
the launchd-started gateway — previously a manual `hermes …` on the mini ran with
*no* credentials at all, which made ad-hoc dev/debug/monitoring work awkward.

Trade-off accepted: the wrapper failed **closed** (non-zero exit → gateway never started
credential-less). The `command` source instead degrades to "no secrets applied" plus a
warning, so a broken cache yields a gateway that starts and then fails to connect. Confirm
`Command helper: applied 26 secrets` in `hermes gateway status` after any secrets change.

> **launchd now works.** Earlier notes claimed `launchctl` couldn't bootstrap
> `ai.hermes.gateway` (`Bootstrap failed: 5: I/O error`) and that the gateway fell back to
> a bare `run --replace`. As of v0.19.0 `hermes gateway status` reports it genuinely
> **supervised by launchd**, so auto-start at login and auto-restart on crash are live.
> `hermes gateway install` still prints `Bootstrap failed: 5` while repairing the
> definition — that message is noise; check `gateway status` for the real state.

## Gateway HTTP Exposure (argo dashboard chat)

The gateway runs an OpenAI-compatible HTTP API alongside Slack, so the **argo VPS
dashboard chat** can talk to Hermes. Controlled by four env vars (framework keys in
`hermes_cli/config.py`), resolved at startup from `.env.tpl` via `secrets.command`
(see "Secrets" above) so a rebuild never silently drops the exposure:

- `API_SERVER_ENABLED=true`, `API_SERVER_PORT=8642` — literals.
- `API_SERVER_HOST` — the Mac Mini's Tailscale IP, **tailnet-only bind** (no LAN
  listener). Stored at `op://hermes/gateway/host` (never a literal in git — security rule).
- `API_SERVER_KEY` — bearer that auth-gates **every** request (even loopback).
  Canonical at `op://hermes/gateway/api-server-key`.

**Shared secret (single source of truth):** the gateway's `API_SERVER_KEY` **must
equal** argo's `HERMES_API_KEY`. Canonical value = `op://hermes/gateway/api-server-key`,
mirrored to `op://vps/argo/HERMES_API_KEY`. Rotate by editing both op items to the same
value, then `ssh vps "cd ~/vps && ENV=prod make argo-env && ENV=prod make argo-up"` (argo
re-materializes its `.env` and recreates argo-api). A key mismatch surfaces as **401** on
the dashboard chat; connection-refused means the gateway isn't bound to the tailnet IP.

**Network path:** argo on the VPS holds `HERMES_BASE_URL=http://<mac-tailnet-ip>:8642/v1`
(`apps/argo/compose.yml` + `.env.tpl`). A Tailscale ACL grants `tag:vps → tag:mac` on
`tcp:8642`. The exposure needs **no gateway restart** to reconcile a key — the gateway is
static; only the argo side redeploys.

**Verify (from the VPS, reading URL+key from `apps/argo/.env`):** `curl .../health`
(no auth) → 200; `curl -H "Authorization: Bearer $KEY" .../v1/models` → 200; a real
`POST .../v1/chat/completions` returns a completion. Local bind: `lsof -nP -iTCP:8642
-sTCP:LISTEN` must show the tailnet IP, not `127.0.0.1`.

## Homelab API Integration

`skills/argo-api/SKILL.md` endpoint tables are regenerated from `https://argo.jkrumm.com/api/openapi/json` by the homelab `/docs` skill. The live spec carries **14 tags**, split three ways in the skill's taxonomy: **personal** (`argo-api`) — Garmin Health, Strength, **WalkingPad**, Productivity, Infrastructure, External Data, **Reading**, **Usage Tracking**, System; **work** (`work` skill) — M365, Atlassian, GitLab; and **not-agent-facing** — **Hermes Chat** (`/hermes/*`, the argo→Hermes path) and **AI Gateway** (`/ai/v1/*`, the model+audio proxy Hermes bypasses by hitting its brain + audio-gateway directly). Domain skills (infrastructure, tasks, capture, schedule, work, weather, slack, garmin-health, strength, walking-pad) are updated in the same pass if their endpoints changed. Reading (`/reading/*`) is owned by the standalone `reading` skill; the `research-gateway` skill calls the research-gateway service, not Argo.

**Work surface (IU) — `work` skill.** Argo wraps four upstream systems behind a single curated REST surface (read-only everywhere **except Jira writes**), all consumed by the Hermes `work` skill:

- **M365** (Outlook calendar, Teams chats + channels, curated `/m365/important` alerts feed, `/m365/team` roster + repo registry — the cross-system identity hub).
- **Atlassian / Jira** (`/atlassian/jira/{me, my-issues, current-sprint, sprints, backlog, search, issue/:key, users/search}`) — full ticket + sprint + backlog access plus JQL escape hatch. **Plus the one write exception:** `create-meta`, `POST /issues` (create + `links`), `PATCH /issues/:key` (update + transition + additive `links`), `POST /issues/:key/comments` — argo auto-stamps Team=Prometheus, no agent attribution.
- **Atlassian / Confluence** (`/atlassian/confluence/{spaces, search, pages/:id, pages/:id/children, recently-updated}`) — CQL search + page body in rendered HTML.
- **GitLab** (`/gitlab/{me, users/search, users/by-username, merge-requests, projects/:id/merge-requests/:iid + approvals + discussions, projects/:id/commits + releases, events/recent}`) — cross-project MR view, per-MR approval state + threaded discussions, per-project commits + releases. MRs auto-extract `jiraKeys` for direct Jira pivots.

The skill is **personal-orientation, never team-facing** — read-only across every system **except Jira**, where it creates/updates/comments/transitions Johannes's own tickets on his behalf (Team=Prometheus auto-stamped, no agent attribution — a delegated personal action, not posting for the team). It never sends Teams messages, posts Outlook mail, creates Confluence pages, opens GitLab MRs, or speaks for / pings teammates. Team-facing assistance (Greenkeeper / standup automation) is a separate Hermes Agent (not yet deployed). The skill's SKILL.md owns: identity model (`/m365/team` `members[]` + `repos[]`), MR↔Jira link via `jiraKeys`, structured "is MR blocked" check (5 conditions), and the recurring-question playbook ("what's on my plate", "what needs my review", "is X blocked", "Confluence context for Y").

**What's wired into briefings vs ad-hoc-only.** The morning briefing surfaces exactly three work signals: (1) today's Outlook calendar (merged with personal calendar under `:office:` prefix in the schedule section), (2) Jira sprint commitments — `:briefcase: Work — Sprint & Reviews`, (3) GitLab MRs needing action (ready-to-merge + needs-review, also in the Work section). The evening report keeps only tomorrow's merged calendar (wind-down tone forbids pressure-piling). **Everything else on the work surface is ad-hoc-only** — `/m365/important` (curated Teams alerts), `/m365/chats` + `/teams/.../channels/.../messages`, `/atlassian/confluence/*`, `/gitlab/events/recent`, `/gitlab/.../commits + releases` — never wired into briefings, never into the watchdog (watchdog is personal apps + infra alerts only). Errors: `503 M365 not authenticated …` → tell the user to run `bun m365:auth:prod` from `~/SourceRoot/argo`. `503` on `/gitlab/*` or `/atlassian/*` → corresponding PAT expired.

**Split: garmin-health vs strength.** Garmin Health owns passive measurements (`/daily-metrics`, `/recovery`, `/training-load`, `/fitness-direction`, `/activities`, `/weight-log`, `/user-profile`). Strength owns active lifting (`/workouts`, `/workout-sets`, `/exercises`) plus the 13-endpoint `/workouts/summary/*` analytics suite (e1RM, INOL, ACWR per-exercise, MEV/MAV/MRV landmarks, deload-signal, readiness). The cross-skill bridge is `/workouts/summary/readiness` — it joins Garmin recovery + strength fatigue debt and lives in `strength`. Note `weight-log` + `user-profile` are tagged Garmin Health in the live OpenAPI even though they're physically distinct from daily metrics; respect that grouping in cross-references.

**API secret:** `op://common/api/SECRET` (account `tkrumm`) — wired in `.env.tpl`.

**WalkingPad + Usage Tracking (newly surfaced, ad-hoc only).** Two recently-added Argo domains are now in `argo-api`: **WalkingPad** (`/walking-pad/*` — treadmill sessions, streak, pace; `references/walking-pad.md`; read-only — the device ingests sessions) answers "how far did I walk"; **Usage Tracking** (`/usage/*` — AI token/cost KPIs across all sources) answers "what have I spent on AI". Both are **ad-hoc only** — never wired into briefings or the watchdog (consistent with the watchdog-personal-only + briefing-work-scope rules). `/hermes/*` (Hermes Chat) and `/ai/v1/*` (AI Gateway) are infra Hermes never calls — see the argo-api taxonomy.

## Research (research-gateway)

Deep cited research is served by the standalone **research-gateway** (`research.jkrumm.com`,
VPS, **Tailscale-only** — the Mac Mini reaches it; same grey-cloud DNS pattern as the
audio-gateway). Hermes consumes it through the **`research-gateway` skill** (`skills/research-gateway/SKILL.md`)
via the `terminal` tool: submit `POST /research/ {query, depth?}` → `{jobId}`, then poll
`GET /research/{jobId}` until `status: done` → `{result: {report, citations[], sources[]}}`.
Async submit+poll because deep research outlasts a single sync call — even `quick` depth runs
1–3 min. It is the **preferred path for substantive / factual / library-version questions** (the
`research-first` discipline), over Hermes's built-in Tavily web search, which stays for quick
single lookups. Runs on EU/IU models, off Max.

- **Auth:** `RESEARCH_API_KEY` = `op://vps/research-gateway/API_SECRET` (the gateway's own
  bearer, shared with the Claude Code `/research` skill). Wired in `.env.tpl` + the README
  `.env` builder. Base URL hardcoded in the skill (like argo / karakeep).
- **tirith + cron allowlists extended:** both `patches/tirith-allowlist-argo-pipes.patch` and
  `patches/cronjob-tools-allowlist-argo-bearer.patch` now include `research.jkrumm.com` in their
  trusted-host sets, so `curl https://research.jkrumm.com/... | jq` doesn't trip the
  pipe-to-interpreter / exfil gates (see *Local Modifications*).
- **Routing guard (SOUL.md):** "research X now" → `research-gateway` skill; "remind me to
  research X later" → `capture` → TickTick; book / novel discovery → `reading`.
- **Name collision (why `research-gateway`, not `research`):** upstream ships a bundled skill
  *category* directory `~/.hermes/skills/research/` (containing `arxiv`, `blogwatcher`,
  `llm-wiki`, `polymarket`, `research-paper-writing`). A top-level `research` symlink would
  collide with that dir (and `make setup` would back the whole category up, only for `hermes
  update` to re-seed and reconflict). So our skill is named `research-gateway` and symlinks to
  `~/.hermes/skills/research-gateway` — no collision, no reconciliation step needed. Routing is
  by description/tags, so natural-language "recherchier mal" still triggers it.

## Second Brain (Obsidian + KaraKeep)

Two skills make Hermes the front door to Johannes's second brain. Roles are deliberately distinct (don't blur them):

- **`obsidian`** — the **source of truth**: read/search/write the PARA vault at `~/SourceRoot/brain/`. The vault is also a **git repo**, shared with Claude Code (`/brain` skill) — LiveSync stays the continuous cross-device backup, git is the deliberate review + history gate (`git diff` before a write to `wiki/` or the curated surface counts as done). The retired standalone OKF brain repo is folded into this vault. Shared machine-facing contract for both agents: `~/SourceRoot/brain/AGENTS.md`. **CLI-first** (`/usr/local/bin/obsidian` → `obsidian-cli`; Obsidian.app runs on this Mac Mini, so the CLI goes through Obsidian's live API — metadata cache, backlinks, Dataview, LiveSync-clean), with a **filesystem fallback** when Obsidian isn't running. No secret. Encodes the *real* vault conventions (actual folders `00_Inbox`/`01_Journal`/`02_Daily`/`03_Projects`/`04_Areas`/`09_Templates`/`wiki`, `YYYY-MM-DD` naming, `#topic/subtopic` tags, per-type frontmatter) plus the two-layer split validated by `node .scripts/vault-lint.mjs`: agentic knowledge in the top-level `wiki/` tree (atomic English concept notes carrying `type`+`description`, strict), and the curated human surface `03_Projects`/`04_Areas` (Area/Project folder notes + human pages, any language, light — they link *down* into `wiki/`; no `05_Resources` tier — reference material is a `wiki/` note or an Area page). **Does not write `01_Journal/`** (the parked journal subsystem owns it).
- **`karakeep`** — the **read-later / everything bucket**: REST against `https://karakeep.jkrumm.com/api/v1` (Bearer `$KARAKEEP_API_KEY` → `op://hermes/karakeep/api-key`, Tailscale-only). Save links/text, full-text search (Meili — no semantic search in 0.32.0), lists incl. smart lists, tags, highlights. AI auto-tagging is async (DeepSeek-V4-Flash via IU). State cache (`skills/karakeep/state.json`, gitignored, seeded by `make setup`) holds lists+tags, refresh-on-miss.

**Routing model** (the `capture` skill is the router): KaraKeep = reference/reading you consume · Obsidian = durable knowledge you author · TickTick = human action · GitHub = code change.

**Bundled-skill collision (obsidian).** Upstream ships a stock bundled `obsidian` skill (generic, filesystem-first) listed in `.bundled_manifest`. Our local `obsidian` (symlinked from this repo) has the same name; the stock one was removed from `~/.hermes/skills/note-taking/obsidian/` so ours is canonical. It **re-seeds on `hermes update`** — `/hermes-update` carries the `rm -rf ~/.hermes/skills/note-taking/obsidian` reconciliation step. In `hermes skills list` ours may show source `builtin` (name is in the manifest) — cosmetic; an empty *category* column confirms the top-level symlink (ours) is loaded.

**Kobo / e-reader (planned, Phase 4).** Reading selected vault notes on the Kobo via KOReader will use **Readeck** (single Go binary; `iceyear/readeck.koplugin` does bidirectional highlight + progress sync; OPDS at `/opds`) as a dedicated reading surface — *not* KaraKeep (its koplugin is save-only) and *not* Wallabag (no highlight sync-back). Hermes will push curated Obsidian/KaraKeep content into Readeck and pull highlights back to Obsidian. Not built yet.

## Local Modifications to Upstream

Re-apply after `hermes update`: **eight `.patch` files** (each applied with `git apply --3way`; `/hermes-update` carries the loop). All eight are regenerated against the current upstream baseline (**v0.19.0**, upstream `46c7a407`) so they re-apply cleanly on minor upstream bumps; only a structural rewrite of a touched function needs a hand-rewrite.

> **Retired patch — `auxiliary-client-gpt5-max-completion-tokens` (dropped at v0.15.1).** It forced `max_completion_tokens` for `gpt-5*`/`gpt-4o`/`o-series` models by name in `_build_call_kwargs`. v0.15.1 rewrote that function to **omit `max_tokens` entirely** for non-Anthropic custom endpoints (it only sets it for Anthropic-compat endpoints, where it's mandatory) — so the patch's target block no longer exists, and its defensive goal (never send `max_tokens` to a gpt-5 aux on the IU endpoint → HTTP 503) is now achieved by upstream's omit-by-default behavior. The direct-OpenAI `max_completion_tokens` case is handled by upstream's separate `auxiliary_max_tokens_param` helper. The current config (DeepSeek-V4-Flash auxiliaries, `chat_completions`) never hit this path regardless. Patch file deleted from `patches/`.

> **Retired patch — `slack-audio-mime-ext` (dropped at v0.18.2).** It mapped a Slack audio file's MIME type to the correct download extension (`audio/mp4` → `.m4a` etc.), since upstream's `ext = "." + mimetype.split("/")[-1]` produced unmapped extensions that got force-defaulted to `.ogg` — corrupting the bytes/extension pairing the STT endpoint expected. v0.18.2's platform-plugin rewrite (see below) introduced upstream's **own** `_resolve_slack_audio_ext()` helper (`plugins/platforms/slack/adapter.py`) that does the same job more thoroughly: real filename extension first, then a `_SLACK_AUDIO_MIME_TO_EXT` mimetype map, falling back to `.m4a` (not `.ogg`) as a last resort — plus a companion `_is_slack_voice_clip()` check that reroutes Slack's `video/mp4`-mislabeled in-app voice clips onto the audio path. Our patch's target is fully superseded. Patch file deleted from `patches/`.

> **Retired hunk — `_resolve_thread_ts` synthetic-thread guard (dropped at v0.19.0, with the switch to threads).** It detected a synthetic `thread_id == reply_to` (no real `thread_ts`) and returned `None` so the reply posted flat in the channel. Two independent reasons it went: (1) it was **already dead code** — upstream's own `if not reply_in_thread:` branch (`adapter.py:3174-3180`) *returns unconditionally* before ever reaching it, and it was functionally equivalent anyway (outbound metadata is built by `_thread_metadata_for_source` in `gateway/platforms/base.py`, which sets only `thread_id`, never `thread_ts`, so the guard's extra `not real_thread_ts` condition was always true). CLAUDE.md previously claimed the guard "targets the `if metadata:` branch that upstream still lacks" and that "our config uses `reply_in_thread: true`" — **both were wrong**; the key had been `false` since `1e753e9`. (2) Once `reply_in_thread: true` (v0.19.0, see the threading note below) the guard becomes *actively harmful*: upstream's gate no longer returns early, so the guard fires on every top-level message → flat replies **and** a fresh context window per message, the worst of both. The other three hunks of `slack-cannot-reply-to-message.patch` (SlackApiError import, `cannot_reply_to_message` retry, mrkdwn normalization) are unaffected and stay.

> **Slack threading = context-window boundary (changed at v0.19.0).** `slack.reply_in_thread` is now **`true`** (upstream's default — every read site is `.get("reply_in_thread", True)`; the key is absent from `DEFAULT_CONFIG`, so the code default governs). This is not cosmetic: `build_session_key()` (`gateway/session.py:1029`, key assembly at `1114-1131`) appends `thread_ts` to the session key **only when `source.thread_id` is set**, and the inbound scoping block (`adapter.py:5607-5638`) sets `thread_id` to the message's own ts for top-level messages *only* when `reply_in_thread` is true. So: **one Slack thread == one session == one context window.** Under the previous `false`, every top-level channel message collapsed into a single never-resetting session (`agent:main:slack:group:<team>:<C…>:<U…>`) — observed live at 213 messages over 6 days — while a real thread reply got an isolated window, with no visual cue which one you were in. Consequence of the flip: continuing a topic means replying **inside** its thread; a new top-level message is deliberately a clean slate. `session_reset.mode` is unset (default `none`), so only the compressor bounds a long-lived thread. Note `group_sessions_per_user` only affects the *flat* key shape — `isolate_user` is forced off whenever a thread is present (`session.py:1126-1129`).

> **Platform architecture rewrite (v0.18.x).** Upstream moved built-in chat platforms out of `gateway/platforms/` into a plugin system: Slack now lives at `plugins/platforms/slack/adapter.py` (previously `gateway/platforms/slack.py`, which no longer exists). `gateway/platforms/base.py` (the shared response-delivery base class) stayed in place. All Slack-targeting patches below were rewritten against the new `adapter.py` path and file structure during the v0.16.0 → v0.18.2 update.

- **STT tool itself is stock upstream** — `tools/transcription_tools.py` (native `openai` STT) is unpatched, pointed at the **audio-gateway** (`audio-gateway.jkrumm.com`, tailnet-only) purely via `config.yaml` (`stt.openai`). Repointed off the retired Mac audio-proxy (`:7716`) when the audio stack consolidated onto the gateway. The Slack *download* path that feeds STT is now handled natively by upstream's `_resolve_slack_audio_ext()` (see the retirement note above) — no patch needed. The old localai-helper client patches (`tts_fast_tool.py`) and the `toolsets-expose-text-to-speech-fast` patch were removed when Hermes moved to Gemini Charon.
- `~/.hermes/hermes-agent/tools/tts_tool.py` — one small local modification on top of the stock native tool: name the saved audio file from the gateway's `X-Audio-Title` response header (a short title generated by the gateway's `DeepSeek-V4-Pro` prep step) instead of the upstream `tts_<timestamp>.mp3`, so the Slack attachment shows a real name. Source: `patches/tts-tool-audio-title.patch`. Re-apply: `cd ~/.hermes/hermes-agent && git apply ~/SourceRoot/hermes-agent/patches/tts-tool-audio-title.patch`. The patch (a) switches `_generate_openai_tts` to `with_raw_response` so it can read the header alongside the binary body and returns the decoded title, and (b) renames the output file to a sanitized title via a new `_rename_with_title` helper. TTS provider/voice/base_url stay config-driven (`tts.openai` → the **audio-gateway** at `audio-gateway.jkrumm.com`, repointed off the retired audio-proxy `:7716`). Without it, voice memos still work but land as `tts_<timestamp>.mp3` in Slack. The title itself is produced in the **audio-gateway** repo (`src/gemini-tts.ts`, `X-Audio-Title` header). **v0.18.2 nuance:** `_resolve_openai_audio_client_config()` independently grew a third `is_managed` return value upstream (routes to a managed OpenAI audio gateway); the patch's `_unquote` import (for decoding the title header) and the 3-tuple unpack now coexist — both are load-bearing, keep both on re-apply.
- `~/.hermes/hermes-agent/plugins/platforms/slack/adapter.py` (moved from `gateway/platforms/slack.py` at v0.18.x — see the platform rewrite note above) — three changes, all in `patches/slack-cannot-reply-to-message.patch`. Re-apply: `cd ~/.hermes/hermes-agent && git apply ~/SourceRoot/hermes-agent/patches/slack-cannot-reply-to-message.patch`.
  - `format_message()` pre-steps: normalize `*` list markers to `-`, strip backticks from inline code containing emoji shortcodes. **Not upstream.**
  - ~~`_resolve_thread_ts` synthetic-thread guard~~ — **retired at v0.19.0**, see the retirement note below.
  - `send()` retry: on `cannot_reply_to_message`, drop `thread_ts` and retry chunk as plain channel message. **Not upstream.**
- `~/.hermes/hermes-agent/gateway/platforms/base.py` — pass the text reply's anchor (`_reply_anchor_for_event(event)`) to the media senders (`send_voice`/`send_video`/`send_document`) in the response media-dispatch loops, so attached files thread identically to the text reply. Source: `patches/slack-media-inline-reply-anchor.patch`. Re-apply: `cd ~/.hermes/hermes-agent && git apply ~/SourceRoot/hermes-agent/patches/slack-media-inline-reply-anchor.patch`. **Dormant since v0.19.0's switch to `reply_in_thread: true`:** with threads on, `_resolve_thread_ts` returns the same `thread_id` whether or not `reply_to` is passed, so media and text land together either way. Kept applied — it costs nothing, keeps the text and media paths symmetric, and is immediately load-bearing again if `reply_in_thread` ever goes back to `false`. Under `false` it *was* load-bearing: the media senders got `reply_to=None`, so the flat-reply guard (which only nulls the message's own ts when it equals `reply_to`) couldn't fire, and TTS audio landed in a thread while the text reply sat inline. Real threads always threaded correctly (anchor ≠ thread parent). **v0.18.2 nuance:** upstream independently wraps this metadata in `_mark_notify_metadata()` (renamed to `_final_thread_metadata`) for the same call sites — the patch's `reply_to=_media_reply_anchor` addition and upstream's `_final_thread_metadata` variable now coexist; keep both on re-apply.
- `~/.hermes/hermes-agent/cron/scheduler.py` — skip `resolve_channel_name` for raw Slack channel IDs in `_resolve_single_delivery_target`. Source: `patches/scheduler-skip-resolver-for-slack-ids.patch`. Re-apply: `cd ~/.hermes/hermes-agent && git apply ~/SourceRoot/hermes-agent/patches/scheduler-skip-resolver-for-slack-ids.patch`. Without this, `--deliver slack:<C…ID>` fails with `channel_not_found` for any channel that has exactly one thread session in the directory (prefix-match collision against compound `C…:thread_ts` entries).
- `~/.hermes/hermes-agent/run_agent.py` — broaden `_try_refresh_anthropic_client_credentials` skip-condition from Azure-only to all third-party Anthropic-compatible endpoints. Source: `patches/run-agent-third-party-endpoint-token-refresh.patch`. Re-apply: `cd ~/.hermes/hermes-agent && git apply ~/SourceRoot/hermes-agent/patches/run-agent-third-party-endpoint-token-refresh.patch`. Without this, every `messages.create()` call invokes `resolve_anthropic_token()` which prefers `~/.claude/.credentials.json` OAuth token over `ANTHROPIC_API_KEY`, swaps the client's IU key for the OAuth token, and the next request 401s on the IU endpoint with "Authorization parsing failed" / "invalid x-api-key". v0.12 only excluded `azure.com` from the refresh; our IU endpoint (`unified-endpoint-main.app.iu-it.org/anthropic`) needs the same exclusion. The patch swaps the literal `azure.com` check for `_is_third_party_anthropic_endpoint(base_url)`, which already handles all non-`anthropic.com` hosts.
- `~/.hermes/hermes-agent/tools/tirith_security.py` — early-return `allow` in `check_command_security` when the command is a trusted-personal-API pipeline (every URL on `argo.jkrumm.com`, `karakeep.jkrumm.com`, or `research.jkrumm.com`, every pipeline-stage program in a safe text-tool set, no shell escape hatches). Source: `patches/tirith-allowlist-argo-pipes.patch`. Re-apply: `cd ~/.hermes/hermes-agent && git apply ~/SourceRoot/hermes-agent/patches/tirith-allowlist-argo-pipes.patch`. Without this, tirith's `[HIGH] Pipe to interpreter` rule fires on **every** `curl https://argo.jkrumm.com/... | python3 ...` (and `| jq` to a lesser degree) the LLM produces — Hermes constantly stops at a Slack approval gate ("Command Approval Required") for completely safe argo calls that pipe JSON to python3 for formatting. The threat tirith protects against ("Downloaded content will be executed without inspection") doesn't apply: argo is bearer-authenticated and serves JSON parsed as data, not executable code. Patch mirrors the cron-scanner allowlist precedent — only the allowlisted hosts (`argo.jkrumm.com`, `karakeep.jkrumm.com`, `research.jkrumm.com`, via the `_ALLOWED_PIPELINE_HOSTS` frozenset) + a small safe-program set (curl, jq, python3, head, tail, tee, tr, cat, wc, cut, grep, sort, awk, sed, uniq, xargs) are accepted, and any redirect, `$(...)`, backtick, `;`, `&&`, `||`, `&`, `(`, `>` token defers to tirith. Sanity-tested against 19 representative shapes (8 allow, 11 defer including mixed-host, eval, subshell, `sh -c`, redirect). **v0.18.2 nuance:** upstream independently added a circuit breaker (`_circuit_open`, after `_CRASH_LIMIT` consecutive tirith spawn/execution failures) as its own early-return at the same insertion point; the patch's argo-pipeline bypass now sits directly after it — both are independent early-return gates, order doesn't affect correctness.
- `~/.hermes/hermes-agent/tools/cronjob_tools.py` — extend the shared `_strip_cron_safe_constructs` helper with an argo + karakeep + research allowlist so the cron-prompt scanners stop flagging legitimate `curl -H "Authorization: Bearer $HOMELAB_API_KEY" "https://argo.jkrumm.com/..."` shapes (and the `$KARAKEEP_API_KEY` → `https://karakeep.jkrumm.com/...` and `$RESEARCH_API_KEY` → `https://research.jkrumm.com/...` equivalents) carried by the bundled argo + karakeep + research-gateway skills. Source: `patches/cronjob-tools-allowlist-argo-bearer.patch`. Re-apply: `cd ~/.hermes/hermes-agent && git apply ~/SourceRoot/hermes-agent/patches/cronjob-tools-allowlist-argo-bearer.patch`. **v0.15.1 refactor:** upstream split the cron scanner into `_scan_cron_prompt` (raw user prompt — still checks `_CRON_EXFIL_COMMAND_PATTERNS`, incl. `exfil_curl_auth_header`) and `_scan_cron_skill_assembled` (skills-loaded — now uses a looser pattern set that already *drops* the curl/exfil shapes), with the GitHub-auth exemption hoisted into a shared `_strip_cron_safe_constructs` helper both call. The argo allowlist now lives in that **shared helper** (was inline in `_scan_cron_prompt`), so it covers both paths: the still-live `exfil_curl_auth_header` block on the raw-prompt path, plus harmless redundancy on the assembled path. Without it, any cron whose raw prompt carries an argo bearer curl fails with `Blocked: prompt matches threat pattern 'exfil_curl_auth_header'`. The patch sanitizes allowlisted-host markdown bash fences plus any single-line argo/karakeep curl before the exfil scan runs, but leaves any fence containing a non-allowlisted host intact so real exfil to a different host still triggers. Co-located evil curls in the same fence as argo/karakeep curls still get caught because the fence-sanitizer skips fences with a foreign host alongside the allowlisted ones. (Behaviorally tested post-update: argo single-line + fence sanitized, evil single-line + mixed fence preserved, GitHub fallback intact.)
- `~/.hermes/hermes-agent/agent/auxiliary_client.py` — respect `api_mode: anthropic_messages` in the `provider == "custom" + explicit_base_url` branch of `resolve_provider_client`: skip the `/anthropic`→`/v1` rewrite that `_to_openai_base_url` would otherwise apply, so `custom_base` keeps the `/anthropic` suffix. Source: `patches/auxiliary-client-anthropic-mode-respect.patch`. Re-apply: `cd ~/.hermes/hermes-agent && git apply ~/SourceRoot/hermes-agent/patches/auxiliary-client-anthropic-mode-respect.patch`. **v0.15.1 nuance:** upstream's `_maybe_wrap_anthropic` now detects the Anthropic surface via `api_mode == "anthropic_messages"` *explicitly* (decoupled from the URL suffix), so detection itself no longer breaks — **but** the patch is still load-bearing because `build_anthropic_client(api_key, base_url)` is handed `custom_base`; if that got rewritten to `/v1` the Anthropic client targets `/v1/messages` on the IU `/anthropic`-only gateway → 404 "Endpoint not found". The patch keeps the correct `/anthropic` base. **Currently defensive/dormant:** the live config routes the brain *and* auxiliaries through `${OPENAI_BASE_URL}` with `api_mode: chat_completions` (DeepSeek-V4-Pro / -Flash), so the `anthropic_messages` branch isn't exercised today — the patch only matters if a model is re-routed through the IU `/anthropic` endpoint. Kept applied (clean, zero cost on the `chat_completions` path).

## Setup

```bash
make setup        # idempotent — symlinks, cron, CC skills
make status       # verify everything is in place (incl. audio-gateway remote health)
```

Prerequisites:
1. `hermes` CLI installed (see README.md §2)
2. `audio-gateway` reachable at `https://audio-gateway.jkrumm.com/health` (VPS Docker container over the tailnet) — for TTS/STT
3. 1Password CLI authenticated as `tkrumm`

## Editing Rules

**Adding a Hermes skill:** create `skills/{name}/SKILL.md`, add `{name}` to
`HERMES_SKILLS` in the Makefile, run `make setup`. If the skill should appear in scheduled briefings, also wire it into the relevant cron prompt (`cron/*.prompt.txt`) and re-sync `cron/jobs.json`.

**Adding a CC slash command for Hermes:** create `.claude/skills/{name}/SKILL.md`. Auto-loaded by Claude Code when started inside this repo — no symlink, no Makefile change needed.

**Patches:** when fixing bugs in upstream Hermes, save the diff under `patches/`
and document the re-apply command in this file.
