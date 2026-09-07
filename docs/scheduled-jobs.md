# Scheduled jobs — the Hermes cron registry, why LaunchAgents, the cron guard, editing a cron job

Moved verbatim out of `CLAUDE.md` (2026-09-04, size pass). `CLAUDE.md` § Symlink Map / Dispatch Bridge / Editing Rules points here — nothing was rewritten, only relocated. The registry table below was added 2026-09-07.

## Registry — every Hermes cron job (`hermes cron list`)

**This table is the git-tracked source of truth for what is registered.** `cron/jobs.json`
is gitignored runtime state, so without this list a job created by hand (`hermes cron
create` from a Slack turn) exists nowhere in git — the brain drift audit lived that way for
three weeks. `make status` asserts the live set against these ids in both directions: a row
with no live job is a schedule that silently stopped; a live enabled job absent here was never
written down. Add a row (and the `cron/<name>.md` + `.prompt.txt` pair for an agent job) in
the same commit that registers it.

| Job id | Name | Schedule | Mode | Script / prompt | Skills | Delivery |
|-|-|-|-|-|-|-|
| `cc7900c424a9` | Morning briefing | `0 7 * * 1-5` | agent | `briefing-context.py` pre-run · `cron/morning-briefing.prompt.txt` | `argo-api`, `work` | `slack:C0AT6TH404R` #briefings |
| `2d38c80e685c` | Evening report | `0 22 * * 1-4` | agent | `briefing-context.py` pre-run · `cron/evening-report.prompt.txt` | `argo-api`, `work` | `slack:C0AT6TH404R` #briefings |
| `4b1faabda97d` | Watchdog | `*/30 * * * *` | no-agent | `watchdog-slack.py` → `watchdog-poll.py --slack-body` | — | `slack:C0ASRULFTSS` #watchdog |
| `4dd759917dd1` | Dispatch sweep | `*/5 * * * *` | no-agent | `dispatch-sweep-cron.py` → `dispatch-sweep.py` | — | `slack:C0ASRULFTSS` #watchdog (per-dispatch origin thread via `hermes send`) |
| `8fe7be4985d9` | Brain drift audit | `0 9 * * 6` | agent | `cron/brain-drift-audit.prompt.txt` | `claude-dispatch`, `obsidian` | `slack:C0ASRULFTSS` #watchdog |
| `72aa2fb36307` | Agents overview | `*/30 * * * *` | no-agent | `agents-cron.py` → `agents-overview.py --slack-body` | — | `slack:C0BVDE5R562` #agents (Block Kit via `chat.postMessage`) |
| `9909f808fe17` | Project narratives | `30 6 * * *` | no-agent | `narratives-cron.py` → `project-narratives.py --run` | — | `slack:C0BVDE5R562` #agents |

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
> `watchdog-poll.py` (1218 lines), `watchdog-summary.py` and `briefing-coverage.py` are **all**
> rejected today; `watchdog-slack.py` (48 lines) passes. The already-registered jobs survive
> only because they predate the guard. That is why every registered entry point here is a thin
> loader and the logic lives in a module it imports — `dispatch-sweep-cron.py` (registered,
> terse, quotes nothing) loads `dispatch-sweep.py` (the real thing). If a future entry point
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
real**, so retarget it first (`--deliver slack:<test-channel>`) and restore the target after.
