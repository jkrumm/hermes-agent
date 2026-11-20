# hermes-agent — Hermes Agent Instructions

VCS source of truth for Johannes's Hermes Agent setup, Mac Mini-only. Everything here is symlinked into `~/.hermes/` (`make setup`): edit at either end, git sees it here. The checkout is the live config.

Hermes has one role, **narrate, answer, route** (spec: `dotfiles/docs/agent-platform.md` §Hermes). It reports one line per item, answers questions and files code work as a GitHub issue (`capture`). An explicit request to start an agent on a repo goes to the software factory (`fleet` skill, `factory signal file`). The reporting contract lives in `SOUL.md` and nowhere else. Hermes does not use Slack (retired 2026-11).

**This repo is public.** Anything Hermes writes here gets read for tailnet names, node IPs, workspace user ids and `homelab-private` internals before it is committed; all four appeared on the first pass.

**After any edit: commit here.**

## Before you change it, read the doc

Detail, rationale and incident history are in `docs/`. Before touching one of these, Read its doc:

| Work on | Read |
|-|-|
| Audio: TTS/STT, the audio door, briefing voice | `docs/audio-door.md` |
| Symlinks, `HERMES_SKILLS`, host LaunchAgents, liveness scripts, skill durability | `docs/symlinks-and-agents.md` |
| Cron jobs, pre-run scripts, `hermes cron` | `docs/scheduled-jobs.md` |
| Secrets, `secrets.command`, door token, `.env.tpl` | `docs/secrets-command.md` |
| `:8642` API server, Iris turns | `docs/gateway-http-api.md` |
| `hermes serve`, Hermes Desktop | `docs/hermes-serve.md` |
| Argo endpoints, `work` skill, personal vs work APIs | `docs/argo-surface.md` |
| `agw research` / `web` / `podcast` / `hdx` / `otel`, WeatherOrb | `docs/agw-doors.md` |
| Project narratives | `docs/project-narratives.md` |
| Obsidian, KaraKeep, Wild Rift | `docs/second-brain.md` |
| Upstream patches, `/hermes-update` | `docs/patches.md` |
| Model, effort, context window, auxiliary lanes, `config.yaml` seats | `docs/model-context-reasoning.md` |
| Herdr steering, factory read/file paths | `docs/agent-routing.md` |
| Shell scripts under `pipefail` | `docs/shell-conventions.md` |
| Adding or renaming a skill, editing cron prompts, deploy, verify, heartbeat | `docs/editing-and-deploy.md` |

`docs/agents-md-ledger.md` records where every section of the former 45 KB root file went.

## Repo work is filed, never done

Hermes reads repos badly: an LLM with a `terminal` tool cannot use a repo's `AGENTS.md`, `.claude/rules/` or `.claude/skills/`. Repo work is filed as a GitHub issue (`capture`); the owner starts it. Hermes never lands PRs, runs `gh pr merge` or starts a `claude` session (`claude --bg`, `claude -p`). When Hermes did repo work anyway, fix the routing table in `SOUL.md`, never add a gate.

| Need | Path |
|-|-|
| Read fleet / Issue / ask / health state | `fleet` skill, `factory read overview\|needs\|flow\|chain\|issues\|issue\|health\|sessions\|accounts\|friction` (read-only `FACTORY_READ_TOKEN`) |
| File agent work ("do X", "let an agent …") | `fleet` skill, `factory signal file` (`FACTORY_SIGNAL_TOKEN`, `--from owner:hermes`) |
| File a GitHub issue / todo | `capture` |
| Personal data and service state (TickTick, Gmail, calendar, Docker, Kuma) | `argo-api` |
| Steer an existing terminal | `herdr` skill (`hc`), only when the owner asks |
| Notify the owner | cron: `scripts/ntfy-publish.sh <topic>`; turns: the reply |

Hermes never reads the agw/rd agent lists or the Herdr pane list for fleet status. Herdr safety: never `hc server stop|restart`, `hc update`, `hc machine update`, `hc send --force` or `hc attach`; every `hc read|get|wait|interrupt` takes an explicit target; keep `hc wait` under ~150 s (terminal tool cap 180 s). No approval stack: `plugins:` and `HERMES_PLUGINS` are empty.

## Traps that every change meets

- **Gateway restart is the owner's and `make deploy`'s; Hermes may not restart its own gateway.** `config.yaml`, `SOUL.md`'s cached prompt and any patched upstream file (`cron/prompt_scan.py`, `runtime_provider.py`, `agent/transports/chat_completions.py`, `utils.py`, `gateway/run_bootstrap.py`) are not live until `launchctl kickstart -k gui/$(id -u)/ai.hermes.gateway`. After a `hermes update`, restart `com.jkrumm.hermes-serve` too.
- **No approval prompts, no command guards (owner decision 2026-09-14): do not re-add either.** Steer by guidance in `SOUL.md` and the skills. `approvals.mode` is `off`; when Hermes does the wrong thing, make the guidance clearer.
- **Never run `hermes model` on the mini.** It writes a plaintext `~/.hermes/.env` that shadows the door-token names. In `secrets.command`, write the door token as `$t`, never `${t}` (config loading expands `${...}` first). Rotating it means editing `~/.agent-workflows/data/door-tokens`, then restarting the gateway **and** `com.jkrumm.hermes-serve`. Rotating `API_SERVER_KEY` means restarting the gateway and iris.
- **Scheduled jobs are LaunchAgents, never macOS crontab:** a `crontab -` write needs Full Disk Access and hangs forever on the headless mini. `hermes cron create --script` rejects any substantial script: keep entry points thin, logic in an imported module.
- **`cron/jobs.json` is gitignored runtime state with its own copy of the prompt.** Editing `cron/*.prompt.txt` changes nothing at runtime; push with `hermes cron edit <job_id> --prompt "$(cat …)" --skill a --skill b`. `hermes cron run` has no dry-run and delivers for real: retarget with `--deliver local` first.
- **A skill is durable only if symlinked from this repo.** `HERMES_SKILLS` in the Makefile is the source of truth; `fleet` is linked from the factory checkout (`HERMES_EXTERNAL_SKILLS`). A new skill needs `make setup` and a gateway restart (the skills index is cached in-process); a new plugin also needs `hermes plugins enable <name>`. Renaming or retiring a skill fails silently in cron (`skill not found, skipping`, job still `ok`): run `make status` after any rename.
- **Under `set -euo pipefail`, `$(producer | head -c N)` dies with SIGPIPE (141).** Write `$(… | head -c N || true)`.
- **Model facts are probed, and the route table owns them.** `make seats-check` (in `make check`) fails when `config.yaml` drifts from `agw routes`; a tier change in agw means editing `config.yaml` plus a restart. Hermes is Claude-only; every call goes through the local inference gateway (`127.0.0.1:7794`). The live effort key is `agent.reasoning_effort`. Compaction triggers at 650,000 tokens (owner decision 2026-11-04). Slice `agent.log` at the current process start; it is not rotated per process.
- **Argo is the personal and work API.** The `work` skill is read-only across M365, Confluence and GitLab, with Jira as the one write exception. Briefings carry exactly three work signals: today's calendar, Jira sprint commitments, GitLab MRs needing action.
- **agw reads its own config; callers set `AGW_CALLER=hermes`.** `agw research`, `agw podcast` and `agw otel` exit 10 `pending` after ~110 s: resume with `agw run wait <runId>`.
- **API sessions are keyed by the first message:** an identical test prompt to `/v1/chat/completions` resumes the old session, so reword it. A smoke that files real work (`capture`) opens a real issue; close it.

## Local modifications to upstream

One `.patch` per patched upstream file in `patches/`; `ls patches/` is the count and `make patch-check` proves they are applied, so never restate the number. Re-apply after `hermes update`: `cd ~/.hermes/hermes-agent && git apply ~/SourceRoot/hermes-agent/patches/<name>.patch` (`/hermes-update` carries the loop). The table of patches, their purpose and every retirement is in `docs/patches.md`. Baseline v0.23.2, `stable` channel.

## Validate and deploy

- `make check`: shell syntax, `compileall`, `make patch-check`, `make seats-check` and every `tests/test_*.py` under the Hermes venv (standalone, not pytest). No side effects. `tests/test_checkpoint_store_excludes.py` is not in it (intermittent timing failures on a clean tree): run `make test-checkpoint` and read the failures before blaming a change.
- `make setup` (idempotent symlinks and LaunchAgents), `make status`, `make verify` (exit 0 = healthy), `make logs`.
- `make deploy` = `make setup` + restart of `ai.hermes.gateway` and `com.jkrumm.hermes-serve` + `make verify`. It drops in-flight turns, and Hermes itself may never run it. On failure it rolls back to `HEAD~1` (detached): return with `git switch master`. Edits to `SOUL.md` and skills need no deploy beyond the skills-index restart.
- Factory manifest: `project.yaml`, `deploy.mode make`, verified by `make verify`, ship by push. `make version` prints the checkout's HEAD sha.
- Per-repo agent skills in `.claude/skills/`: `/hermes-validate` (test routing, fix `SOUL.md` / `SKILL.md`), `/hermes-update` (pull upstream, re-apply patches, restart).
