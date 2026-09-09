# Briefing pre-run scripts and runtime state

The watchdog poll, its Slack digest, the dispatch sweeper and the alert-triage act-loop
moved to `~/SourceRoot/warden` on 2026-09-09 (see its `CLAUDE.md`, `DESIGN.md`, `STATE.md`).
What's left here is the briefing side, which still runs inside `hermes-agent`:

**Hermes cron pre-run scripts (executed by `hermes-agent` before each cron run, *not* by macOS crontab or launchd):**
- `scripts/briefing-context.py` — reads `briefing-state.json` and emits `BRIEFING_CITY` + `BRIEFING_SUPPRESSED` for the morning briefing prompt. Calls `briefing-coverage.py` as subprocess. Also shells out to warden's `scripts/watchdog-summary.py` (path overridable via `WARDEN_WATCHDOG_SUMMARY`) for the briefing's Infrastructure section. Output is appended as `## Script Output` block.
- `scripts/briefing-coverage.py` — full TickTick backlog + open GitHub items; emits `COVERAGE_AVAILABLE`, `TICKTICK_BACKLOG`, `TICKTICK_HIGH_PRIO_DATELESS`, `GITHUB_OPEN_BY_REPO`, `GITHUB_FRESH_48H`, `GITHUB_TOTAL` blocks. Called by `briefing-context.py`. Resolves its one secret (`HOMELAB_API_KEY`) from the process env, falling back to `secrets-run read op://common/api/SECRET` — the same two-step, and the same ref, warden's `watchdog-poll.py` uses. It used to parse a plaintext `~/.hermes/.env`, which has not existed since v0.19 moved secrets to `config.yaml`'s `secrets.command`; that path returned `{}` on every run and the script worked only because the cron happened to inherit the gateway's env. The failure it left open is quiet — the cron subprocess sanitizer strips high-value secrets, and a stripped key means the briefing silently loses its whole coverage section.
- `scripts/briefing-state.json` — *gitignored* runtime config (city + vacation flag). Edit locally; never commits. Seeded from `briefing-state.example.json` on first `make setup`.
- `skills/capture/state.json` — *gitignored* runtime cache for the capture skill (GitHub repos + TickTick projects). Refreshed on miss via `gh repo list jkrumm` and `/ticktick/projects`. Seeded empty from `state.example.json` on first `make setup`.

For the watchdog poll's sources/reminder cadence, the SQLite ledger (`~/.warden/warden.db`),
the dispatch sweeper's verdict/nudge delivery, and the alert-triage act-loop: `~/SourceRoot/warden/CLAUDE.md`,
`DESIGN.md`, `STATE.md`. `docs/dispatch-bridge.md` in this repo covers the `dispatches`/`dispatch_approvals`
half of the ledger, which `scripts/hermes-cc.sh` and `plugins/dispatch-approval/` still own here.
