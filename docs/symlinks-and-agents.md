# Symlink map + host LaunchAgents — original notes

`make setup` writes the following symlinks:

| File here | Live path | Notes |
|-|-|-|
| `config.yaml` | `~/.hermes/config.yaml` | symlink — edit here, live immediately |
| `.env.tpl` | `~/.hermes/.env.tpl` | symlink |
| `serve.env.tpl` | `~/.hermes/serve.env.tpl` | symlink — `hermes serve`'s basic-auth refs, read only by `scripts/hermes-serve-launch.sh` |
| `SOUL.md` | `~/.hermes/SOUL.md` | symlink |
| `cron/` | `~/.hermes/cron/` | symlink — Hermes-driven (LLM) cron jobs |
| `scripts/` | `~/.hermes/scripts/` | symlink — Hermes cron pre-run scripts (security check requires they live under `HERMES_HOME/scripts/`). Also holds host-level shell scripts. |
| `hooks/` | `~/.hermes/hooks/` | symlink — add hooks here |
| `plugins/{name}/` | `~/.hermes/plugins/{name}/` | symlink per plugin — none today. **`HERMES_PLUGINS` in the Makefile is the source of truth.** A plugin also has to be enabled once (`hermes plugins enable <name>`, recorded under `plugins.enabled` in `config.yaml`); the symlink alone does nothing. Same durability argument as skills — a plugin living only under `~/.hermes/` is unreviewable state one `hermes update` away from surprise. |
| `config/` | `~/.hermes/config/` | symlink — tracked agent-facing config. Empty now; kept for whatever tracked agent-facing config lands here next. |
| `skills/{name}/` | `~/.hermes/skills/{name}/` | symlink per skill — actual dirs are the 23 in `HERMES_SKILLS` (`capture`, `argo-api`, `work`, `karakeep`, `obsidian`, `reading`, `wildrift`, `agw-research`, `agw-web`, `image-delivery`, `podcast`, `prose`, `briefing-tts`, `hyperdx`, `homelab`, `homelab-ops`, `hermes-gateway`, `human-queue`, `herdr`, `verify`, `home`, `iris`, `fleet`) (the former infrastructure/schedule/tasks/weather/garmin-health/strength skills were consolidated into `argo-api/references/*.md` — now incl. `walking-pad.md`; they are no longer separate dirs and were dropped from `HERMES_SKILLS`). **`HERMES_SKILLS` in the Makefile is the source of truth — this list must match it (23 entries today).** `fleet` is the exception to "from this repo": its source is `software-factory/integrations/hermes/fleet` (`HERMES_EXTERNAL_SKILLS`, `FACTORY_DIR`), linked from the factory checkout, so no `skills/fleet/` dir exists. `homelab` is additionally a **category dir**: `skills/homelab/{tailscale-diagnostics,torrent-stack-diagnostics}/` load as their own skills (`hermes skills list` shows them under category `homelab`) and ride the parent symlink, so they need no `HERMES_SKILLS` entry. Hermes authored both itself, through the symlink, during ordinary foreground turns — it also patches `references/` files in place the same way. Such edits are safe from the background curator (they resolve under `skills.external_dirs`) but invisible to any stray-skill sweep, which skips symlinked top-level dirs and excludes anything under `external_dirs` regardless. Git is the only thing that sees them, which is why `make status` asserts `skills/` is committed. **This repo is public** — anything Hermes writes here gets read for tailnet names, node IPs, workspace user ids and `homelab-private` internals before it is committed (all four were present on the first pass). |
| `USER.md` | `~/.hermes/memories/USER.md` | copied — Hermes writes to it |

> **Skill trust (v0.16.0+).** Skills are symlinked into `~/.hermes/skills/`, but v0.16.0's skill-security check resolves each skill's *realpath* and warns — and may later **block** — when it lands outside a trusted dir (our symlink targets do). `config.yaml` therefore sets `skills.external_dirs: [~/SourceRoot/hermes-agent/skills, ~/SourceRoot/software-factory/integrations/hermes]` (the second for `fleet`) so the resolved realpath is trusted. The symlink and the external entry resolve to the same path, which `skills_tool` dedups (by realpath on load, by name on listing) — no duplicate-skill collisions. If a future update reintroduces the "skill file is outside the trusted skills directory" warning, confirm this key is still populated.

> **`external_dirs` is also what protects a skill from the background self-improvement pass — this is why every durable skill must live in this repo.** The autonomous curator fork (`is_background_review()`) refuses every mutating action — edit, patch, delete, write_file, remove_file — on a skill whose resolved path falls under `skills.external_dirs` (`tools/skill_manager_tool.py` → `_background_review_write_guard`). A skill created ad hoc under `~/.hermes/skills/` by the agent itself (not symlinked from here) has no such protection: it sits outside `external_dirs`, so the same background pass can — and, observed in practice, repeatedly did — silently rewrite it, growing by accretion with no review (`skills.write_approval` is off by default) until it was restorable only from the nightly rsync backup. **Symlinking a skill from this repo is not cosmetic — it is the only thing that makes it durable.** Nothing sweeps for strays automatically any more (the `stray_skill` poller retired 2026-10-27); `make status` only asserts that repo dirs, live symlinks and `HERMES_SKILLS` agree. A manual sweep walks `~/.hermes/skills/` two levels deep (top-level and one level nested inside a bundled category dir, since real strays hide there too — `homelab-alerts` was under `devops/`) and flags any non-symlink dir with its own `SKILL.md` whose name isn't in `.bundled_manifest` **and** whose `~/.hermes/skills/.usage.json` record shows local mutation — `created_by == "agent"` (the marker `skill_manager_tool.py` sets only inside the background curator fork) **or** `patch_count >= 1`; a stray is resolved by adopting it (symlinked in from here) or deleting it. A plain manifest-membership check over-fires: the live tree carries 19 dirs that are absent from `.bundled_manifest` by name yet legitimate (hub-installed, or seeded by an early pre-manifest-tracking sync). But 18 of those 19 have never been touched, so *mutation* is what separates them — one candidate on the current tree against six real strays it would have caught. `created_by` alone is too narrow: it catches the worst class (`homelab-alerts`, 89 rewrites) but missed four of the six cleaned up on 2026-08-02, since the curator's consolidations of upstream skills carry `created_by: None` with 1-5 patches each. Those are the same problem — a divergent local copy `hermes update` will never refresh — and the patch count is what exposes them.
>
> Manual fallback (e.g. to sanity-check the automated source, or if `watchdog-poll.py` itself is broken) — coarser, top-level only, no mutation filter, so it can false-positive on legitimate untracked nested skills:
> ```bash
> for d in ~/.hermes/skills/*/; do d="${d%/}"; [[ -L "$d" ]] && continue; [[ -f "$d/SKILL.md" ]] || continue; grep -q "^$(basename "$d"):" ~/.hermes/skills/.bundled_manifest || echo "$(basename "$d")"; done
> ```
> Any real hit needs the same treatment this file's history documents: read it fully, separate durable knowledge from dated incident sediment, land the durable part under `skills/` here, wire it into `HERMES_SKILLS` + this table, archive the original outside git (`.skill-archive/`, gitignored — it will carry secrets the source itself doesn't scrub), then delete the untracked original.

**Claude Code per-repo skills** (committed at `.claude/skills/`, not symlinked — auto-loaded by Claude Code when started inside this repo):
- `/hermes-validate` — slash command to test Hermes routing + fix SOUL.md / SKILL.md
- `/hermes-update` — slash command to pull upstream Hermes, re-apply local patches, restart the gateway

**Host-level scripts (run by user LaunchAgents, not symlinked):**
- `scripts/hermes-liveness.sh` — every 5 min (`com.jkrumm.hermes-liveness`, `StartInterval 300`), checks gateway state + the API server platform (`platforms.api_server.state`), pings the push URL resolved via `secrets-run read op://hermes/uptime-kuma/agent-push-url` on success. **Bounded** (both liveness pushers): the plist runs it under `jobrun --timeout 270` (launchd never starts a second instance of a hung job — dotfiles devhost-health froze ~28 h on 2026-11-06), every external call has its own `timeout`/`curl --max-time`, and a failed check pushes `status=down&msg=<reason>` instead of staying silent, except `gateway_state=draining` (planned restart: ping withheld, monitor not told down). `tests/test_liveness_bounded.py` pins it.
- `scripts/hermes-backup.sh` — daily 03:00 (`com.jkrumm.hermes-backup`, `StartCalendarInterval`), rsyncs `~/.hermes/` → `homelab:/mnt/hdd/backups/hermes/`, pings the push URL resolved via `secrets-run read op://hermes/uptime-kuma/backup-push-url` on success. Holds a `mkdir`-based single-instance lock (`~/Library/Caches/hermes-backup.lock`) so two overlapping runs can never race one another's `rsync --delete`.
- `scripts/hermes-serve-launch.sh` — the `ProgramArguments` of `com.jkrumm.hermes-serve` (KeepAlive, 30s throttle). Counts the three `serve.env.tpl` refs, refuses (exit 78) below the full set, then execs `.hermes/bin/hermes serve --host 127.0.0.1 --port 9119 --skip-build` under `secrets-run run --env-file=serve.env.tpl` (the gateway's refs arrive via `secrets.command`). Restored 2026-10-15; see `docs/hermes-serve.md`.
- `scripts/hermes-serve-liveness.sh` — every 5 min (`com.jkrumm.hermes-serve-liveness`), asserts `/api/status` reports `auth_required: true` and an unauthenticated `POST /api/auth/ws-ticket` returns 401, then pings `op://hermes/uptime-kuma/serve-push-url`.

Templates live in `launchd/`, rendered into `~/Library/LaunchAgents` by `make setup`
(`_agents` → `_render-plists`, `__HOME__` substituted; unchanged content is a no-op,
so re-running never bounces a healthy agent). Logs are declared, never globbed, in
`dotfiles/scripts/log-rotate.sh`'s `FILES` array: `hermes-{liveness,backup,serve,serve-liveness}.{log,err}`
under `~/Library/Logs`, `~/.hermes/logs/gateway.{log,error.log}` (absolute — the
gateway's own launchd streams, not this repo's LaunchAgents), plus the audit log
`hermes-ops.log` (`hermes-cc.log` is the retired predecessor
name, still rotated until it ages out).

<!-- MOVED-SYMLINK-MAP: moved verbatim from the root AGENTS.md (Symlink Map, 4533 bytes) -->

## Symlink Map

`make setup` writes these symlinks. Full table + host-LaunchAgent detail, per-script:
**`docs/symlinks-and-agents.md`**.

| File here | Live path | Notes |
|-|-|-|
| `config.yaml`, `.env.tpl`, `SOUL.md` | `~/.hermes/…` | edit here, live immediately; `.env.tpl` is the gateway's list of `KEY=op://…` refs |
| `serve.env.tpl` | `~/.hermes/serve.env.tpl` | `hermes serve`'s own three basic-auth refs — deliberately not in `.env.tpl` (see `docs/hermes-serve.md`) |
| `cron/`, `scripts/`, `hooks/` | `~/.hermes/…` | Hermes-driven cron + pre-run scripts (must live under `HERMES_HOME/scripts/`) + host-level shell scripts |
| `plugins/{name}/` | `~/.hermes/plugins/{name}/` | **`HERMES_PLUGINS`** is the source of truth. **None today.** A new one must **also** be enabled once — `hermes plugins enable <name>`; the symlink alone is inert. |
| `config/` | `~/.hermes/config/` | **empty** — kept for tracked agent-facing config |
| `skills/{name}/` | `~/.hermes/skills/{name}/` | **`HERMES_SKILLS` in the Makefile is the source of truth** — 23 dirs (agent-platform Wave 2, 2026-10-04; was 126; `iris` added 2026-11-04, `fleet` 2026-11-07, `agw-web` 2026-11-15). **`fleet`'s source is `software-factory/integrations/hermes/fleet`** (`HERMES_EXTERNAL_SKILLS`, `FACTORY_DIR` in the Makefile; `make setup` links it from the factory checkout, warns and skips if absent) — there is no `skills/fleet/`. Retired skills live on as `<skill>/references/*.md` or in git history; roster: docs. |
| `USER.md` | `~/.hermes/memories/USER.md` | **copied** — Hermes writes to it |

**Skill audit (2026-10-10, `docs/skills-audit.md`):** per-skill verdicts, usage evidence and the Hermes↔global wiring map. Upstream-bundled skills with no usage record are retired by `skills.disabled` in `config.yaml` (reversible; never deleted). `make skills-set-check` (in `make status`) asserts repo `skills/` (minus `HERMES_EXTERNAL_SKILLS`), live symlinks (into this repo or `$FACTORY_DIR/integrations/hermes/`) and `HERMES_SKILLS` are one set.

**Autonomous skill creation is off** (`skills.creation_nudge_interval: 0`); `skills.create_dir` points at `~/.hermes/skills-quarantine`, outside `external_dirs`, so anything Hermes writes anyway is neither live nor tracked until the owner promotes it here. Needs a gateway restart.

**A skill is durable only if symlinked from this repo.** `skills.external_dirs` satisfies the
v0.16.0+ skill-trust check **and** protects a skill from the background self-improvement
curator — a skill created ad hoc under `~/.hermes/skills/` has neither and gets silently
rewritten by accretion. Detection is manual (`ls ~/.hermes/skills` against `HERMES_SKILLS`); the old `stray_skill` poll retired with the control plane. Full
mechanism + adoption path: **`docs/symlinks-and-agents.md`**.

**Host-level scripts** (user LaunchAgents, not symlinked): `hermes-liveness.sh` (300s, both liveness pushers run under `jobrun --timeout 270` with every call bounded, a failed check pushes `status=down&msg=<reason>`, except `gateway_state=draining` (planned restart: ping withheld, monitor not told down) — `docs/symlinks-and-agents.md`; gateway
state + API server connected + the live pid belongs to launchd's job + the inference gateway answers and accepts Hermes' door token, via `scripts/inference-gateway-check.sh`, shared with `make verify`/`status`), `hermes-backup.sh` (daily
03:00 — rsync to homelab, `mkdir`-lock against overlap), and the `hermes serve` pair —
`hermes-serve-launch.sh` (KeepAlive) + `hermes-serve-liveness.sh` (300s), see `docs/hermes-serve.md`
below.
`HERMES_PLISTS_RETIRED` unloads +
removes labels this repo no longer installs — the two `hermes-webui{,-liveness}` labels sit there
since the 2026-09-07 teardown of the third-party WebUI clone (not coming back; the serve pair torn
down with it was restored 2026-10-15). `make status` grades every agent like
dotfiles' doctor. Logs declared, never globbed, in `dotfiles/scripts/log-rotate.sh`.

**Scheduled jobs are LaunchAgents, never macOS crontab** — a `crontab -` *write* needs Full
Disk Access and hangs forever on the headless mini. Done 2026-08-02 — no hermes entries in
`crontab -l`. All live `hermes cron` jobs (ids, schedules, delivery) + reasoning:
**`docs/scheduled-jobs.md`**.

**Per-repo agent skills** (`.claude/skills/`, committed, no symlink — Claude Code and OpenCode both load them): `/hermes-validate`
(test routing, fix SOUL.md / SKILL.md) · `/hermes-update` (pull upstream, re-apply patches,
restart gateway).
