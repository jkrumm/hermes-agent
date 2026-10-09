# hermes-agent — Hermes Agent Instructions

Commands, tables and gotchas — dense reference for every session. Full rationale, incident
history and per-file detail live in `docs/*.md`; each section here points at its own.

## What This Repo Is

VCS source of truth for Johannes's Hermes Agent setup, Mac Mini-only. Everything here is
symlinked into `~/.hermes/` — edit at either end, git sees it here.

**Warden (`~/SourceRoot/warden`) is the control plane this repo hands work to and reads
from.** It ingests signals, decides, dispatches Claude Code episodes through agent-gateway, and
owns the only ledger (`~/.warden/warden.db`) — five LaunchAgents, no LLM call anywhere in its
loop. Hermes has one role — **narrate, answer, route** (spec: `dotfiles/docs/agent-platform.md` §Hermes): it reports one line per item, answers questions, and files work through `warden run` or a GitHub issue; herdr tabs / `rd wave` only when the owner asks. It never dispatches on its own, lands PRs, or authors skills unattended. The reporting contract lives in `SOUL.md` and nowhere else — no per-skill report formats. See *Dispatch
Bridge* below for how Hermes hands it work, and the read-only `warden` skill for how Hermes
reads it back.

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
| `plugins/{name}/` | `~/.hermes/plugins/{name}/` | **`HERMES_PLUGINS`** is the source of truth. **None today** — `dispatch-approval` was removed 2026-10-04 (warden Wave 1 deleted the approval stack). A new one must **also** be enabled once — `hermes plugins enable <name>`; the symlink alone is inert. |
| `config/` | `~/.hermes/config/` | **empty** since 2026-09-10 — `dispatch-repos.json` is gone — the repo/tier policy is agent-gateway's `server/lib/dispatch-policy.ts` (`GET /api/dispatch-policy`) |
| `skills/{name}/` | `~/.hermes/skills/{name}/` | **`HERMES_SKILLS` in the Makefile is the source of truth** — 20 dirs (agent-platform Wave 2, 2026-10-04; was 126). Retired skills live on as `<skill>/references/*.md` or in git history; roster: docs. |
| `USER.md` | `~/.hermes/memories/USER.md` | **copied** — Hermes writes to it |

**Autonomous skill creation is off** (`skills.creation_nudge_interval: 0`); `skills.create_dir` points at `~/.hermes/skills-quarantine`, outside `external_dirs`, so anything Hermes writes anyway is neither live nor tracked until the owner promotes it here. Needs a gateway restart.

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
`crontab -l`. All 4 live `hermes cron` jobs (ids, schedules, delivery) + reasoning:
**`docs/scheduled-jobs.md`**. The watchdog poll and dispatch sweep are LaunchAgents in
`~/SourceRoot/warden` now, not `hermes cron` jobs — see *Alert triage* below.

**Per-repo agent skills** (`.claude/skills/`, committed, no symlink — Claude Code and OpenCode both load them): `/hermes-validate`
(test routing, fix SOUL.md / SKILL.md) · `/hermes-update` (pull upstream, re-apply patches,
restart gateway).

## Dispatch Bridge — handing repo work to Warden

Hermes observes well and reads repos badly — an LLM with a `terminal` tool cannot use a
repo's `AGENTS.md`/`CLAUDE.md`, `.claude/rules/` or `.claude/skills/`. So repo work is **filed,
not done**: `scripts/hermes-cc.sh` here (= `~/.hermes/scripts/hermes-cc.sh`) is a 6-line exec shim
into `~/SourceRoot/warden/scripts/warden`, and the `dispatch` skill documents the one verb Hermes
uses — **`hermes-cc.sh run <repo>`** (brief on stdin, quoted heredoc, never argv). `run` opens a
Warden item that rides its own lifecycle (investigate → implement → review → merge → deploy →
verify). Hermes does not land PRs, `gh pr merge`, pick a tier, or start a `claude` session.
Reading an item back (`/board`, `/items/:id` on warden's loopback API) is the read-only `warden`
skill — never the ledger file, never a guess. Design: `~/SourceRoot/warden/DESIGN.md`;
the door: **`docs/dispatch-bridge.md`**.

**One door per verb:** repo work → `hermes-cc.sh run`; status → `warden` skill (HTTP API); panes /
long visible work → `herdr` + `rd` (`rd wave`, never `claude --bg` / `claude -p`); issues → `capture`.

**No signed approval.** Warden Wave 1 (2026-10-04) deleted the approval stack, so the
`dispatch-approval` plugin (Ed25519 signer, Approve/Deny buttons) was removed here. agent-gateway's repo
policy is the only boundary; budgets and the brief secret scan (refuses, never redacts) remain.
Config of `plugins:` is empty; `HERMES_PLUGINS` in the Makefile is empty.

**`slack.allow_bots: all` is deliberate — do not "fix" it.** The trust boundary is the
workspace, not human-vs-bot: HomeLab/VPS/Argo post from inside the tailnet and live `#alerts`
auto-triage depends on it. `require_mention_channels` silences `#media`/`#updates`/`#alerts`/`#agents` (pure-echo
channels; in `#agents` Hermes answers only when mentioned, so it never replies to warden's posts) — inbound-only, `hermes send`/cron/dispatch verdicts still post there.

**Tests** (`~/.hermes/hermes-agent/venv/bin/python3`): `test_cron_allowlist.py`. `test_hermes_cc.py` moved to
`warden/tests/test_warden_cli.py` (black-box against the real `warden` CLI, stubbed agent-gateway +
GitHub + Slack) with `hermes-cc.sh` itself (2026-09-10); run it with warden's own venv (`make test`
from `warden/`). The other
half is `agent-gateway/tests/` (`bun test`, mutation-verified — worktree isolation, the
diff-refusal ladder, the secret scan, the nonce fence around the brief).

**Hermes cron pre-run scripts** (run by `hermes-agent` before each run, not launchd):
`briefing-context.py`/`briefing-coverage.py` feed the morning briefing (TickTick + GitHub
coverage) — the former also reaches across to warden's `watchdog-summary.py`
(`WARDEN_WATCHDOG_SUMMARY`-overridable) for the briefing's Infrastructure section.
`narratives-cron.py` is the same thin-loader shape for `project-narratives.py`.

**`hermes cron create --script` rejects any substantial script** (`cron/lifecycle_guard.py`
fails closed on an exhausted recursion budget) — keep entry points thin, logic in an imported
module. Detail: **`docs/scheduled-jobs.md`**.

## Herdr — the interactive lane Hermes may drive

**Warden is the background lane; herdr is Johannes's own visible workspace, and
Hermes may drive it on his explicit request.** The `herdr` skill
(`skills/herdr/SKILL.md`) is the door: open a tab/pane in a repo workspace, run a
command, read a pane back, start an interactive Claude Code session with the
dotfiles launchers (`c`/`cf`/`cs`, typed into the pane's zsh — `herdr agent start`
uses herdr's own bare `claude` and loses the house flags), prompt it, steer it.

Every herdr verb is allowed. The command guard that once blocked agent-starting herdr verbs
produced the failure it existed to prevent — asked to "open a herdr pane in warden with `cf`",
Hermes was refused, silently substituted a Warden dispatch and reported success for work never
asked for. That guard is gone (see *No approval prompts, no command guards* below); lane choice
is SOUL.md guidance.

Hermes runs **outside** any pane: no `HERDR_ENV`, no `$HERDR_PANE_ID`, so the skill
forbids `--current` and focus-dependent targeting and requires explicit
`w1E` / `w1E:t9` / `w1E:p4` ids. Two gotchas baked into the skill: `pane read`
returns **plain text, not JSON** (don't pipe it to `jq`), and the terminal tool's
180 s timeout means `agent prompt --wait` above ~150000 ms kills the call, not the
agent — prompt without waiting, then poll `agent get`.

## Alert triage

**Moved to `~/SourceRoot/warden` 2026-09-09.** `triage.py` (LaunchAgent
`com.jkrumm.warden-loop`, 10 min) is the deterministic act-loop over
`~/.warden/warden.db` that turns deduplicated watchdog events into items and drives them to `fixed`
(implement at any confidence; review is the gate), with one Slack line per
`fixed`/`needs_decision` item. It reaches back into this repo
through `scripts/hermes-cc.sh` (an exec shim into the `warden` CLI) — see
*Dispatch Bridge* above. Full state machine
and why the loop is a LaunchAgent rather than a `hermes cron` job:
`~/SourceRoot/warden/AGENTS.md`, `DESIGN.md`, `STATE.md`.

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
`export K='V'` while the bulk parser wants `K=V`. 0.29s for 29 refs (28 since 2026-09-14) (default budget 3s), and
secrets resolve for **every** hermes invocation — gateway, CLI, cron.

- **Not `secrets.onepassword`**: it needs an interactive `op` session (hangs headless) or a
  standing `OP_SERVICE_ACCOUNT_TOKEN` (a live credential on an always-on box). The sealed cache
  is strictly stronger — its contents are the explicit `dotfiles-private/headless.refs` allowlist.
- **Fail-soft, monitored.** The `command` source can't abort startup; it degrades to "no secrets
  applied" + a warning. `hermes-liveness.sh` covers both halves — total failure via
  `platforms.slack.state == "connected"`, partial via `KEY=` count vs rendered count.
- Manual check: `Command helper: applied 28 secrets` in `hermes gateway status`, `✓ secrets (28
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

Deep cited research is the standalone **research-gateway** (`research.mini.jkrumm.com`, on the
mini as a native LaunchAgent — the only instance, the VPS container is retired, **Tailscale-only**),
used through `skills/research-gateway/SKILL.md` via `terminal`:
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
- Its host is in the cron scanner allowlist patch (`cronjob-tools-allowlist-argo-bearer`).

## Observability triage (hyperdx)

`skills/hyperdx/SKILL.md` gives Hermes an authenticated path into ClickHouse instead of a browser
login wall. HyperDX/ClickStack is **VPS-only** (`hyperdx.jkrumm.com`, Tailscale-only), exposing a
stateless JSON-RPC/SSE MCP server at `/api/mcp` — the same server agent-gateway's `otel` tool uses,
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

Read-only cross-project Claude Code/herdr status via agent-gateway's `/api/overview` —
conversational skill (`skills/warden/references/agents.md`) and a morning-briefing feed
(`scripts/agents-overview.py`). Never dispatches, never steers a pane — that's
`dispatch`. **`docs/agents-overview.md`**.

## Project narratives (project-narratives)

Daily vault pages, one per active repo, written by agent-gateway's `narrative` job
(same daemon as `agents`) into `wiki/engineering/projects/<project>.md` — what
a project is, where it stands, how it got there. Less is more: a project with
no substantive change gets no revision and no mention, gated by a pure
`needs_revision()` (HEAD moved or a newer Claude Code transcript) before any
model call. `scripts/project-narratives.py --run` is the cron entry (job `9909f808fe17`, daily 06:30,
via `narratives-cron.py`); `--bootstrap a,b,c` writes for human review without committing. It
takes brain-sync's `mkdir` lock around add/commit, pushes (fail-soft), and POSTs each written
page to Argo `/api/agents/narratives` (best-effort, a 404 is non-fatal).
Every commit names the vault (`git -C ~/SourceRoot/brain …`). **`docs/project-narratives.md`**.

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
Writes use the `obsidian` CLI-first contract and `git -C ~/SourceRoot/brain …`
(never push — the LaunchAgent syncs).

**Web facts go through `research-gateway`** — build sites are JS-heavy and contradict each
other; the gateway cross-verifies. **Stats are China-server only**
and swing hard by rank tier (0-4 — Hecarim ~45% WR at tier 0 vs ~53.7% at tier 4): qualify every
answer by rank. An Argo `/wildrift/*` group is **built but not deployed**; the skill tells the
agent not to call it.

## Local Modifications to Upstream

Re-apply after `hermes update`: **one `.patch` file per patched upstream file**, each with `git
apply --3way` (`/hermes-update` carries the loop). `ls patches/` is the count, `make patch-check`
proves they are applied — deliberately not restated here (it drifted repeatedly). Baseline
**v0.21.5** (tag v2026.9.24), upstream `f97608f178`.

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
| `tools/cronjob_prompt_scan.py` | `cronjob-tools-allowlist-argo-bearer` | argo/karakeep/research/hyperdx/audio-gateway bearer allowlist so a legitimate cron curl stops tripping `exfil_curl_auth_header` |
| `hermes_cli/runtime_provider.py` | `runtime-provider-iu-responses-api` | route the IU `…/openai/v1` leg onto `codex_responses` for any gpt-5.x model with no explicit `api_mode` — **dormant on the current config**, every live slot sets `api_mode` explicitly |
| `agent/transports/chat_completions.py` | `transport-iu-reasoning-effort` | deny-by-default tools+`reasoning_effort`: keep both only for the probed-safe allowlist (Anthropic/DeepSeek/GLM); strip for everything else, gpt-5.x and any unrecognized model id included; clamp per model family (Anthropic: no `xhigh`; GLM: no `medium`; unrecognized: omitted entirely) |
| `run_agent.py` | `run-agent-iu-max-completion-tokens` | always send `max_completion_tokens` (never `max_tokens`) on the IU OpenAI leg, regardless of which model-id prefix is behind it — `model_forces_max_completion_tokens` only recognizes OpenAI ids, so a non-OpenAI custom-provider model (DeepSeek) fell through to the rejected key |
| `agent/auxiliary_client.py` | `auxiliary-client-iu-openai-leg-quirks` | always `max_completion_tokens` on the IU OpenAI leg, covering every call site of `auxiliary_max_tokens_param` (compression/title/vision, the fast-lane cap via `_build_call_kwargs`, the credit-limited-402 retry, the same-provider fallback rebuild), and move `extra_body.reasoning` to a clamped top-level `reasoning_effort` there. The gpt-5.x `temperature` strip was retired at v0.21.4 — upstream's `_is_openai_default_temperature_only` now omits it on every endpoint |
| `gateway/run.py` | `gateway-start-predecessor-grace` | non-`--replace` startup (launchd KeepAlive) gets a 20s/1s poll grace for a still-dying predecessor PID before refusing — continues (clearing stale PID/lock like `--replace` does) if it exits, refuses as before if it doesn't. Never signals the target |
| `tools/skill_manager_tool.py` | `skill-manager-colon-hint` | `_validate_frontmatter` stays fail-closed on a YAML `ScannerError`, but appends a hint when the message is "mapping values are not allowed here" — an unquoted `key: value: with-a-colon` description |
| `tools/checkpoint_manager.py` | `checkpoint-store-integrity` | four fixes in the shared shadow store, one file: (1) `_take()`'s `git add -A` retries once on **any** transient failure — a stale gitlink (drop the dead gitlinks, `update-index --force-remove`) *and* a file deleted mid-walk by another process (`unable to stat …: No such file or directory`, the Claude Code scratch race); (2) `info/exclude` is rewritten from `DEFAULT_EXCLUDES` whenever it has moved on, and tracked paths the store's own exclude file matches are force-removed — a path committed *before* its pattern existed survives `_seed_project_index`'s read-tree forever otherwise (`claude-501/` sat at 1925 tracked paths / ~32 MB in the `/tmp` ref while nominally excluded); (3) one reentrant `_STORE_LOCK` over every store-touching git call **and** a cross-process file lock on the store, so a snapshot cannot be pruned by a concurrent `gc --prune=now` between `add -A` and `write-tree` (a per-project index is not a gc reachability root) and two *processes* snapshotting the same project cannot collide on git's own `indexes/<hash>.lock`; (4) the logged stderr keeps its first line verbatim (Warden's signature) but is summarized, and the retry quotes the real cause — `add -A` prints advice before the error, so a commitless nested repo was filed as an innocent `Füge eingebettetes Repository hinzu: …` |
| `agent/anthropic_adapter.py` | `anthropic-adapter-haiku-5` | `_thinking_kwargs` returned `{}` for any id containing `haiku`, so `claude-haiku-5-5-eu` got no `output_config.effort` and silently ran at the API default (medium). Narrowed to legacy Haikus (3.x/4.x) + non-Claude ids; 5.x reaches the adaptive branch |
| `agent/chat_completion_helpers.py` | `stream-error-transient-openai-classes` | `_StreamingCall._handle_stream_error` classified transients against raw httpx types only, so `openai.APITimeoutError`/`openai.APIConnectionError` missed the transient set and a blip the retry loop heals anyway logged at ERROR with a full traceback (the `hermes_log:*` card family; issue #4). Adds both classes to `_is_timeout`/`_is_conn_err` — the same classification `agent/error_classifier._TRANSPORT_ERROR_TYPES` and `agent/agent_runtime_helpers._TRANSIENT_TRANSPORT_ERRORS` already apply |

Re-apply: `cd ~/.hermes/hermes-agent && git apply ~/SourceRoot/hermes-agent/patches/<name>.patch`.
**Anything touching `cronjob_prompt_scan.py`, `runtime_provider.py`,
`agent/transports/chat_completions.py`, `run_agent.py`, `agent/auxiliary_client.py`,
`agent/chat_completion_helpers.py`, `agent/anthropic_adapter.py` or
`config.yaml` needs a gateway restart** (`launchctl kickstart -k gui/$(id -u)/ai.hermes.gateway`)
— modules are imported once at startup and `config.yaml` is read at startup too: a running
process serves whatever model/patch state it started with, regardless of what `config.yaml` or
these patched files say on disk. The 2026-10-08 brain switch (`claude-haiku-5-5-eu` on
`anthropic_messages`) is live — gateway restarted that day.

**No approval prompts, no command guards (owner decision 2026-09-14) — do not re-add either.**
Hermes runs like Claude Code with `--dangerously-skip-permissions` and is steered by
**guidance, not gates**: SOUL.md *How you get things done* + the skills. `approvals.mode: 'off'`
(`smart` turned flagged commands into Slack Approve buttons that stalled the turn 300 s and
failed closed), cron/`-q`/unattended `approve`, `security.tirith_enabled: false`,
`security.protected_instruction_files: false`. The local `tirith-hermes-guards` patch
(pipeline allowlist, `download_then_execute`, `raw_agent_invocation`, `raw_repo_write`) was
**deleted** with its tests — it produced friction and silent lane substitutions, not safety.
Still blocking: upstream's hardline floor, the gateway-self-restart block, three irreversible
`approvals.deny` globs, and Warden's own dispatch policy (in `~/SourceRoot/warden`). `make
status` grades the config. **When Hermes does the wrong thing, fix SOUL.md or the skill** — make
the guidance clearer; never answer with a new block.

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
| Brain, `claude-haiku-5-5-eu` (2026-10-08) | Bedrock eu-west-1, native `/anthropic` leg, `anthropic_messages`, `high` | modelpick bench: `high` 15/15 ~1.6 s; `medium` 14/15; `xhigh`/`max` think 50–100 s+. Not in `/v1/models`. Price doubles+ above 100k input (see `docs/model-context-reasoning.md`) |
| Context, `deepseek-v4.1-flash` (former brain and compression; no longer routed) | **1,000,000** | probed 2026-09-13; `/responses` 404s ("No suitable backend") despite `/models` listing it — `chat_completions` is the only wire that works |
| Input cap, `gpt-5.6-luna` (former fallback, title) | **922,000** | 900k ok; 1.1M → `context_length_exceeded` (a *combined* input+reasoning+output budget). **Not re-probed for `gpt-6-luna`** — config keeps 850,000 |
| `/v1/models` metadata | `ContextSize: "105000"` | **Wrong** — 110k/260k/520k/900k all succeed. Never configure from it |
| Efforts, gpt-5.6 family | `none, low, medium, high, xhigh` | `max` refused here; `minimal` isn't a gpt-5.6 value |
| Efforts, `gpt-6-luna` (fallback, title) | `none, low, medium, high, xhigh` | probed 2026-09-23; `max` refused, only default `temperature` (1); with tools it needs an **explicit** `none` — omitting the key 503s too, unlike gpt-5.6 |
| Efforts, deepseek-v4.1-flash (no longer routed) | `low, high, xhigh, max` | accepts tools + effort together on `chat_completions` — unlike gpt-5.x, no strip needed |
| Efforts, Anthropic leg | `none, low, medium, high` | `xhigh` refused by the IU LiteLLM gateway |

**The brain runs `anthropic_messages` (Haiku 5.5 EU) and gets its effort every turn via
`patches/anthropic-adapter-haiku-5.patch`; the Responses dance was a gpt-5.x-only problem
(DeepSeek, no longer routed anywhere, never needed it).** `/v1/chat/completions` refuses any effort on gpt-5.x once the request
carries function tools — and Hermes always sends tools — but DeepSeek takes tools and
`reasoning_effort` together on the same wire with no such refusal (probed 2026-09-13). So the
brain needs no Responses routing at all: `model.api_mode: chat_completions`,
`patches/transport-iu-reasoning-effort.patch` strips the effort for a gpt-5.x model id and
forces an explicit `none` for gpt-6.x (the fallback, `gpt-6-luna`), never touches DeepSeek's. **Tell if the fallback is active:**
`Fallback activated: claude-haiku-5-5-eu → gpt-6-luna` in `~/.hermes/logs/agent.log` — expected
under throttling, not a misconfiguration; the fallback runs with no reasoning effort while tools
are attached (the 503-avoidance tradeoff), which is accepted, not a bug.

- **`agent.log` is not rotated per process** — slice every read at the current process start
  (`pgrep -f "hermes_cli.main gateway run"` → `ps -o lstart=`). `skills/hermes-gateway/` owns
  this. **Hermes may not restart its own gateway.**
- **The live key is `agent.reasoning_effort`, not `model.reasoning_effort`** (the latter was a
  dead, never-read mirror and has been removed from `config.yaml`).
- **`patches/runtime-provider-iu-responses-api.patch` is dormant on the current config** — every
  slot on this endpoint now sets an explicit `api_mode` (`chat_completions`), which always wins
  over the patch's forced host-detection. Kept applied: it is the fallback the moment anything
  here is switched back to a gpt-5.x model with no explicit `api_mode`, and a stale
  `Ignoring persisted custom api_mode=codex_responses for non-OpenAI endpoint` log line still
  means a patch fell off a `hermes update`, not that this one is broken.
- **Compaction triggers at 240,000 tokens** (absolute — the *lower* of ratio and absolute
  governs). A window **under 512K** floors its threshold at **0.75**, and the auxiliary
  compression model's own `context_length` clamps the trigger to itself — hence
  `auxiliary.compression.context_length: 850000`, not the model's real 1,000,000 or the
  default 200,000 (compression is gpt-6-luna; the Haiku brain caches natively).

**Auxiliary lanes are separately routed, not the brain** — `title_generation` (`gpt-6-luna`)
and `approval` (`claude-haiku-5-5-eu`) are pinned off non-brain models because both hardcode a
`temperature` the flagship rejects; upstream's `_is_openai_default_temperature_only` (v0.21.4)
omits `temperature` for any gpt-5.x/o-series id on every endpoint, and the aux patch extends it to gpt-6.x. `approval`
runs the **native `/anthropic` leg**, 0.9s vs 3.0s through the OpenAI-compat shim, `provider`
stays `custom` so it never reaches for `~/.claude` OAuth. `vision` moved off Google AI Studio
direct onto the same IU leg (`gemini-3.5-flash`, EU-resident per the IU catalog) — no documented
reason for the direct route was ever found; see `modelpick/docs/decisions/vision-and-image.md`.
`auxiliary.web_extract` and `auxiliary.session_search` are gone — upstream stopped reading them
(`config_defaults.py`: "no longer use an auxiliary LLM... ignored"), so the blocks were dead
weight. **`delegation.*` (subagent routing) exists but is unused** — a Hermes child gets no
`.claude/rules`/`skills`/PR artifact, so repo work stays on the dispatch bridge. **Core-tool
deferral is on** (`tools.tool_search.enabled: auto`) — measured −19.8% off the cached tool prefix
every turn; if Hermes ever claims it can't schedule something, check `cronjob_manage` isn't
wrongly deferred rather than disabling the feature.

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

## Validate

`make check` — shell syntax (`scripts/*.sh`), `compileall`, `make patch-check`, and every
`tests/test_*.py` run as a script under the Hermes venv (they are standalone, not pytest).
No side effects; non-zero on failure. `tests/test_checkpoint_store_excludes.py` is **not** in
it — its gc / cross-process-lock cases fail intermittently on a clean tree (timing); run it
with `make test-checkpoint` and read the failures before blaming a change.

## Deploy

`make deploy` — the checkout *is* the live config (symlinked into `~/.hermes`), so deploy =
`make setup` + `launchctl kickstart -k gui/$(id -u)/ai.hermes.gateway` + `make verify`
(retried ~1 min while Slack reconnects). On failure it rolls back to `HEAD~1` (detached,
clean tree only), repeats, and exits non-zero either way; return with `git switch master`.
It restarts the gateway, which drops in-flight turns — and **Hermes itself may never run
it** (it may not restart its own gateway). Edits to `SOUL.md` and skills need no deploy
beyond the skills-index restart noted in *Editing Rules*.

## Verify & Monitor

- **`make verify`** — gateway pid alive, `gateway_state.json` slack + api_server
  `connected`, API `/health` 200 on the tailnet bind (`op://hermes/gateway/host`), all patches
  applied. Exit 0 = healthy.
- **Heartbeat:** `hermes-liveness.sh` (300 s LaunchAgent) pushes the Uptime Kuma push monitor
  at `op://hermes/uptime-kuma/agent-push-url`; the backup job has its own
  (`backup-push-url`). A red heartbeat means the gateway, Slack or the secret cache is down.
- **OTel:** none — Hermes emits no traces; `service.name` does not apply.
- **`make logs`** — bounded tail of `gateway.error.log`, `errors.log`, `agent.log`
  (`~/.hermes/logs/`). Slice `agent.log` at the current process start (see *Model, context
  window and reasoning effort*).

## Gotchas

- **Gateway restart is the owner's** (and `make deploy`'s). Changes to `config.yaml`,
  patched upstream files or `SOUL.md`'s cached prompt are not live until it.
- **API sessions are keyed by the first message.** Re-sending an identical test prompt to
  `/v1/chat/completions` resumes the previous session (and its still-running turn) — reword it.
  A smoke that files real work (`hermes-cc.sh run`) opens a real Warden item; close it with
  `warden close <id> --why … --reason ignored`.
- **Repo work goes through `dispatch`, never the repo** — a model told only "you can run
  anything" debugged a flaky agent-gateway test in the live checkout itself (Wave 3 smoke,
  2026-10-04). The routing table in `SOUL.md` is the control; fix wording there, not with a gate.
- Gotchas with their own incident write-up live in the sections above (SIGPIPE under
  `pipefail`, `cron/jobs.json` carrying its own prompt copy, `slack.allow_bots: all`).
