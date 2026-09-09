# hermes-agent — Hermes Agent Instructions

Commands, tables and gotchas — dense reference for every session. Full rationale, incident
history and per-file detail live in `docs/*.md`; each section here points at its own.

## What This Repo Is

VCS source of truth for Johannes's Hermes Agent setup, Mac Mini-only. Everything here is
symlinked into `~/.hermes/` — edit at either end, git sees it here.

Audio (TTS + STT) is the **`audio-gateway`** service (`~/SourceRoot/audio-gateway`), an
OpenAI-compatible VPS container at `https://audio-gateway.jkrumm.com/v1` over the tailnet.
Hermes only points its native `openai` TTS/STT providers at it in `config.yaml` — this repo
installs and patches no audio service. TTS = ElevenLabs via the IU Replicate route:
`elevenlabs/flash-v2.5` (voice "Mark") for chat replies, `elevenlabs/v3` for briefings
(`skills/briefing-tts`); STT = `gpt-4o-transcribe`. Rationale: `modelpick/docs/decisions/audio-stack.md`.

**This repo is public.** Anything Hermes writes here gets read for tailnet names, node IPs,
workspace user ids and `homelab-private` internals before it is committed — all four appeared on
the first pass.

**After any edit: commit here.**

## Symlink Map

`make setup` writes these symlinks. Full table + host-LaunchAgent detail, per-script:
**`docs/symlinks-and-agents.md`**.

| File here | Live path | Notes |
|-|-|-|
| `config.yaml`, `.env.tpl`, `SOUL.md` | `~/.hermes/…` | edit here, live immediately; `.env.tpl` is the one list of `KEY=op://…` refs |
| `cron/`, `scripts/`, `hooks/` | `~/.hermes/…` | Hermes-driven cron + pre-run scripts (must live under `HERMES_HOME/scripts/`) + host-level shell scripts |
| `plugins/{name}/` | `~/.hermes/plugins/{name}/` | **`HERMES_PLUGINS`** is the source of truth. Today `dispatch-approval` (the Ed25519 signer). Must **also** be enabled once — `hermes plugins enable <name>`; the symlink alone is inert. |
| `config/` | `~/.hermes/config/` | `dispatch-repos.json`: root, `deny`, `defaultTier`, per-repo ceilings |
| `skills/{name}/` | `~/.hermes/skills/{name}/` | **`HERMES_SKILLS` in the Makefile is the source of truth** — 18 dirs (roster + `homelab` category-dir note: docs). |
| `USER.md` | `~/.hermes/memories/USER.md` | **copied** — Hermes writes to it |

**A skill is durable only if symlinked from this repo.** `skills.external_dirs` satisfies the
v0.16.0+ skill-trust check **and** protects a skill from the background self-improvement
curator — a skill created ad hoc under `~/.hermes/skills/` has neither and gets silently
rewritten by accretion. Detection: warden's `watchdog-poll.py` `stray_skill` source (30 min). Full
mechanism + adoption path: **`docs/symlinks-and-agents.md`**.

**Host-level scripts** (user LaunchAgents, not symlinked): `hermes-liveness.sh` (300s — gateway
state + Slack connected + the live pid belongs to launchd's job), `hermes-backup.sh` (daily
03:00 — rsync to homelab, `mkdir`-lock against overlap). The alert-triage act-loop is a
LaunchAgent too, but it's `~/SourceRoot/warden`'s own — see **Alert triage** below.
`HERMES_PLISTS_RETIRED` unloads +
removes labels this repo no longer installs — the four `hermes-{webui,serve}{,-liveness}` labels
sit there since the 2026-09-07 teardown (Collie + Slack are the surfaces; the third-party WebUI
clone and `hermes serve`/Hermes Desktop are gone). `make status` grades every agent like
dotfiles' doctor. Logs declared, never globbed, in `dotfiles/scripts/log-rotate.sh`.

**Scheduled jobs are LaunchAgents, never macOS crontab** — a `crontab -` *write* needs Full
Disk Access and hangs forever on the headless mini. Done 2026-08-02 — no hermes entries in
`crontab -l`. All 5 live `hermes cron` jobs (ids, schedules, delivery) + reasoning:
**`docs/scheduled-jobs.md`**. The watchdog poll and dispatch sweep are LaunchAgents in
`~/SourceRoot/warden` now, not `hermes cron` jobs — see *Alert triage* below.

**Claude Code per-repo skills** (`.claude/skills/`, committed, no symlink): `/hermes-validate`
(test routing, fix SOUL.md / SKILL.md) · `/hermes-update` (pull upstream, re-apply patches,
restart gateway).

## Dispatch Bridge — handing repo work to Claude Code

Hermes observes well and reads repos badly — `gpt-5.6-luna` with a `terminal` tool cannot use a
repo's `CLAUDE.md`, `.claude/rules/` or `.claude/skills/`. `scripts/hermes-cc.sh` is the bounded
client that hands the episode to Claude Code (sideclaw's `dispatch` job tool) instead. Design +
why each bound is shaped this way: **`docs/dispatch-bridge.md`**.

**Verbs:** `dispatch <repo>` · `status <job-id>` · `list [open|today|all]` · `merge <job-id>` ·
`cancel <job-id>` — `cancel` abandons the LOCAL record only (sideclaw has no cancel endpoint,
and the help text says so).

| Invariant | Detail |
|-|-|
| No verb takes a path, command or URL | a dispatch names a **repo**, resolved under the single `root` in `config/dispatch-repos.json`. `.`/`..`/dotted names refused; the resolved checkout's parent must **be** the resolved root. |
| `deny` list | `dotfiles-private`, `homelab-private`. Both also carry `sensitive: true` — the one carve-out of `deny`, opening `investigate` only, `"sensitive": true` on the submitted body, sideclaw's own scan withholding a matched verdict rather than leaking it. `author`/`implement` stay refused. `brain` is **not** denied: `tiers.investigate` (read-only, worktree-isolated) since 2026-08-15. |
| Brief is data, never argv | stdin (`<<'BRIEF'` quoted heredoc) or `--brief-file`. **No `--brief`** — as argv it would be shell-expanded before the script ran. |
| Tiers | `investigate` (read-only → verdict) · `author` (+ one GitHub issue) · `implement` (`dispatch/…` branch + **draft** PR). **Every tier runs in its own throwaway worktree**, read tiers included — `readOnly` removes Edit/Write, not Bash. |
| Ceilings | `defaultTier: implement`, `investigate` floor for `dotfiles`/`brain`/`hermes-agent` (`vps` and `homelab` came off it 2026-09-08 — deployment surfaces, not the rules that bound the agents) — the last is this repo's own control plane (`config.yaml`, `scripts/`, `hooks/`, `skills/` are symlinked live into `~/.hermes/`), a different reason than `dotfiles`' — see `config/dispatch-repos.json`'s comment block. Above-ceiling/denied/outside-root refuses exit 4; a misspelled name is exit 64. No `implement` allowlist, deliberately. |
| `implement` gate | `--why` **and** `--confirm`. Without `--confirm` it prints the plan + `wouldNeverDo` and exits **0**. `--auto-from-item <event_id>` is a second, narrower door for warden's `triage.py` only — every precondition re-checked from `~/.warden/warden.db`, no Slack click needed once it passes; see *Alert triage* below. |
| Secret scan | refuses (never redacts) a brief carrying credentials, scans the diff's **added lines** too — handler-side. |
| Budgets | 20 dispatches/UTC day, ≤5 `implement`, ≤3 `merge`, 170s `--wait` cap. `HERMES_CC_{DAILY,IMPLEMENT,MERGE}_BUDGET` to raise. |

**`--confirm` is a signed approval artifact, not an instruction.** Approve/Deny buttons post
into the origin channel; the click is signed by an **Ed25519 key minted at gateway startup, RAM
only** (`plugins/dispatch-approval/`), then **runs the approved verb itself** — bound to
`verb|repo|tier|brief|why|context`, single-use, 30-min TTL, fails closed. Enable once:
`hermes plugins enable dispatch-approval`. *Tell for the one bug this has had:* a refusal saying
**"has not been clicked yet"** despite a visible Approve → `grep 'published public key'` vs
`Wired 2 plugin action handler` in `~/.hermes/logs/agent.log`; no matching wire line means a
non-gateway process overwrote the public key. Full evolution: **`docs/dispatch-bridge.md`**.

**`merge <job-id>` lands the draft PR with no human on GitHub** (owner decision) — a job id never
a PR number, eligibility derived from `dotfiles/config/pr-required-repos.json`, every bound
re-checked against the **current** head with the head SHA pinned. **Primary gate re-keyed
2026-09-08**: `~/SourceRoot/warden/config/triage-policy.json`'s per-repo `autoMergePaths` (every changed path must
match, or refuse) and `noCiRequired` (a repo with zero CI check-runs on the head commit and no
acknowledgement now FAILS — `mergeable_state: clean` used to read as "CI passed" even with
nothing run), plus the step-7 validation (`dispatches.validation_status == 'confirmed'`); the old
40-file/2000-line ceilings are a backstop, not primary, now. Deliberately **not** gated on
the signed approval (reverted after an hour — see docs). GitHub credential on stdin, never argv.
`op://mini/github/token` needs **three grants** — `Contents: write` plus `Issues: write` and
`Pull requests: write`; with only the first, the last step fails as "Resource not accessible by
personal access token".

**`slack.allow_bots: all` is deliberate — do not "fix" it.** The trust boundary is the
workspace, not human-vs-bot: HomeLab/VPS/Argo post from inside the tailnet and live `#alerts`
auto-triage depends on it. `require_mention_channels` silences `#media`/`#updates` (pure-echo
channels) — inbound-only, `hermes send`/cron/dispatch verdicts still post there.

**Tests** (`~/.hermes/hermes-agent/venv/bin/python3`): `test_hermes_cc.py` (134, stubbed job
server + GitHub), `test_dispatch_approval.py`, `test_raw_agent_guard.py`,
`test_repo_write_guard.py`, `test_dispatch_sweep.py`, `test_cron_allowlist.py`; the other half is
`sideclaw/tests/` (`bun test`, mutation-verified — worktree isolation, the diff-refusal ladder,
the secret scan, the nonce fence around the brief).

**Hermes cron pre-run scripts** (run by `hermes-agent` before each run, not launchd):
`briefing-context.py`/`briefing-coverage.py` feed the morning briefing (TickTick + GitHub
coverage) — the former also reaches across to warden's `watchdog-summary.py`
(`WARDEN_WATCHDOG_SUMMARY`-overridable) for the briefing's Infrastructure section.
`agents-cron.py`/`narratives-cron.py` are the same thin-loader shape for
`agents-overview.py`/`project-narratives.py`.

**`hermes cron create --script` rejects any substantial script** (`cron/lifecycle_guard.py`
fails closed on an exhausted recursion budget) — keep entry points thin, logic in an imported
module. Detail: **`docs/scheduled-jobs.md`**.

## Alert triage

**Moved to `~/SourceRoot/warden` 2026-09-09.** `triage.py` (LaunchAgent
`com.jkrumm.warden-loop`, 10 min) is the deterministic act-loop over
`~/.warden/warden.db` that turns deduplicated watchdog events into Slack cards
and, once eligible, `implement` dispatches. It reaches back into this repo
through `scripts/hermes-cc.sh dispatch --auto-from-item` (every precondition
re-checked from `~/.warden/warden.db`, no Slack click needed) and the
`dispatches`/`dispatch_approvals` tables `hermes-cc.sh` and
`plugins/dispatch-approval/` still own at that same ledger path — see
*Dispatch Bridge* above. Full state machine, the policy contract
(`config/triage-policy.json`, now at `~/SourceRoot/warden/config/`), and why
the loop is a LaunchAgent rather than a `hermes cron` job:
`~/SourceRoot/warden/CLAUDE.md`, `DESIGN.md`, `STATE.md`.

## Secrets — native `secrets.command` over the headless cache (v0.19.0+)

No plaintext `~/.hermes/.env`, no launch wrapper. `config.yaml`:

```yaml
secrets:
  command:
    enabled: true
    command: "$HOME/.local/bin/secrets-run export --env-file=$HOME/.hermes/.env.tpl | sed 's/^export //'"
    helper_timeout_seconds: 15
    override_existing: true
```

`secrets-run` is the dotfiles shim over the age-encrypted offline cache; `.env.tpl` stays the
single list of `KEY=op://vault/item/field` refs. The `sed` exists because `export` emits
`export K='V'` while the bulk parser wants `K=V`. 0.29s for 29 refs (default budget 3s), and
secrets resolve for **every** hermes invocation — gateway, CLI, cron.

- **Not `secrets.onepassword`**: it needs an interactive `op` session (hangs headless) or a
  standing `OP_SERVICE_ACCOUNT_TOKEN` (a live credential on an always-on box). The sealed cache
  is strictly stronger — its contents are the explicit `dotfiles-private/headless.refs` allowlist.
- **Fail-soft, monitored.** The `command` source can't abort startup; it degrades to "no secrets
  applied" + a warning. `hermes-liveness.sh` covers both halves — total failure via
  `platforms.slack.state == "connected"`, partial via `KEY=` count vs rendered count.
- Manual check: `Command helper: applied 29 secrets` in `hermes gateway status`, `✓ secrets (29
  refs …)` from `make status`.
- **Never run `hermes model` on the mini** — it writes a plaintext `~/.hermes/.env`
  (`save_env_value`) that duplicates two `.env.tpl` names on the same op ref; deleted 2026-09-07,
  and `hermes-backup.sh` excludes it so a recreated one never reaches homelab.
- **launchd works** — `ai.hermes.gateway` is genuinely supervised. The plist is stock (wraps
  `venv/bin/python -m hermes_cli.main gateway run --external-supervisor` in
  `hermes_cli.stderr_timestamp`), so `hermes gateway install` is a no-op; its `Bootstrap failed: 5`
  output is noise — check `gateway status`.

Rationale + what this replaced: **`docs/secrets-command.md`**.

## Gateway HTTP Exposure (argo dashboard chat)

The gateway runs an OpenAI-compatible HTTP API alongside Slack so the **argo VPS dashboard
chat** can reach Hermes. Four env vars (framework keys in `hermes_cli/config.py`), resolved at
startup from `.env.tpl` via `secrets.command`:

| Var | Value |
|-|-|
| `API_SERVER_ENABLED` / `API_SERVER_PORT` | `true` / `8642` — literals |
| `API_SERVER_HOST` | the mini's Tailscale IP — **tailnet-only bind**, no LAN listener. `op://hermes/gateway/host` (never a literal in git) |
| `API_SERVER_KEY` | bearer gating **every** request, even loopback. `op://hermes/gateway/api-server-key` |

**`API_SERVER_KEY` must equal argo's `HERMES_API_KEY`** (mirrored op items) — rotate both, then
`ssh vps "cd ~/vps && ENV=prod make argo-env && ENV=prod make argo-up"` (no gateway restart, only
argo redeploys). Mismatch = **401**; connection-refused = not bound to the tailnet IP. Verify
from the VPS, rotation steps, network path: **`docs/gateway-http-api.md`**.

## Homelab API Integration

`skills/argo-api/SKILL.md` endpoint tables are regenerated from
`https://argo.jkrumm.com/api/openapi/json` by the homelab `/docs` skill. The spec's **14 tags**
split three ways: **personal** (`argo-api`) — Garmin Health, Strength, WalkingPad, Productivity,
Infrastructure, External Data, Reading, Usage Tracking, System; **work** (`work` skill) — M365,
Atlassian, GitLab; **not agent-facing** — Hermes Chat (`/hermes/*`) + AI Gateway (`/ai/v1/*`).
`/reading/*` is the standalone `reading` skill. **API secret:** `op://common/api/SECRET`
(account `tkrumm`), in `.env.tpl`.

**`work` skill = read-only across M365/Confluence/GitLab, with one write exception: Jira**
(create/update/transition/comment on Johannes's own tickets, Team=Prometheus auto-stamped —
never Teams messages, mail, Confluence pages, MRs, or speaking for teammates). **Briefings carry
exactly three work signals** — today's Outlook calendar, Jira sprint commitments, GitLab MRs
needing action; everything else (chats, Confluence, WalkingPad, `/usage/*`) is ad-hoc only, never
in briefings or the watchdog. Errors: `503 M365 not authenticated` → `bun m365:auth:prod` in
`~/SourceRoot/argo`; `503` on `/gitlab/*`/`/atlassian/*` → PAT expired. Full taxonomy
(garmin-health vs strength split, MR↔Jira linking): **`docs/argo-surface.md`**.

## Research (research-gateway)

Deep cited research is the standalone **research-gateway** (`research.jkrumm.com`, VPS,
**Tailscale-only**), used through `skills/research-gateway/SKILL.md` via `terminal`:
`POST /research/ {query, depth?}` → `{jobId}`, poll `GET /research/{jobId}` until `status: done`
→ `{result: {report, citations[], sources[]}}`. Async because even `quick` runs 1–3 min.
**Preferred path for substantive / factual / library-version questions** over built-in Tavily
search, which stays for quick lookups. EU/IU models, off Max.

- **Auth:** `RESEARCH_API_KEY` = `op://vps/research-gateway/API_SECRET` (shared with the Claude
  Code `/research` skill), in `.env.tpl`; base URL hardcoded in the skill, like argo/karakeep.
- **Routing (SOUL.md):** "research X now" → `research-gateway`; "remind me to research X later"
  → `capture` → TickTick; book/novel discovery → `reading`.
- **Named `research-gateway`, not `research`** — upstream's bundled skill *category* dir
  `~/.hermes/skills/research/` would collide with a top-level `research` symlink. Routing is by
  description/tags, so "recherchier mal" still triggers it.
- Its host is in both allowlist patches (`tirith-hermes-guards`, `cronjob-tools-allowlist-argo-bearer`).

## Observability triage (hyperdx)

`skills/hyperdx/SKILL.md` gives Hermes an authenticated path into ClickHouse instead of a browser
login wall. HyperDX/ClickStack is **VPS-only** (`hyperdx.jkrumm.com`, Tailscale-only), exposing a
stateless JSON-RPC/SSE MCP server at `/api/mcp` — the same server sideclaw's `otel` tool uses,
same credential (`HYPERDX_AGENT_ACCESS_KEY` ← `op://vps/clickstack/AGENT_ACCESS_KEY`). One
verified curl template (`clickstack_sql` against `default.otel_traces`/`otel_logs`/
`otel_metrics_*`) plus the SQL behind each of the three live alerts
(`vps/observability/alerts/*.json`), so a triage re-runs the condition that fired. Escalation
reuses the dispatch bridge (`--tier author` to file, `implement` after confirmation) except a
root cause inside Traefik/ClickStack config itself, which is `vps`'s `investigate`-only ceiling
— falls back to `capture` → `gh issue create` there. No ClickHouse HTTP on the tailnet; all
querying goes via HyperDX's MCP/REST. Its host is in both allowlist patches (see *Local
Modifications*).

## Podcast generation (podcast)

`skills/podcast/SKILL.md` turns notes into a long-form two-host German episode via a **job API on
the audio-gateway** (same VPS/tailnet service as TTS/STT) and publishes the MP3 (chapters + cover)
into Audiobookshelf. Submit-and-poll like `research-gateway`, **not** a single `/v1/audio/speech`
call like `briefing-tts`. **No secret** — tailnet-gated, caller identified by the bearer label
`hermes`. SOUL.md's TTS rule 4 ("NEVER curl an audio endpoint") exempts `/v1/podcasts*` — there is
no native tool for this pipeline.

## Agents overview (agents)

Read-only cross-project Claude Code/herdr status via sideclaw's `/api/overview` —
conversational skill (`skills/agents/SKILL.md`), a scheduled Slack digest and a
morning-briefing feed (`scripts/agents-overview.py`). Never dispatches, never
steers a pane — that's `claude-dispatch`. **`docs/agents-overview.md`**.

## Project narratives (project-narratives)

Daily vault pages, one per active repo, written by sideclaw's `narrative` job
(same daemon as `agents`) into `wiki/engineering/projects/<project>.md` — what
a project is, where it stands, how it got there. Less is more: a project with
no substantive change gets no revision and no mention, gated by a pure
`needs_revision()` (HEAD moved or a newer Claude Code transcript) before any
model call. `scripts/project-narratives.py --run` is the cron entry (job `9909f808fe17`, daily 06:30,
via `narratives-cron.py`); `--bootstrap a,b,c` writes for human review without committing. It
takes brain-sync's `mkdir` lock around add/commit, pushes (fail-soft), and POSTs each written
page to Argo `/api/agents/narratives` (best-effort, a 404 is non-fatal).
Every commit names the vault (`git -C ~/SourceRoot/brain …`), the sole
exemption in the `raw_repo_write` guard (`docs/guards.md`). **`docs/project-narratives.md`**.

## Second Brain (Obsidian + KaraKeep)

Two skills, deliberately distinct roles — don't blur them:

- **`obsidian`** — the **source of truth**: read/search/write the PARA vault at
  `~/SourceRoot/brain/`, also a git repo shared with Claude Code (`/brain`). A LaunchAgent
  pulls+pushes every 5 min; **on this mini it never auto-commits, so a write isn't durable until
  committed**. **CLI-first** (`obsidian-cli` through the running app's API), filesystem fallback
  when Obsidian is down. No secret. Two layers: strict atomic English concept notes in `wiki/`,
  light curated `Projects`/`Areas` linking *down* into it. Contract: `~/SourceRoot/brain/AGENTS.md`.
- **`karakeep`** — the **read-later bucket**: REST on `https://karakeep.jkrumm.com/api/v1`
  (Bearer `$KARAKEEP_API_KEY`, Tailscale-only). Links/text, full-text search, lists, tags,
  highlights, async AI auto-tagging.

**Routing** (`capture` is the router): KaraKeep = reference/reading you consume · Obsidian =
durable knowledge you author · TickTick = human action · GitHub = code change.

**Bundled-skill collision:** upstream's stock `obsidian` skill was removed from
`~/.hermes/skills/note-taking/obsidian/` so ours is canonical, and it **re-seeds on `hermes
update`** — `/hermes-update` carries the `rm -rf` step. **Kobo/e-reader (not built):** reading
vault notes on the Kobo via KOReader would use Readeck (bidirectional highlight sync via
`iceyear/readeck.koplugin`), not KaraKeep (save-only) or Wallabag (no sync-back) — a homelab
container + a new `readeck` skill pushing curated content and pulling highlights back, nothing
scheduled.

## Wild Rift (champion pool tracker)

`skills/wildrift/SKILL.md` maintains the **eleven-champion pool** across jungle, support, mid and
baron. **Vault-first:** builds, runes, matchups, bans and a dated stats snapshot live at
`~/SourceRoot/brain/Areas/Gaming/Wild Rift/*.md` (curated surface, not `wiki/`); the open web
via `research-gateway` only *refreshes* a note when a patch moved. No secret, no external API.
Writes use the `obsidian` CLI-first contract and the `git -C ~/SourceRoot/brain …` exemption
(never push — the LaunchAgent syncs).

**Never a build site directly** — no Riot/Tencent/build-site host is trusted by tirith or the
cron scanner, so every fetch routes through `research-gateway`. **Stats are China-server only**
and swing hard by rank tier (0-4 — Hecarim ~45% WR at tier 0 vs ~53.7% at tier 4): qualify every
answer by rank. An Argo `/wildrift/*` group is **built but not deployed**; the skill tells the
agent not to call it.

## Local Modifications to Upstream

Re-apply after `hermes update`: **one `.patch` file per patched upstream file**, each with `git
apply --3way` (`/hermes-update` carries the loop). `ls patches/` is the count, `make patch-check`
proves they are applied — deliberately not restated here (it drifted repeatedly). Baseline
**v0.21.0**, upstream `d8a07768c5`.

**2026-09-07 — every patch moved file.** Upstream landed 5503 commits in six days under an
unchanged version number, splitting every monolith apart. The **patch names are unchanged**
(identifiers cited by `# LOCAL MODIFICATION (patches/<name>.patch)` markers), so three now name a
file they no longer touch — read the table's left column, not the patch name.

| Upstream file | `patches/…` | What it does |
|-|-|-|
| `tools/tts_tool_openai.py` + `tools/tts_tool.py` | `tts-tool-audio-title` | name saved audio from the gateway's `X-Audio-Title` header instead of `tts_<timestamp>.mp3` |
| `gateway/run_voice.py` | `gateway-auto-tts-voice-only` | auto-TTS answers **voice input only**, so alerts stop coming back as MP3s. `/voice all` per chat still speaks everything |
| `hermes_cli/web_routers/audio.py` | `serve-speak-summary` | Desktop relay read-aloud summarization. **Dormant** — the relay it serves was torn down 2026-09-07, kept applied |
| `plugins/platforms/slack/adapter.py` | `slack-cannot-reply-to-message` | mrkdwn normalization + `cannot_reply_to_message` retry (drop `thread_ts`, retry flat) |
| `gateway/platforms/base.py` | `slack-media-inline-reply-anchor` | pass the text reply's anchor to media senders. **Dormant** under `reply_in_thread: true`, kept applied |
| `agent/client_lifecycle.py` | `run-agent-third-party-endpoint-token-refresh` | stop `~/.claude/.credentials.json` OAuth replacing the IU key. **Dormant**, kept applied |
| `tools/tirith_security.py` | `tirith-hermes-guards` | four guard rules, below |
| `tools/cronjob_prompt_scan.py` | `cronjob-tools-allowlist-argo-bearer` | argo/karakeep/research/hyperdx/audio-gateway bearer allowlist so a legitimate cron curl stops tripping `exfil_curl_auth_header` |
| `hermes_cli/runtime_provider.py` | `runtime-provider-iu-responses-api` | route the IU `…/openai/v1` leg onto `codex_responses` — **the only way to run a reasoning effort here** |
| `agent/transports/chat_completions.py` | `transport-iu-reasoning-effort` | drop `reasoning_effort` on a gpt-5.x request carrying function tools; clamp `xhigh`/`max` → `high` for the Anthropic fallback |

Re-apply: `cd ~/.hermes/hermes-agent && git apply ~/SourceRoot/hermes-agent/patches/<name>.patch`.
**Anything touching `tirith_security.py`, `cronjob_prompt_scan.py` or `runtime_provider.py`
needs a gateway restart** (`launchctl kickstart -k gui/$(id -u)/ai.hermes.gateway`) — modules are
imported once at startup.

**Four guard rules in `tirith-hermes-guards.patch`**: trusted-pipeline allowlist (argo/karakeep/
research/hyperdx/audio-gateway hosts only), `download_then_execute` (blocks the two-step
`curl -o f && sh f` form tirith itself misses), `raw_agent_invocation` (blocks Hermes composing
its own `claude`/`rd bg|work`/`agent-dispatch`/`herdr agent …` call), `raw_repo_write` (blocks
editing a repo instead of dispatching — two exemptions: GitHub issues, and the brain vault when
the command names it). All three write/execution guards share **one tokenizer bug history** — a
newline inside `shlex.whitespace_split` let a multi-line command scan only its first line,
exploited twice before every guard moved `\n`/`\r` into `punctuation_chars`. Rules, current test
counts, the full incident record: **`docs/guards.md`**.

**Slack threading is a context-window boundary.** `slack.reply_in_thread: true` makes
`build_session_key()` append `thread_ts` whenever `source.thread_id` is set, so **one thread ==
one session == one context window**. Continue a topic *inside* its thread; a new top-level
message is deliberately a clean slate.

Per-file detail, every retired patch and why, the v0.18.x platform rewrite: **`docs/patches.md`**.

## Model, context window and reasoning effort

Numbers are **probed against the live IU endpoint**, not read off a model card — every
published source disagrees in some direction. Re-probe after an endpoint change.

| | Value | How established |
|-|-|-|
| Input cap, `gpt-5.6-luna` | **922,000** | 900k ok; 1.1M → `context_length_exceeded` (a *combined* input+reasoning+output budget) |
| `/v1/models` metadata | `ContextSize: "105000"` | **Wrong** — 110k/260k/520k/900k all succeed. Never configure from it |
| `claude-sonnet-4-6-eu` | ≥300,000 proven | config sits at 300,000; metadata claims 1M, untested above |
| Efforts, gpt-5.6 family | `none, low, medium, high, xhigh` | `max` refused here; `minimal` isn't a gpt-5.6 value |
| Efforts, Anthropic leg | `none, low, medium, high` | `xhigh` refused by the IU LiteLLM gateway |

**Reasoning effort only exists on the Responses API here.** `/v1/chat/completions` refuses any
effort once the request carries function tools — and Hermes always sends tools, so the effort
400s **every** turn and lands the conversation on the Anthropic fallback while looking healthy.
Hence `model.api_mode: codex_responses` + the runtime-provider patch. **Tell:** `Fallback
activated: gpt-5.6-luna → claude-sonnet-4-6-eu` every turn in `~/.hermes/logs/agent.log`, with
`Ignoring persisted custom api_mode=codex_responses for non-OpenAI endpoint` one line above —
that second line means the patch fell off, which is what a `hermes update` does.

- **`agent.log` is not rotated per process** — slice every read at the current process start
  (`pgrep -f "hermes_cli.main gateway run"` → `ps -o lstart=`). `skills/hermes-gateway/` owns
  this. **Hermes may not restart its own gateway.**
- **The live key is `agent.reasoning_effort`, not `model.reasoning_effort`.**
- **The Anthropic fallback shares this base URL and must not follow it onto Responses** — an
  explicit `api_mode` on a `fallback_providers` entry wins over URL detection.
- **Compaction triggers at 240,000 tokens** (absolute — the *lower* of ratio and absolute
  governs). A window **under 512K** floors its threshold at **0.75**, and the auxiliary
  compression model's own `context_length` clamps the trigger to itself — hence
  `auxiliary.compression.context_length: 850000`, not the default 200,000.

**Auxiliary lanes are separately routed, not the brain** — `title_generation` and `approval` are
pinned off a flash/haiku model (the flagship 503s on their hardcoded `temperature`); `approval`
runs the **native `/anthropic` leg**, 0.9s vs 3.0s through the OpenAI-compat shim, `provider`
stays `custom` so it never reaches for `~/.claude` OAuth. **`delegation.*` (subagent routing)
exists but is unused** — a Hermes child gets no `.claude/rules`/`skills`/PR artifact, so repo work
stays on the dispatch bridge. **Core-tool deferral is on** (`tools.tool_search.enabled: auto`) —
measured −19.8% off the cached tool prefix every turn; if Hermes ever claims it can't schedule
something, check `cronjob_manage` isn't wrongly deferred rather than disabling the feature.

Full numbers, lane rationale, deferral measurement: **`docs/model-context-reasoning.md`**.

## Shell script conventions

**Under `set -euo pipefail`, any `$(producer | head -c N)` substitution dies with SIGPIPE (141)
once `producer` exceeds `N` bytes** — `head` closes the pipe, `pipefail` makes the substitution
non-zero, `set -e` ends the script, and the crash happens before the first `echo` so there is no
log line. Guard **inside** the substitution: `$(git diff --cached | head -c 20000 || true)`. Any
new script piping an unbounded producer into `head -c`/`tail -c` under `pipefail` needs it.
The incident it came from: **`docs/shell-conventions.md`**.

## Setup

```bash
make setup        # idempotent — symlinks, LaunchAgents, CC skills
make status       # verify all of it
make patch-check  # assert every patches/*.patch is applied to the live checkout
```

Prerequisites: `hermes` CLI installed, `audio-gateway` reachable, 1Password CLI authenticated as
`tkrumm`. `make help` lists the rest.

## Editing Rules

**Adding a Hermes skill:** create `skills/{name}/SKILL.md`, add `{name}` to `HERMES_SKILLS`, run
`make setup`, then **restart the gateway** — the skills-index system prompt is cached
**in-process** and nothing but a restart or `skill_manager_tool` clears it, so `hermes skills
list` shows a new skill the running gateway still can't see.

**Renaming or retiring a skill fails silently** — a cron job preloads skills *by name*, an
unresolvable one logs `skill not found, skipping` at WARNING and the job still reports `ok`.
`make status` asserts every skill in `~/.hermes/cron/jobs.json` resolves — run it after any
rename.

**`cron/jobs.json` is gitignored runtime state carrying its own copy of the prompt** — editing
`cron/*.prompt.txt` alone changes nothing at runtime. Push through the CLI:
`hermes cron edit <job_id> --prompt "$(cat cron/morning-briefing.prompt.txt)" --skill a --skill b`
(`--clear-skills` applied after `--skill` wins — pass `--skill` alone to replace a set).
`hermes cron run <job_id>` has **no dry-run and delivers for real** — retarget first
(`--deliver slack:<test-channel>`), then restore. Detail: **`docs/scheduled-jobs.md`**.

**Adding a CC slash command:** create `.claude/skills/{name}/SKILL.md` — auto-loaded here, no
symlink or Makefile change. **Patches:** save the diff under `patches/`, add a table row in
*Local Modifications*, put per-file detail in `docs/patches.md`.
