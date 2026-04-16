---
name: weather
description: Get weather forecast for Munich — current conditions, 48h hourly detail, 7-day daily overview with rain, clouds, temperature, UV index, and wind
version: 1.0.0
metadata:
  hermes:
    tags: [weather, forecast, rain, temperature, uv, wind, clouds]
    related_skills: [homelab-api]
---

# Weather

Weather forecast for Munich via the homelab API. Data sourced from Open-Meteo (DWD/ECMWF models).

**Endpoint:** `GET https://api.jkrumm.com/weather/forecast`
**Auth:** `Authorization: Bearer $HOMELAB_API_KEY`

Use this skill when Johannes asks about weather, temperature, rain, whether to bring an umbrella, UV protection, wind conditions, or weekend plans that depend on weather.

---

## What You Get

Single call returns everything:

| Section | Content |
|-|-|
| `current` | Right now: temp, feels-like, humidity, cloud cover, wind, UV, precipitation, condition |
| `hourly_48h` | Next 48 hours, hourly: temp, feels-like, rain probability + amount, clouds, UV, wind, condition |
| `daily_7d` | Next 7 days, daily: temp range, precipitation total + probability, max wind + gusts, max UV, condition, sunrise/sunset |

## Usage

```bash
curl -s -H "Authorization: Bearer $HOMELAB_API_KEY" "https://api.jkrumm.com/weather/forecast"
```

## How to Respond

- **Quick check** ("how's the weather?"): current conditions + today's outlook in 2-3 lines
- **Detailed today/tomorrow**: use hourly data — highlight rain windows, UV peaks, wind changes
- **Weekend/week ahead**: use daily data — summarize each day in one line (condition, temp range, rain chance)
- **Activity planning** ("can I bike tomorrow?", "BBQ on Saturday?"): pull relevant metrics (rain probability, wind, UV) and give a clear yes/no with reasoning
- Always mention UV index if > 3 (sunscreen territory) or > 6 (avoid midday sun)
- Wind gusts > 50 km/h are worth flagging
- Precipitation probability > 40% = bring an umbrella

## Notes

- Location is fixed to Munich — no location parameter needed
- Temperatures in °C, wind in km/h, precipitation in mm
- `condition` field is already human-readable (translated from WMO weather codes)
- Data updates roughly every hour from Open-Meteo
