---
name: weather
description: Get weather forecast for any city (default Munich) — current conditions, 48h hourly detail, 7-day daily overview with rain, clouds, temperature, UV index, and wind
version: 1.1.0
metadata:
  hermes:
    tags: [weather, forecast, rain, temperature, uv, wind, clouds]
    related_skills: [homelab-api]
---

# Weather

Weather forecast for any city via the homelab API. Defaults to Munich. Data sourced from Open-Meteo (DWD/ECMWF models).

**Endpoint:** `GET https://api.jkrumm.com/weather/forecast`
**Query:** `?city=<name>` (optional, default `Munich`) — any city name; geocoded via Open-Meteo
**Auth:** `Authorization: Bearer $HOMELAB_API_KEY`

Use this skill when Johannes asks about weather, temperature, rain, whether to bring an umbrella, UV protection, wind conditions, or weekend plans that depend on weather — for Munich or any other city.

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
# Default — Munich
curl -s -H "Authorization: Bearer $HOMELAB_API_KEY" "https://api.jkrumm.com/weather/forecast"

# Any other city
curl -s -H "Authorization: Bearer $HOMELAB_API_KEY" "https://api.jkrumm.com/weather/forecast?city=Salzburg"
```

Response includes resolved `city` and `country` so you can confirm the geocoder picked the right place. A 400 is returned if the city can't be geocoded.

## How to Respond

- **Quick check** ("how's the weather?"): current conditions + today's outlook in 2-3 lines
- **Detailed today/tomorrow**: use hourly data — highlight rain windows, UV peaks, wind changes
- **Weekend/week ahead**: use daily data — summarize each day in one line (condition, temp range, rain chance)
- **Activity planning** ("can I bike tomorrow?", "BBQ on Saturday?"): pull relevant metrics (rain probability, wind, UV) and give a clear yes/no with reasoning
- Always mention UV index if > 3 (sunscreen territory) or > 6 (avoid midday sun)
- Wind gusts > 50 km/h are worth flagging
- Precipitation probability > 40% = bring an umbrella

## Notes

- Default location is Munich — pass `?city=<name>` for anywhere else (e.g. `Salzburg`, `Berlin`, `Hamburg`)
- Geocoding handles fuzzy matches and accents; pick the more specific name if multiple cities share a name (e.g. `Frankfurt am Main` vs `Frankfurt an der Oder`)
- Temperatures in °C, wind in km/h, precipitation in mm
- `today` is in the resolved city's local timezone, not always Europe/Berlin
- `condition` field is already human-readable (translated from WMO weather codes)
- Data updates roughly every hour from Open-Meteo
