# Evening Report — Hermes Cron Job

Source-of-truth for the evening report prompt. **This file is documentation, not auto-loaded.** Hermes cron jobs live in `~/.hermes/cron/jobs.json`, created via `hermes cron create` or the `cronjob` tool. Update both this file and the live job when iterating.

## Job Spec

| Field | Value |
|-|-|
| Schedule | `0 22 * * 1-4` (22:00 Mon–Thu, Europe/Berlin) |
| Skills | `argo-api`, `schedule`, `weather`, `tasks` |
| Pre-run script | `briefing-context.py` (shared with morning briefing) |
| Deliver | `slack:C0AT6TH404R` (#briefings) |
| Name | `Evening report` |

The schedule deliberately excludes Friday and Sunday — Friday evening is already weekend, Sunday should not be loaded with anything. Mon–Thu only.

## Create / Update

```bash
# Create
hermes cron create "0 22 * * 1-4" "$(cat ~/SourceRoot/dotfiles/hermes/cron/evening-report.prompt.txt)" \
  --skill argo-api \
  --skill schedule \
  --skill weather \
  --skill tasks \
  --script briefing-context.py \
  --name "Evening report" \
  --deliver slack:C0AT6TH404R

# Trigger immediately for testing
hermes cron run <job_id>

# Edit prompt only
hermes cron edit <job_id> --prompt "$(cat ~/SourceRoot/dotfiles/hermes/cron/evening-report.prompt.txt)"
```

`--script briefing-context.py` is shared with the morning briefing. The same `briefing-state.json` controls the city + vacation flag for both. Vacation suppresses both reports until the date passes.

## What It Does

Mon–Thu at 22:00, a fresh Hermes session:

1. Pre-run script (`briefing-context.py`) emits `BRIEFING_CITY=…` + `BRIEFING_SUPPRESSED=true|false`. On vacation the agent short-circuits with `[SILENT]`.
2. Fires 5 parallel curls — `/daily-metrics/`, `/workouts/`, `/gmail/calendar?days=2`, `/weather/forecast`, `/summary`
3. Composes a structured Slack mrkdwn body (English, 5 sections) — Today's Training, Recovery & Body, Tomorrow's Schedule, For Tomorrow (max 3 items), Tomorrow's Weather
4. Composes a separate German narrative (~120–150 words, four paragraphs, calm wind-down tone)
5. Calls TTS on the narrative → MP3 + `MEDIA:` tag
6. Returns the structured text body + `MEDIA:` tag — Slack delivers both text and audio attachment

## Tone & Format

**Anti-stress contract.** The evening report deliberately omits anything that can pile pressure onto the night:

- No overdue task counts (even though `/summary` returns them)
- No open PRs / open issues
- No infrastructure / Docker / UptimeKuma status (watchdog cron handles that with its own channel)
- No #alerts surface
- No motivational closing lines, no "Schlaf gut", no pep talk

It exists so the day closes with: what your body did today, what tomorrow looks like, that's it.

**Text body (Slack mrkdwn, English):**
- Sections: Header (`Evening — Weekday, Mon DD`) → Today's Training → Recovery & Body → Tomorrow's Schedule → For Tomorrow (max 3) → Tomorrow's Weather
- Emoji shortcode headers (`:waning_crescent_moon:`, `:weight_lifter:`, `:sleeping:`, `:date:`, `:checkered_flag:`, `:partly_sunny:`)
- Bullet lists with `-`, project emojis for tasks (`:briefcase:`, `:house:`, `:innocent:`)

**Audio narrative (German, separate text — only fed to TTS):**
- Soft conversational, no greeting / no name
- Four paragraphs separated by blank lines: Today's body+training, Sleep+recovery, Tomorrow's schedule+focus, Tomorrow's weather+optional close
- Calm low-energy tone; NOT a recap of achievements, NOT motivational
- ~120–150 words / ~55–70s spoken
- TTS chunks per paragraph with `paragraph_pause_secs=2.0`

## Vacation + city handling

Same mechanism as the morning briefing — both reports read `~/.hermes/scripts/briefing-state.json`:

- `"city"` — used for tomorrow's weather
- `"vacation_until"` — date string. If today ≤ that date, both morning and evening reports return `[SILENT]`.

No separate state file. To skip just the evening (e.g. dinner out), `hermes cron pause <id>` is simpler.

## Why Mon–Thu (not Mon–Fri)

- **Friday evening:** weekend has already started — no need for "tomorrow prep" framing on a Saturday.
- **Sunday evening:** intentionally protected. Sunday is the longest off-ramp; loading it with a "tomorrow is Monday" report would be counterproductive.
- **Saturday evening:** would feed into Sunday — also skipped.

If a Mon–Thu falls on a public holiday, the calendar will show no events and the report fires anyway. Acceptable — the body data is still useful as a closing-loop signal.

## Iteration Notes

- If 22:00 feels too late (or too early), edit the cron expression. `0 21 * * 1-4` for 21:00.
- If the audio feels too long, tighten the prompt's word target from 150 to 110.
- The 7-day averages for HRV/RHR are computed from the same `/daily-metrics/` payload as the morning briefing — keep the trend formula consistent across both prompts so arrows mean the same thing.
- If a workout is logged late (after 22:00), tomorrow's report will catch it as "yesterday's session" only via the `/workouts/` order. Acceptable — the alternative is a delayed cron, which feels worse.

## Open question — sleep timing on the data side

At 22:00 the `daily_metrics` row for "today" reflects last night's sleep, today's HRV (recorded during last night's sleep), today's resting HR, and today's body battery trajectory up to ~22:00. This is the cleanest sample window for the report. The morning briefing has the inverse problem (sleep score still syncing) — the evening report does not.
