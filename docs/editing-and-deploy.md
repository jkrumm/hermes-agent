# editing-and-deploy

<!-- MOVED-EDITING: moved verbatim from the root AGENTS.md (Editing rules, 1425 bytes) -->

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
(`--deliver local`), then restore. Detail: **`docs/scheduled-jobs.md`**.

**Adding a CC slash command:** create `.claude/skills/{name}/SKILL.md` — auto-loaded here, no
symlink or Makefile change. **Patches:** save the diff under `patches/`, add a table row in
the `docs/patches.md` table, put per-file detail in `docs/patches.md`.

<!-- MOVED-DEPLOY-VERIFY: moved verbatim from the root AGENTS.md (Deploy and verify, 2740 bytes) -->

## Deploy

`make deploy` — the checkout *is* the live config (symlinked into `~/.hermes`), so deploy =
`make setup` + `launchctl kickstart -k` of `ai.hermes.gateway` **and** `com.jkrumm.hermes-serve` + `make verify`
(retried ~1 min while the API server reconnects). On failure it rolls back to `HEAD~1` (detached,
clean tree only), repeats, and exits non-zero either way; return with `git switch master`.
It restarts the gateway, which drops in-flight turns — and **Hermes itself may never run
it** (it may not restart its own gateway). Edits to `SOUL.md` and skills need no deploy
beyond the skills-index restart noted in *Editing Rules*.

## Verify & Monitor

**Factory manifest:** `project.yaml` (software-factory `docs/design.md` §9) — `deploy.mode make`, target `mini`
verified by `make verify`, 5m hold, ship by push. `make version` prints the checkout's HEAD sha (the checkout is
the live config), which the factory compares with the shipped commit.
- **Weekly hygiene probes** (`hygiene.probes` in `project.yaml`, run by the factory, not a LaunchAgent): `upstream` =
  **`make upstream-check`** (installed `hermes --version` vs the newest stable upstream tag — canary, rc, abandoned and
  date tags excluded; prints installed / latest / commits behind; exit 0 current, 1 behind with a last line naming the
  `/hermes-update` skill, 2 could not tell) and `live` = `make verify`. Read-only: the lead that takes a finding runs
  `/hermes-update` and `make deploy`. `docs/scheduled-jobs.md` §Weekly hygiene probes.

- **`make verify`** — gateway pid alive, `gateway_state.json` api_server
  `connected`, API `/health` 200 on the tailnet bind (`op://hermes/gateway/host`), the inference gateway (`:7794`) healthy and accepting the door token, `hermes serve`
  answering on `:9119` **and gated** (`auth_required`, unauthenticated ws-ticket 401), all patches
  applied. Exit 0 = healthy.
- **Heartbeat:** `hermes-liveness.sh` (300 s LaunchAgent) pushes the Uptime Kuma push monitor
  at `op://hermes/uptime-kuma/agent-push-url`; the backup job has its own
  (`backup-push-url`). A red heartbeat means the gateway, the API server or the secret cache is down.
  Both liveness scripts try the success push three times and then exit 75 (EX_TEMPFAIL): the check
  ran, Kuma was not reached; jobrun-grade reports it as "undelivered", not as the job failing.
  Skips that tell Kuma `down` stay exit 0; an unresolvable push URL stays a real failure.
- **OTel:** none — Hermes emits no traces; `service.name` does not apply.
- **`make logs`** — bounded tail of `gateway.error.log`, `errors.log`, `agent.log`
  (`~/.hermes/logs/`). Slice `agent.log` at the current process start (see *Model, context
  window and reasoning effort*).
