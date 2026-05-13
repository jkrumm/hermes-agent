---
name: strength
description: Strength training — workouts, sets, exercises, and the full per-exercise analytics suite (e1RM, INOL, ACWR, volume landmarks, readiness, deload signal, PRs). Use for lifting questions, training planning, and progression analysis
version: 1.0.0
metadata:
  hermes:
    tags: [strength, workouts, sets, exercises, e1rm, inol, acwr, volume, prs, readiness, deload, training]
    related_skills: [garmin-health, argo-api]
---

# Strength

Lifting sessions, sets, exercises, and the `/workouts/summary/*` analytics suite.
Recovery inputs (HRV, RHR, sleep, training-load, ACWR) come from the `garmin-health` skill. The `/workouts/summary/readiness` endpoint joins both worlds.

**Base URL:** `https://argo.jkrumm.com/api`
**Auth:** `Authorization: Bearer $HOMELAB_API_KEY`

---

## Quick Commands

```bash
# Last 5 workouts (newest first) with sets + computed metrics
curl -s -H "Authorization: Bearer $HOMELAB_API_KEY" \
  "https://argo.jkrumm.com/api/workouts?sort=date&order=desc&limit=5"

# Single workout with sets + computed e1RM per set
curl -s -H "Authorization: Bearer $HOMELAB_API_KEY" \
  "https://argo.jkrumm.com/api/workouts/123"

# Per-exercise summary (currentE1RM, bestE1RM, volume, trends)
curl -s -H "Authorization: Bearer $HOMELAB_API_KEY" \
  "https://argo.jkrumm.com/api/workouts/summary/strength"

# Compact sparkline arrays per exercise (last 20 e1RM, 10 weekly volume, 15 INOL)
curl -s -H "Authorization: Bearer $HOMELAB_API_KEY" \
  "https://argo.jkrumm.com/api/workouts/summary/sparklines"

# Personal records — running max per exercise + metric
curl -s -H "Authorization: Bearer $HOMELAB_API_KEY" \
  "https://argo.jkrumm.com/api/workouts/summary/records"

# Strength readiness for today (joins Garmin recovery + fatigue debt)
curl -s -H "Authorization: Bearer $HOMELAB_API_KEY" \
  "https://argo.jkrumm.com/api/workouts/summary/readiness"

# Deload signal — verdict ∈ {progress, monitor, deload}
curl -s -H "Authorization: Bearer $HOMELAB_API_KEY" \
  "https://argo.jkrumm.com/api/workouts/summary/deload-signal"

# Composite signals for one exercise (z-scored)
curl -s -H "Authorization: Bearer $HOMELAB_API_KEY" \
  "https://argo.jkrumm.com/api/workouts/summary/composite/{exerciseId}"

# All exercises (display_order sorted)
curl -s -H "Authorization: Bearer $HOMELAB_API_KEY" "https://argo.jkrumm.com/api/exercises"

# Log a workout with sets
curl -s -X POST -H "Authorization: Bearer $HOMELAB_API_KEY" -H "Content-Type: application/json" \
  -d '{"date":"2026-05-13","exercise_id":1,"sets":[
        {"set_number":1,"set_type":"warmup","weight_kg":40,"reps":10},
        {"set_number":2,"set_type":"work","weight_kg":90,"reps":5}
      ]}' \
  "https://argo.jkrumm.com/api/workouts"
```

---

## Endpoint Reference

### Exercises + workouts CRUD
| Method | Path | Key params / body | Description |
|-|-|-|-|
| GET | `/exercises` | — | All exercises, `display_order` sorted |
| GET | `/workouts` | `dateFrom?`, `dateTo?`, `exercise?`, `sort?` (`date`/`id`/`exercise_id`/`created_at`), `order?`, `page?`, `limit?` | List workouts |
| GET | `/workouts/{id}` | — | Workout with sets + computed e1RM |
| POST | `/workouts` | `date!`, `exercise_id!`, `sets![]`, `notes?` | Create workout with sets (transactional) |
| PATCH | `/workouts/{id}` | `date?`, `exercise_id?`, `notes?`, `sets?` | Update workout |
| DELETE | `/workouts/{id}` | — | Delete workout + cascade sets |
| GET | `/workout-sets` | `workoutId?`, `order?`, `page?`, `limit?` | List workout sets |
| POST | `/workout-sets` | `workout_id!`, `set_number!`, `set_type!`, `weight_kg!`, `reps!` | Create set |
| PATCH | `/workout-sets/{id}` | `set_number?`, `set_type?`, `weight_kg?`, `reps?` | Update set |
| DELETE | `/workout-sets/{id}` | — | Delete set |

### Strength analytics — `/workouts/summary/*`
| Path | What it returns | When to call |
|-|-|-|
| `/strength` | Per-exercise aggregates: `currentE1RM`, `bestE1RM`, volume, trends | "How strong am I right now?" / per-exercise overview |
| `/series` | Strength time-series by exercise | Charts / "show progression" |
| `/series-detailed` | Per-session: e1RM, 30d MA, INOL, max weight, best set, volume | Deep per-session view |
| `/sparklines` | Last 20 e1RM, last 10 weekly volume totals, last 15 INOL; `vel` = %/day velocity; `dir` = strength direction | Compact one-line trends |
| `/records` | Running-max PRs per exercise + metric | "What PRs have I set?" |
| `/relative-progression` | Best-of-day e1RM as % change from first-in-window baseline | "How much have I progressed?" |
| `/weekly-volume` | Weekly tonnage by `set_type` (warmup/work/drop/amrap) + 4-week trailing MA + MEV/MAV/MRV (p25/p50/p90) landmarks | Volume planning |
| `/training-load` | Per-exercise ACWR series (EWMA acute / chronic of weekly tonnage). Zones: undertrained (<0.8), optimal (0.8–1.3), caution (1.3–1.5), danger (>1.5) | "Am I pushing too hard on bench?" |
| `/heroes` | Hero composites for the strength tracker dashboard | Dashboard summary |
| `/composite/{exerciseId}` | Z-scored composite signals for a single exercise | Per-exercise drill-down |
| `/alignment` | 3×3 matrix bucketing sessions by recovery row × ACWR column over 90 days | "Am I lifting when recovered?" |
| `/deload-signal` | Verdict + active signal list (stall, overload, fatigue, physio) over 90 days. ≥2 → `deload`, =1 → `monitor`, =0 → `progress` | "Should I deload?" |
| `/readiness` | Per-day strength readiness from Garmin recovery + fatigue debt within 48h; `driver` names the limiting input. Empty `points` if < 7 daily-metric rows in window | "Ready to train hard today?" |

---

## Decision Tree

**"Show me my last N workouts"**
→ `/workouts?sort=date&order=desc&limit=N`
→ Each entry includes sets and computed e1RM; pull the heaviest work set per session for headlines

**"What's my current bench/squat/deadlift?" / "Per-exercise overview"**
→ `/workouts/summary/strength` — `currentE1RM` + `bestE1RM` per exercise in one call

**"Show progression over time"**
→ `/workouts/summary/series` (per-exercise series), or `/series-detailed` if INOL + best-set context needed
→ Use `/sparklines` for a tiny inline trend line

**"What PRs have I set this month?"**
→ `/workouts/summary/records`

**"Am I ready to train hard today?"**
→ `/workouts/summary/readiness` — single call combines Garmin recovery + fatigue debt. Look at `points[0].readiness` and `points[0].driver`.
→ If `points` is empty (< 7 daily-metric rows), fall back to `/recovery` from `garmin-health`.

**"Should I deload?" / "Am I cooked?"**
→ `/workouts/summary/deload-signal` — verdict ∈ {`progress`, `monitor`, `deload`} plus the list of active signals

**"Am I lifting when recovered?" / "Training/recovery alignment?"**
→ `/workouts/summary/alignment` — 3×3 matrix

**"How's my volume on X?" / "Am I above MAV?"**
→ `/workouts/summary/weekly-volume` — includes MEV/MAV/MRV landmarks per exercise

**"Bench-press ACWR?" / "Am I overloading squat?"**
→ `/workouts/summary/training-load` — per-exercise ACWR. Note this is *strength-specific* (weekly tonnage); the Garmin `/training-load` endpoint covers whole-body activity load.

**"Log this workout"**
→ POST `/workouts` with sets array in one transactional call. Resolve `exercise_id` from `/exercises` if needed.

---

## Field Semantics

### Set types
| `set_type` | Counts towards |
|-|-|
| `warmup` | Excluded from work-volume metrics |
| `work` | Primary volume driver |
| `drop` | Drop-set after a work set |
| `amrap` | "As many reps as possible" — terminal set |

### e1RM (estimated 1RM)
Computed per set on the server (Epley-style). Per-workout, the **best set's** e1RM becomes the day's e1RM. Sparkline + series endpoints use best-of-day.

### INOL
Volume-intensity metric used in `/series-detailed` + `/sparklines`. Higher = more taxing session.

### ACWR (per-exercise, strength-only)
EWMA(4-week) / EWMA(16-week) of weekly tonnage. Zones identical to whole-body Garmin ACWR — see thresholds in the `/training-load` row of the endpoint table.

### Volume landmarks (per exercise, from `/weekly-volume`)
- `MEV` (minimum effective volume) = p25 of trailing weekly tonnage
- `MAV` (maximum adaptive volume) = p50
- `MRV` (maximum recoverable volume) = p90

### Readiness driver values (`/readiness.points[].driver`)
Names the limiting input: `"recovery"`, `"fatigue"`, `"both"`. `null` driver = readiness score itself was null (incomplete data).

---

## Response Formatting

- **Workout list**: one line per session — date, exercise, heaviest work set, est. 1RM. Group consecutive same-day sessions if any.
- **Readiness query**: lead with the single verdict ("Go hard / Manage / Hold off"), then HRV + fatigue-debt drivers in one line. Don't dump the full `points` array.
- **Deload signal**: lead with verdict + active signals; if `progress`, one line is enough.
- **Per-exercise overview**: short table with one row per exercise — `currentE1RM`, `bestE1RM`, last-session date.
- **Don't dump raw weekly-volume arrays** — summarize: "Bench week 18: 3,200 kg, above MAV". Hide the landmark math unless asked.
- **PRs**: prefer "new bench PR May 11: 105 kg × 3 (e1RM 116 kg)" over JSON dumps.

---

## Notes

- Query params are camelCase (`dateFrom`, `dateTo`); legacy json-server forms (`_sort`, `_order`, `_start`, `_end`) still work as aliases for backwards compat with the morning briefing's prompt.
- `/workouts/summary/training-load` is **strength-specific** (per-exercise weekly tonnage). The Garmin `/training-load` (in `garmin-health`) covers whole-body activity score. Don't mix them.
- For training planning that needs both recovery state + strength fatigue, prefer `/workouts/summary/readiness` over computing it yourself.
- `/workouts/summary/alignment` returns a 3×3 grid; treat it as a heatmap, not a single number.
- `/exercises` is small (~10 entries) — cache mentally for the session if you need IDs.
