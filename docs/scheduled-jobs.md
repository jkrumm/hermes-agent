# Scheduled jobs — the Hermes cron registry, why LaunchAgents, the cron guard, editing a cron job

## Registry — every Hermes cron job (`hermes cron list`)

**This table is the git-tracked source of truth for what is registered.** `cron/jobs.json`
is gitignored runtime state, so without this list a job created by hand (`hermes cron
create` from a chat turn) exists nowhere in git — the brain drift audit lived that way for
three weeks. `make status` asserts the live set against these ids in both directions: a row
with no live job is a schedule that silently stopped; a live enabled job absent here was never
written down. Add a row (and the `cron/<name>.md` + `.prompt.txt` pair for an agent job) in
the same commit that registers it.

**Delivery vocabulary:** `local` (the job delivers nothing through Hermes) or `ntfy:<topic>`
(deliver is `local` AND the job publishes its own notice to that ntfy topic through
`~/.hermes/scripts/ntfy-publish.sh`). Hermes has no ntfy platform and its `bot-chat` target is
Desktop's, not Iris (which is pull-only), so no job uses a Hermes delivery target. `make status`
asserts the column and that every registered job's `deliver` is `local`. A publish failure makes
the no-agent script jobs fail (non-zero exit), so the failure grade shows it (the brain drift audit
publishes from inside its agent turn: its failure shows only in its cron output); failure notices are `--failure-deliver
local` — dotfiles' jobs-grade already grades the Hermes cron jobs and posts to ntfy topic `alerts`.

**State vocabulary:** `live` | `paused (<reason>)` | `retired (<date>, <reason>)`. A row's
state must match the live job's — `make status` asserts it.

| Job id | Name | Schedule | Mode | Script / prompt | Skills | Delivery | State |
|-|-|-|-|-|-|-|-|
| `cc7900c424a9` | Morning briefing | `0 7 * * 1-5` | agent | `briefing-context.py` pre-run · `cron/morning-briefing.prompt.txt` | `argo-api`, `work` | `local` | paused (owner, 2026-11-04) |
| `2d38c80e685c` | Evening report | `0 22 * * 1-4` | agent | `briefing-context.py` pre-run · `cron/evening-report.prompt.txt` | `argo-api`, `work` | `local` | paused (owner, 2026-11-04) |
| `8fe7be4985d9` | Brain drift audit | `0 9 * * 6` | agent | `cron/brain-drift-audit.prompt.txt` | `obsidian` | `ntfy:updates` | live |
| `9909f808fe17` | Project narratives | `30 6 * * *` | no-agent | `narratives-cron.py` → `project-narratives.py --run` | — | `ntfy:updates` | live |
| `679e16824f2c` | claude-release-watch | `every 60m` | no-agent | `model-release-watch.py` (temporary — retire when the awaited Claude model ships; OpenRouter + models.dev + Anthropic sitemap + news; stdout only when something is new; state in `~/.hermes/state/model-release-watch.*`) | — | `ntfy:models` | live |
| `825d9e57be32` | Usage weekly report | `30 7 * * 1` | no-agent | `usage-weekly-report.py` (prints usage-tracker's `<iso-week>.md`, written Monday 07:00 by its LaunchAgent) | — | `ntfy:updates` | live |

**Unpinned jobs stop, they don't re-route, when the global model moves.** `cron.model_drift_guard`
(on unless `cron.model_drift_guard: false`) refuses to fire any job whose *creation snapshot* of
the global provider/model no longer matches the resolved one — no inference call, one alert, then
silent until resolved. Remediation is a deliberate pin: `hermes cron edit <job_id> --provider <p>
--model <m>`. Only jobs created (or inference-edited) after the snapshot feature carry snapshots,
so no live job is both guarded and pinned today: `8fe7be4985d9` carries neither a pin nor a
snapshot (checked in `cron/jobs.json` 2026-11-04) and follows the global default — Haiku 5.5 on
the gateway's Anthropic leg — as do the older rows.

## Retired

- **`fd2fa108e0cc` — homelab-pr6-hardening-followup** — `every 180m`, agent, monitor
  `homelab-pr6-state.sh` → `origin`; retired 2026-09-28. The watcher's subject finished (the
  homelab PR #6 hardening follow-up landed) and the job was removed with its monitor script
  dropped in `6db191b` — but the registry row stayed behind, so `make status` read it as a
  schedule that silently stopped. Removed from the table above 2026-09-30; the script is in git
  history (`git show 66317b6:scripts/homelab-pr6-state.sh`) if that watch is ever wanted again.
- **`ea7a8f60daf4` — weatherorb-dwd_icon-stall-recheck** — one-shot (`in 5h`, run
  2026-09-23 06:22), agent, `origin`; it fired once (`repeat.completed: 1`) and was left
  disabled-but-present in `jobs.json`, which the registry check reports as an unregistered
  live job. Removed 2026-09-26 (a spent one-shot has no reason to stay); to re-arm, create a
  fresh job — the id above is not reusable.
- **`72aa2fb36307` — Agents overview** — `*/30 * * * *`, no-agent, `agents-cron.py`; posted a
  Block Kit digest to a Slack channel. Paused 2026-09-08 after reposting the same blocked pane
  ~35 times in two days; retired 2026-09-11. `agents-overview.py` and its briefing section were
  removed with the Slack gateway (2026-11): fleet state is read with `factory read` (overview,
  issues, asks, health, sessions) over the `/v1` API.
- **`b7a45b694f80` — quota-nudge** — retired 2026-10-30 (F1 Wave 6). The software factory
  babysits every session `rd` and the factory start: `~/SourceRoot/software-factory/AGENTS.md`.
- **`9919cec4a6d5` — Fleet babysitter** — retired 2026-10-30 (F1 Wave 6), same replacement.

Job ids are minted at `hermes cron create` and are stable for the life of the job — edit with
`hermes cron edit <id>`, never delete + re-create (that changes the id and breaks this table,
the prompt's own `cron/output/<id>/` history, and any doc that cites it).

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

> **The cron-creation guard rejects any substantial script — plan for a thin entry point.**
> `hermes cron create --script` runs the referenced file through `cron/lifecycle_guard.py`.
> Its `_contains_unsafe_gateway_action` recurses into anything that tokenizes like a
> referenced script and **fails closed when it exhausts its depth budget**
> (`if depth >= _MAX_REFERENCED_SCRIPT_DEPTH: return True`), so a long file — or even a short
> one whose comments quote filenames and command lines — is rejected as *"contains a gateway
> lifecycle command"* regardless of content. Measured against the live guard 2026-08-02:
> `briefing-coverage.py` is rejected today (and so were the retired `watchdog-poll.py`/`watchdog-summary.py`). The already-registered jobs survive only because
> they predate the guard. That is why every registered entry point here is a thin loader and the
> logic lives in a module it imports — `narratives-cron.py` (registered, terse, quotes nothing)
> loads `project-narratives.py` the same way. If a future entry point
> is rejected with that message, the cause is almost certainly length or a quoted command in a
> comment, not an actual lifecycle call — verify with
> `contains_gateway_lifecycle_command_or_referenced_script` before rewriting anything.

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
real**, so a job that publishes to ntfy posts for real; read its last output in `~/.hermes/cron/output/<id>/` instead
unless a real notice is acceptable.

### Cut-over from Slack delivery (run once at deploy)

The jobs still carry their old Slack targets in `jobs.json` until these run. Ids are the stable
registry ids above; the brain drift audit also needs its prompt pushed (final publish step).

```bash
hermes cron edit cc7900c424a9 --deliver local --failure-deliver local   # Morning briefing (paused)
hermes cron edit 2d38c80e685c --deliver local --failure-deliver local   # Evening report (paused)
hermes cron edit 8fe7be4985d9 --deliver local --failure-deliver local \
  --prompt "$(cat ~/SourceRoot/hermes-agent/cron/brain-drift-audit.prompt.txt)"   # Brain drift audit
hermes cron edit 9909f808fe17 --deliver local --failure-deliver local   # Project narratives
hermes cron edit 679e16824f2c --deliver local --failure-deliver local   # claude-release-watch
hermes cron edit 825d9e57be32 --deliver local --failure-deliver local   # Usage weekly report
```

Resuming the morning briefing or evening report needs a surface decision first (an ntfy topic with
a publish step in the prompt, or Iris once it can receive). They are paused, deliver `local`, and
their prompts describe a text body plus a `MEDIA:` audio tag that no current surface carries.
