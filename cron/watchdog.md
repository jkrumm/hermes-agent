# Watchdog — Hermes Cron Job

Source-of-truth for the watchdog cron prompt and registration. This file is documentation, not auto-loaded.

## Job Spec

| Field | Value |
|-|-|
| Schedule | `*/30 * * * *` (every 30 min, all days) |
| Skills | none — pre-run script does all data gathering |
| Pre-run script | `watchdog-poll.py` |
| Deliver | `slack:C0ASRULFTSS` (#watchdog) |
| Name | `Watchdog` |

## Sources monitored

| Source | Polled via | Surface gate | Reminder cadence |
|-|-|-|-|
| UptimeKuma down monitors | `https://api.jkrumm.com/uptime-kuma/monitors` | sustained 30 min | every 6h |
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

## Create / Update

```bash
# Create
hermes cron create "*/30 * * * *" "$(cat ~/SourceRoot/claude-local/hermes/cron/watchdog.prompt.txt)" \
  --script watchdog-poll.py \
  --name "Watchdog" \
  --deliver slack:C0ASRULFTSS

# Trigger immediately for testing
hermes cron run <job_id>

# Edit prompt only
hermes cron edit <job_id> --prompt "$(cat ~/SourceRoot/claude-local/hermes/cron/watchdog.prompt.txt)"
```

## Manual debugging

```bash
# Dry-run the poller (mutates state — see below to reset)
python3 ~/.hermes/scripts/watchdog-poll.py

# Snapshot of currently open items + 7-day resolved counts
python3 ~/.hermes/scripts/watchdog-summary.py

# Reset state (e.g. after threshold tuning)
rm ~/.hermes/watchdog.db
```

## Briefing integration

`briefing-context.py` calls `watchdog-summary.py` and appends a `## Watchdog State` block to its script output. The morning briefing prompt's Infrastructure section references it for context on items that were already triaged overnight.
