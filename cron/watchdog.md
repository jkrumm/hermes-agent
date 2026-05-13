# Watchdog — Hermes Cron Job

Source-of-truth for the watchdog cron registration. This file is documentation, not auto-loaded.

## Job Spec

| Field | Value |
|-|-|
| Schedule | `*/30 * * * *` (every 30 min, all days) |
| Mode | `no_agent` — script stdout delivered verbatim, no LLM round-trip |
| Script | `watchdog-slack.py` (wrapper → `watchdog-poll.py --slack-body`) |
| Deliver | `slack:C0ASRULFTSS` (#watchdog) |
| Name | `Watchdog` |

`watchdog-slack.py` is a thin wrapper because Hermes invokes cron scripts as `python3 <path>` with no args. The real work lives in `watchdog-poll.py`. Empty stdout = silent delivery; non-empty stdout = Slack mrkdwn body sent verbatim. `watchdog.prompt.txt` is kept for reference but unused since the cut-over to `no_agent`.

## Sources monitored

| Source | Polled via | Surface gate | Reminder cadence |
|-|-|-|-|
| UptimeKuma down monitors | `https://argo.jkrumm.com/api/uptime-kuma/monitors` | sustained 30 min | every 6h |
| Docker unhealthy (homelab + vps) | `/docker/{host}/summary` | sustained 30 min | every 6h |
| Stale GitHub PRs | `gh search prs --owner jkrumm --state open` | no update >3 days | every 3 days |
| Stale GitHub issues | `gh search issues --owner jkrumm --state open` | no update >3 days | every 7 days |
| Slack #alerts patterns | `/slack/channels/C0AS1LAUQ3C/messages` | flap of ≥3 same topic in batch | every 24h |
| Slack #updates patterns | `/slack/channels/C0ARZJD824W/messages` | flap of ≥3 same topic in batch | every 24h |
| Hermes self — cron failures | `~/.hermes/cron/jobs.json` `last_status != ok` | immediate | every 6h |

UK push monitor messages in #alerts (regex `\[…Push\]`) are filtered out — the UK API itself is the canonical source for those, avoiding double-eventing.

## Quiet hours

Between 00:00 and 07:00 in Johannes's local timezone (read from `~/.hermes/scripts/briefing-state.json` `timezone` field, default `Europe/Berlin`), the script still runs and updates state, but the LLM responds with `[SILENT]` so nothing reaches Slack. Overnight events surface naturally in the 07:00 morning briefing if still open.

Vacation flag (`vacation_until` in the same state file) suppresses the same way.

## State

`~/.hermes/watchdog.db` (SQLite) — backed up nightly via the existing rsync job. Two tables:

- `events` — one row per `(source, external_id)` with full lifecycle timestamps (`first_seen`, `notified_at`, `last_reminder_at`, `resolved_at`, `reminder_count`).
- `cursors` — per-source watermarks (e.g., last Slack ts polled).

Resolved rows are kept indefinitely for trend queries (`SELECT source, COUNT(*) WHERE resolved_at >= … GROUP BY source`).

## Re-register

```bash
# Initial create (no_agent — no prompt needed)
hermes cron create "*/30 * * * *" "" \
  --script watchdog-slack.py \
  --no-agent \
  --name "Watchdog" \
  --deliver slack:C0ASRULFTSS

# Trigger immediately for testing
hermes cron run <job_id>

# Toggle modes
hermes cron edit <job_id> --no-agent --script watchdog-slack.py   # current
hermes cron edit <job_id> --agent --script watchdog-poll.py       # revert to LLM
```

## Manual debugging

```bash
# Dry-run the slack body — read-only, uses a temp DB copy.
python3 ~/.hermes/scripts/watchdog-poll.py --slack-body --dry-run

# Dry-run the legacy KV-block emission (for diff against historical cron runs).
python3 ~/.hermes/scripts/watchdog-poll.py --dry-run

# Production poll — mutates real DB. Equivalent to one cron tick.
python3 ~/.hermes/scripts/watchdog-poll.py --slack-body

# Snapshot of currently open items + 7-day resolved counts (read-only).
python3 ~/.hermes/scripts/watchdog-summary.py

# Reset state (e.g. after threshold tuning).
rm ~/.hermes/watchdog.db
```

## Briefing integration

`briefing-context.py` calls `watchdog-summary.py` and appends a `## Watchdog State` block to its script output. The morning briefing prompt's Infrastructure section references it for context on items that were already triaged overnight.
