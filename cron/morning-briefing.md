# Morning Briefing — Hermes Cron Job

Source-of-truth for the morning briefing prompt. **This file is documentation, not auto-loaded.** Hermes cron jobs live in `~/.hermes/cron/jobs.json`, created via `hermes cron create` or the `cronjob` tool. Update both this file and the live job when iterating.

## Job Spec

| Field | Value |
|-|-|
| Schedule | `0 7 * * 1-5` (07:00 weekdays, Europe/Berlin) |
| Skills | `tasks`, `schedule`, `weather`, `infrastructure`, `slack`, `homelab-api` |
| Pre-run script | `briefing-context.py` (lives in `~/.hermes/scripts/`, source in `hermes/scripts/`) |
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
  --skill homelab-api \
  --script briefing-context.py \
  --name "Morning briefing" \
  --deliver slack:C0AT6TH404R

# Trigger immediately for testing
hermes cron run <job_id>

# Edit prompt only
hermes cron edit <job_id> --prompt "$(cat ~/SourceRoot/claude-local/hermes/cron/morning-briefing.prompt.txt)"
```

`--script briefing-context.py` is a *bare filename* — Hermes resolves it under `~/.hermes/scripts/` and rejects absolute paths that escape that directory.

The prompt is kept as a separate `.prompt.txt` file (sibling to this doc) so it can be piped into the CLI without escaping.

## What It Does

Every weekday at 07:00 a fresh Hermes session:

1. Pre-run script (`briefing-context.py`) emits `BRIEFING_CITY=…` + `BRIEFING_SUPPRESSED=true|false` from `briefing-state.json`. On vacation the agent short-circuits with `[SILENT]`.
2. Fires 10 parallel curls/`gh` calls — `/summary`, both Docker summaries, calendar, weather (city from script), recent #alerts, `/daily-metrics/` (Garmin), `/workouts/` (strength), open PRs, open issues
3. Composes a structured Slack mrkdwn body (English, emoji-headed sections, bullet lists) — including a `:weight_lifter: Health & Training` section with last workout, recovery (HRV / Body Battery / resting HR), brief sleep, and a synthesized coaching line
4. Composes a separate German narrative (~150–200 words, conversational, four paragraphs incl. *Körper & Training*)
5. Calls TTS on the narrative → MP3 + `MEDIA:` tag
6. Returns the structured text body + `MEDIA:` tag — Slack delivers both text and audio attachment

## Tone & Format

**Text body (Slack mrkdwn, English):**
- Sections: Weather → Schedule → Infrastructure → Alerts → Health & Training → GitHub → Tasks
- Emoji shortcode headers (`:sunny:`, `:date:`, `:hammer_and_wrench:`, `:rotating_light:`, `:weight_lifter:`, `:octocat:`, `:checkered_flag:`)
- Bullet lists with `-`, project emojis for tasks (`:briefcase:`, `:house:`, `:innocent:`)
- Concise: short dates ("Apr 17"), one-line bullets where possible

**Audio narrative (German, separate text — only fed to TTS):**
- Warm conversational, no greeting / no name
- Four paragraphs: Wetter+Termine, Infrastruktur+Alerts, **Körper+Training**, Aufgaben+GitHub
- Times spoken naturally ("Viertel nach neun"); weights spelled out ("neunzig Kilo")
- ~150–200 words / ~70–90s spoken

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

## Location + vacation state

Two files in `hermes/scripts/`:

- **`briefing-state.json`** — *gitignored*, runtime state. Edited locally; never commits. Schema: `{"city": "Munich", "vacation_until": null}`. `make hermes` seeds this from the example on first install if it doesn't exist; subsequent edits stay local.
- **`briefing-state.example.json`** — *tracked*, canonical default. Reference for the schema and a fresh-install seed.
- **`briefing-context.py`** — pre-run script. Reads `briefing-state.json` and emits one of:
  - `BRIEFING_CITY=<value>` + `BRIEFING_SUPPRESSED=false` (normal day)
  - `BRIEFING_SUPPRESSED=true` + `BRIEFING_REASON=...` (vacation active)
  - If the state file is missing entirely, emits `BRIEFING_CITY=Munich` + `BRIEFING_SUPPRESSED=false` and continues.

The cron job is wired with `--script briefing-context.py`. The prompt's *Step 0* tells the agent to read `## Script Output`, pass the city to `/weather/forecast?city=<value>`, and short-circuit with `[SILENT]` when suppressed.

Workflow:
- Working remote in Berlin: edit `briefing-state.json` locally → set `"city": "Berlin"`. Save. Briefing auto-uses Berlin weather. Reset to Munich when back. **No commit needed.**
- Vacation 5–15 May: set `"vacation_until": "2026-05-15"`. Briefing skips until 16 May, then auto-resumes. **No commit needed.**
- For one-off skips, `hermes cron pause <id>` is simpler — no state file edit needed.

## Garmin ↔ strength training integration (current state)

The two data sources are siloed:

- **Garmin daily metrics** (`/daily-metrics/`) capture sleep, HRV, body battery, stress, resting HR, `vigorous_intensity_min`, `moderate_intensity_min`. Sync is overnight + on-demand from the watch — at 07:00 last night's sleep score is often missing (use the most-recent non-null value).
- **Strength workouts** (`/workouts/`) are manually logged via the homelab API. Exercises are pinned to four categories (`push`, `pull`, `legs`, `hinge`). No row-level link to a Garmin activity.
- Garmin's auto-detection rarely catches strength sessions as `vigorous_intensity_min` — a bench press session shows up as 0 vigorous minutes if the watch wasn't started in Strength mode.

The morning briefing bridges this in *prompt-space* (the LLM looks at last-workout date + recovery state and synthesizes a coaching line), not in the data layer. Future work, if useful: a sync that promotes a logged workout into a Garmin "Strength Training" activity, or pulls Garmin Training Readiness / Training Status fields when those land in `garmin-sync`.
