# Morning Briefing — Hermes Cron Job

Source-of-truth for the morning briefing prompt. **This file is documentation, not auto-loaded.** Hermes cron jobs live in `~/.hermes/cron/jobs.json`, created via `hermes cron create` or the `cronjob` tool. Update both this file and the live job when iterating.

## Job Spec

| Field | Value |
|-|-|
| Schedule | `0 7 * * 1-5` (07:00 weekdays, Europe/Berlin) |
| Skills | `tasks`, `schedule`, `weather`, `infrastructure`, `slack` |
| Deliver | `slack:C0AT6TH404R` (#briefings) |
| Name | `Morning briefing` |

## Create / Update

```bash
# Create
hermes cron create "0 7 * * 1-5" "$(cat ~/SourceRoot/claude-local/hermes/cron/morning-briefing.prompt.txt)" \
  --skill tasks \
  --skill schedule \
  --skill weather \
  --skill infrastructure \
  --skill slack \
  --name "Morning briefing" \
  --deliver slack:C0AT6TH404R

# Trigger immediately for testing
hermes cron run <job_id>

# Edit prompt only
hermes cron edit <job_id> --prompt "$(cat ~/SourceRoot/claude-local/hermes/cron/morning-briefing.prompt.txt)"
```

The prompt is kept as a separate `.prompt.txt` file (sibling to this doc) so it can be piped into the CLI without escaping.

## What It Does

Every weekday at 07:00 a fresh Hermes session:

1. Fires 8 parallel curls/`gh` calls — `/summary`, both Docker summaries, calendar, weather, recent #alerts, open PRs, open issues
2. Composes a structured Slack mrkdwn body (English, emoji-headed sections, bullet lists)
3. Composes a separate German narrative (~150 words, conversational)
4. Calls TTS on the narrative → MP3 + `MEDIA:` tag
5. Returns the structured text body + `MEDIA:` tag — Slack delivers both text and audio attachment

## Tone & Format

**Text body (Slack mrkdwn, English):**
- Sections: Weather → Schedule → Infrastructure → Alerts → GitHub → Tasks
- Emoji shortcode headers (`:sunny:`, `:date:`, `:hammer_and_wrench:`, `:rotating_light:`, `:octocat:`, `:checkered_flag:`)
- Bullet lists with `-`, project emojis for tasks (`:briefcase:`, `:house:`, `:innocent:`)
- Concise: short dates ("Apr 17"), one-line bullets where possible

**Audio narrative (German, separate text — only fed to TTS):**
- Warm conversational, no greeting / no name
- Three paragraphs: Wetter+Termine, Infrastruktur+Alerts, Aufgaben+GitHub
- Times spoken naturally ("Viertel nach neun")
- ~150 words / ~60s spoken

## Iteration Notes

- Default language is German. Switch to English by editing the prompt if preferred.
- If the briefing feels too long, ask the agent to keep it under 60s spoken (~150 words).
- Weather city is Munich (skill default). See **Optional: location + vacation state** below for the planned override mechanism.
- For now, no email digest in the morning briefing — keep it focused. Add later if useful.

## Validation (2026-04-28)

Tested via the `/hermes-validate` flow — sent the prompt to `#hermes` as a one-shot message and read the session JSONL trace.

| Metric | Result |
|-|-|
| `time` | 87.5s (target <90s) |
| `api_calls` | 3 (target ≤5) |
| Tool pattern | 3 parallel `terminal` curls → `text_to_speech` → final response |
| Output | German narrative, ~165 words, single `MEDIA:` tag |
| Skills routed | `tasks` + `schedule` + `weather` via SOUL.md (no skill misroutes) |

Two prompt tweaks landed during iteration: use `daily_7d[0]` for the weather (so the 07:00 forecast isn't biased by the API-pull moment) and cap the task list at 5 with a spillover phrase. Both reflected in `morning-briefing.prompt.txt`.

## Optional: location + vacation state

Two helper files in this directory (drafted, not yet wired into the cron prompt):

- `briefing-state.json` — manually edited config: `{"city": "Munich", "vacation_until": null}`
- `briefing-context.py` — pre-run script. Reads the state file and emits one of:
  - `BRIEFING_CITY=<value>` + `BRIEFING_SUPPRESSED=false` (normal day)
  - `BRIEFING_SUPPRESSED=true` + `BRIEFING_REASON=...` (vacation active)

To wire it up:

1. Add a section to `morning-briefing.prompt.txt` instructing the agent to:
   - Use `BRIEFING_CITY` in the weather curl (`?city=$BRIEFING_CITY`)
   - Respond with only `[SILENT]` when `BRIEFING_SUPPRESSED=true`
2. Recreate the cron with `--script`:

```bash
hermes cron create "0 7 * * 1-5" "$(cat ~/SourceRoot/claude-local/hermes/cron/morning-briefing.prompt.txt)" \
  --skill tasks \
  --skill schedule \
  --skill weather \
  --skill infrastructure \
  --skill slack \
  --script ~/SourceRoot/claude-local/hermes/cron/briefing-context.py \
  --name "Morning briefing" \
  --deliver slack:C0AT6TH404R
```

Workflow once wired:
- Working remote in Berlin: edit `briefing-state.json` → set `"city": "Berlin"`, commit. Briefing auto-uses Berlin weather. Reset to Munich when back.
- Vacation 5–15 May: set `"vacation_until": "2026-05-15"`, commit. Briefing skips until 16 May, then auto-resumes.
- For one-off skips, `hermes cron pause <id>` is simpler — no state file edit needed.
