---
name: garmin-health
description: Garmin-derived health signals — daily metrics (HRV, sleep, RHR, body battery, stress), activities, recovery score, training-load (ACWR), fitness direction, weight log, and user profile. Use for recovery, body, and passive-measurement questions
version: 1.0.0
metadata:
  hermes:
    tags: [garmin, hrv, recovery, sleep, rhr, body-battery, stress, training-load, acwr, fitness-direction, weight, profile, health]
    related_skills: [strength, argo-api]
---

# Garmin Health

Daily Garmin metrics, derived recovery signals, weight log, and user profile.
For lifting sessions, strength sets, and the Strength analytics suite (`/workouts/summary/*`), use the `strength` skill.

**Base URL:** `https://argo.jkrumm.com/api`
**Auth:** `Authorization: Bearer $HOMELAB_API_KEY`

---

## Quick Commands

```bash
# Most-recent recovery snapshot — single weighted score
curl -s -H "Authorization: Bearer $HOMELAB_API_KEY" "https://argo.jkrumm.com/api/recovery"

# Last 7+ days of daily metrics (HRV, sleep, RHR, body battery, stress)
curl -s -H "Authorization: Bearer $HOMELAB_API_KEY" "https://argo.jkrumm.com/api/daily-metrics?order=desc&limit=14"

# Latest-day summary snapshot
curl -s -H "Authorization: Bearer $HOMELAB_API_KEY" "https://argo.jkrumm.com/api/daily-metrics/summary"

# Garmin-sync state (queued? running? last success?)
curl -s -H "Authorization: Bearer $HOMELAB_API_KEY" "https://argo.jkrumm.com/api/daily-metrics/sync-status"

# Trigger an on-demand sync
curl -s -X POST -H "Authorization: Bearer $HOMELAB_API_KEY" "https://argo.jkrumm.com/api/daily-metrics/refresh"

# Training load — ACWR series + zones
curl -s -H "Authorization: Bearer $HOMELAB_API_KEY" "https://argo.jkrumm.com/api/training-load"

# Fitness direction (14-day HRV+RHR regression)
curl -s -H "Authorization: Bearer $HOMELAB_API_KEY" "https://argo.jkrumm.com/api/fitness-direction"

# Recent activities
curl -s -H "Authorization: Bearer $HOMELAB_API_KEY" "https://argo.jkrumm.com/api/activities?order=desc&limit=10"

# Weight: current + trend
curl -s -H "Authorization: Bearer $HOMELAB_API_KEY" "https://argo.jkrumm.com/api/weight-log/summary"

# Weight time-series for a range
curl -s -H "Authorization: Bearer $HOMELAB_API_KEY" "https://argo.jkrumm.com/api/weight-log/series?dateFrom=2026-01-01"

# Add weight entry
curl -s -X POST -H "Authorization: Bearer $HOMELAB_API_KEY" -H "Content-Type: application/json" \
  -d '{"date":"2026-05-13","weight_kg":70.4}' \
  "https://argo.jkrumm.com/api/weight-log"

# Profile (height, birth, gender, goal weight)
curl -s -H "Authorization: Bearer $HOMELAB_API_KEY" "https://argo.jkrumm.com/api/user-profile"

# Update profile
curl -s -X PUT -H "Authorization: Bearer $HOMELAB_API_KEY" -H "Content-Type: application/json" \
  -d '{"goal_weight_kg":75}' \
  "https://argo.jkrumm.com/api/user-profile"
```

---

## Endpoint Reference

### Daily metrics (HRV, sleep, RHR, body battery, stress)
| Method | Path | Key params | Description |
|-|-|-|-|
| GET | `/daily-metrics` | `dateFrom?`, `dateTo?`, `order?`, `page?`, `limit?` | Daily Garmin rows, newest first when `order=desc` |
| GET | `/daily-metrics/summary` | — | Latest-day snapshot |
| GET | `/daily-metrics/series` | `dateFrom?`, `dateTo?` | Time-series across the date range |
| GET | `/daily-metrics/sync-status` | — | Garmin-sync state (queued / in-progress / last success) |
| POST | `/daily-metrics/refresh` | — | Trigger an on-demand Garmin sync |

### Activities (Garmin-recorded sessions, not strength workouts)
| Method | Path | Key params | Description |
|-|-|-|-|
| GET | `/activities` | `dateFrom?`, `dateTo?`, `order?`, `sort?` (`start_time_local`/`date`/`duration_sec`/`calories`), `page?`, `limit?` | Activity list |
| GET | `/activities/summary` | — | Rolled-up activity counts + duration |

### Derived recovery signals
| Method | Path | Description |
|-|-|-|
| GET | `/recovery` | Composite recovery score for most recent date. **Weights:** HRV 40% + Sleep 35% + RHR 25%, minus strain-debt penalty from yesterday's activity score |
| GET | `/recovery/series` | Recovery score time-series (params: `dateFrom?`, `dateTo?`) |
| GET | `/training-load` | Daily activity score → EWMA acute (~7d) + chronic (~28d), ACWR + zones |
| GET | `/fitness-direction` | 3-level signal from 14-day RHR + HRV linear regression |

### Weight log
| Method | Path | Key params | Description |
|-|-|-|-|
| GET | `/weight-log` | `order?` | All weight entries |
| GET | `/weight-log/summary` | — | Current + ma7 + ma30 + trend + phase + intensity |
| GET | `/weight-log/series` | `dateFrom?`, `dateTo?` | Time-series for a range |
| POST | `/weight-log` | `date!`, `weight_kg!` | Add entry |
| DELETE | `/weight-log/{id}` | — | Delete entry |

### User profile
| Method | Path | Key body | Description |
|-|-|-|-|
| GET | `/user-profile` | — | Single row (height, birth, gender, goal weight) — auto-created on first access |
| PUT | `/user-profile` | `height_cm?`, `birth_date?`, `gender?`, `goal_weight_kg?` | Update profile fields |

---

## Decision Tree

**"How did I sleep?" / "HRV trend?" / "Resting HR?" / "Body battery?"**
→ `/daily-metrics?order=desc&limit=14` — read today's row for last night's sleep + HRV
→ Compute 7-day averages from non-null fields for trend arrows

**"Recovery score?" / "Am I recovered?"**
→ `/recovery` for the latest composite. For trend: `/recovery/series?dateFrom=...`

**"Training load?" / "Am I overtraining?"**
→ `/training-load` returns ACWR series. Use `/recovery` for the day's load-adjusted state.

**"Fitness trending up or down?"**
→ `/fitness-direction` — 3-level signal (improving / maintaining / declining)

**"Did Garmin sync today?" / "Are metrics stale?"**
→ `/daily-metrics/sync-status` — check `lastSuccessAt` + `in_progress`. Trigger `/daily-metrics/refresh` if stale and the user asks.

**"What did I weigh last week?" / "Goal weight?" / "Bulk progress?"**
→ `/weight-log/summary` for current + trend; `/user-profile` for goal
→ Series for charts: `/weight-log/series?dateFrom=...`

**"Ready to train hard today?" — cross-skill**
→ This belongs in the `strength` skill: `/workouts/summary/readiness` combines `/recovery` with fatigue debt from recent lifting sessions. See `strength`.

---

## Response Envelope (listing endpoints)

`/daily-metrics`, `/activities`, and `/weight-log` (the GET-list forms) return `{data: [...], total: N}`. Always read `response.data` for the row array; `response.total` is the un-paginated row count.

Detail / aggregate / summary endpoints — `/daily-metrics/{summary,series,sync-status}`, `/activities/summary`, `/weight-log/{summary,series,{id}}`, `/recovery`, `/recovery/series`, `/training-load`, `/fitness-direction`, `/user-profile` — return bare objects (their own per-endpoint shapes, see below).

## Field Semantics

### `/daily-metrics` row (one per date)
Today's row holds the **night that just ended** + **today's resting HR + body battery range**. Yesterday's row holds the night two nights ago. Reading sleep from yesterday's row and calling it "last night" is off by 24h.

| Field | Meaning |
|-|-|
| `date` | `YYYY-MM-DD` — Garmin's daily bucket |
| `sleep_duration_min` | Total sleep last night (minutes) |
| `sleep_score` | 0–100, ≥85 deep, 70–84 solid, 55–69 light, <55 rough |
| `hrv_last_night_avg` | ms — last-night average. Trend over 7d matters more than absolute |
| `hrv_status` | Garmin label: `BALANCED` / `LOW` / `UNBALANCED` / `POOR` |
| `resting_hr` | bpm. **Lower is better** — invert arrow semantics (↓ = good) |
| `bb_charged` | Body battery at start of waking day |
| `bb_lowest` | Body battery low point during waking day (end-of-day proxy at 22:00) |
| `bb_highest` | Body battery peak |
| `stress_avg` | Average stress 0–100 |

**Null handling:** at 07:00 the morning row may be partial — last-night sleep usually present, today's RHR/BB still partial. **Do not substitute yesterday's row** when today's field is null. Say "data still syncing" instead.

### `/recovery` score
- Range 0–100, weights HRV 40 / Sleep 35 / RHR 25
- Capped at the 90th-percentile of recent activity scores (the strain-debt ceiling)
- `driver` field names the dominant input ("hrv", "sleep", "rhr") — useful for "why is recovery low?" answers

### `/training-load` ACWR zones (Gabbett 2016)
| ACWR | Zone | Interpretation |
|-|-|-|
| < 0.8 | undertrained | room to push |
| 0.8–1.3 | optimal | the sweet spot |
| 1.3–1.5 | caution | watch fatigue |
| > 1.5 | danger | injury-risk territory |

### `/fitness-direction`
RHR slope < −0.05 bpm/day → improving (RHR dropping); HRV slope > +0.10 ms/day → improving. Composite signal: `improving | maintaining | declining`.

### `/weight-log/summary` fields
| Field | Meaning |
|-|-|
| `current` | Latest entry (kg) |
| `ma7`, `ma30` | 7-day / 30-day moving average |
| `trend` | `gaining` / `losing` / `flat` |
| `weeklyDelta`, `monthlyDelta` | kg vs same lookback |
| `kgPerWeek` | Current rate |
| `phase` | `gaining` / `losing` / `maintaining` — derived from goal_weight vs current |
| `intensity` | Human label, e.g. "Standard bulk", "Mild cut" |

---

## Response Formatting

- **Recovery/HRV trend**: Lead with today's value, the 7-day average, and a directional arrow (↑ ≥5% above, ↓ ≥5% below, = otherwise). RHR uses inverted arrows (lower = good = ↓).
- **Weight queries**: One line — current, 7d MA, weekly delta, phase. Don't list every entry unless asked.
- **Sleep**: Duration + quality word from sleep_score thresholds. Avoid sentence-long preambles.
- **Sync-status**: One line with "synced X minutes ago" (relative to `lastSuccessAt`), flag stale-sync if > 6h.
- **Don't moralize** — neutral framing ("HRV trending down, recovery score 58") beats "you're overtraining, slow down!".

---

## Notes

- Today's metrics finalize through the morning — at 07:00 expect HRV + sleep populated, RHR + body battery partial.
- All Garmin Health endpoints are read-only except `/daily-metrics/refresh`, `/weight-log` (POST/DELETE), and `/user-profile` (PUT).
- For ad-hoc analytics not in a named endpoint, fall back to the `/query` SQL endpoint via `argo-api` skill.
- Query-param convention is camelCase (`dateFrom`, `dateTo`, `order`); legacy json-server forms (`_order`, `_start`, `_end`) still work as aliases.
