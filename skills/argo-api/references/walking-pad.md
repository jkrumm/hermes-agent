# WalkingPad — treadmill sessions, live state, analytics

Walking-treadmill-desk tracking. Passive activity data, like Garmin Health —
**read-only for Hermes** (the device ingests sessions itself; Hermes never pushes).

**Base:** `https://argo.jkrumm.com/api` · **Auth:** `Authorization: Bearer $HOMELAB_API_KEY`

## When to route here

"How far / how long did I walk today / this week / this month?", "wie viel bin ich
gelaufen", "walking streak", "did I walk today", "treadmill stats", "pace trend".

> **Walk vs run.** WalkingPad = the desk treadmill (steps/distance/pace at a desk).
> Outdoor runs / Garmin activities are `references/garmin-health.md` (`/activities`).
> Don't merge the two — different sources, different intent.

## Decision tree

1. **"How much did I walk?"** → `GET /walking-pad/sessions/summary?dateFrom=&dateTo=`.
   One call, all the totals. Default window = the period implied ("today" → today,
   "this week" → last 7d). This is the first call for almost every question.
2. **"Am I on a streak / did I walk today?"** → `GET /walking-pad/sessions/heroes`
   (`streak.currentDays`, `streak.walkedToday`, `streak.sessionsThisWeek`).
3. **Trend over time / "is my pace improving?"** → `heroes` (`volume.direction`,
   `pace.direction` + deltas) for the headline; `sessions/series?bucket=day|week` for a chart.
4. **Pattern questions** ("when do I usually walk?") → `sessions/hour-of-day` (dow×hour matrix).
5. **Specific sessions** → `GET /walking-pad/sessions` (list, newest first).
6. **Right now** → `GET /walking-pad/live` — `snapshot` is `null` when no session is active.

## Field semantics (units matter — convert for display)

**`/walking-pad/sessions/summary`** (window totals):
`sessions` (count) · `duration_s` (seconds → **show minutes/hours**) · `distance_m`
(meters → **show km**) · `steps` · `kcal` · `avg_session_min` (already minutes).

**`/walking-pad/sessions`** → `{data: [...], total}`. Each session:
`uuid`, `started_at`/`ended_at` (ISO, UTC → Europe/Berlin), `duration_s`, `distance_m`,
`steps`, `avg_speed_kmh`, `max_speed_kmh`, `kcal`, `pause_count`, `created_at`.

**`/walking-pad/sessions/heroes`** (the dashboard headline):
- `volume`: `direction` (up/down/flat), `currentDistanceM`, `priorDistanceM`, `deltaPct`
- `pace`: `direction`, `currentAvgKmh`, `priorAvgKmh`, `deltaKmh`
- `streak`: `currentDays`, `bestDays`, `walkedToday` (bool), `momentum`, `sessionsThisWeek`

**`/walking-pad/sessions/series`** → `{bucket, points: [{date, sessions, duration_s, distance_m, steps, kcal, avg_speed_kmh}]}`.
**`/walking-pad/sessions/hour-of-day`** → `{cells: [{dow, hour, sessions, distance_m}], totalSessions}` (168 cells = 7×24).
**`/walking-pad/sessions/length-histogram`** → `{metric, buckets: [{bucketStart, bucketWidth, sessions}]}`.
**`/walking-pad/achievements`** → `{data: [{id, type, session_uuid, value, title, description, confetti, unlocked_at}]}`.

## Response formatting (Slack, German default)

- **Lead with the human numbers**: km (1 dp), total time as `Xh Ym` or `Z min`, step count,
  kcal. Never echo raw `duration_s`/`distance_m`.
- **Streak is motivating** — surface `streak.currentDays` + `walkedToday` when relevant
  ("4 Tage in Folge, heute schon gelaufen :+1:"). Don't manufacture pressure if not asked.
- **Trends**: state direction + the delta, not a table — "Distanz +12% ggü. Vorwoche,
  Pace etwa gleich".
- **Idle live snapshot** (`snapshot: null`) → "gerade keine aktive Session", not an error.
- Ad-hoc only — WalkingPad is **not** wired into the morning briefing or watchdog.

## Gotchas

- **List wrapper:** `/sessions` and `/achievements` return `{data: [...], total}` — read
  `.data` (same envelope as Garmin/Strength lists). `summary`/`heroes`/`series`/
  `hour-of-day`/`length-histogram` are bare objects.
- **All timestamps UTC** — convert to Europe/Berlin before display.
- **Writes are device-ingest only:** `POST /walking-pad/live`, `POST /walking-pad/sessions`,
  `DELETE /walking-pad/sessions/{uuid}` exist for the treadmill collector — Hermes does not
  push or delete sessions.
