---
name: home
description: Control and diagnose Apple Home (HomeKit) — lights, outlets, sensors, scenes, automations, accessories showing "No Response" — via the `home` CLI (HomeClaw on this mini). Use when Johannes asks to switch lights, run a scene (Chill, Hell, TV, Aus, Arbeit, Bett Hell, Bett Dunkel), asks what is on, what is broken or offline in the home, about motion sensors, Hue, Eve, Meross, or the dog-alone lighting (Nami).
version: 1.0.0
metadata:
  hermes:
    tags: [home, homekit, apple-home, lights, scenes, smart-home, hue, eve]
    related_skills: [human-queue]
---

# Home — Apple Home via HomeClaw

`home` (`~/.local/bin/home`, repo `~/SourceRoot/home`) wraps `homeclaw-cli`,
which talks to the HomeClaw app running in this mini's GUI session. Output is
JSON when piped.

```bash
home doctor                      # not responding, low battery, drop-offs (24 h)
home scenes                      # [{name, id, rooms, action_count}]
home trigger "Chill"             # run a scene
home device-map                  # rooms, semantic types, aliases — read before acting on a name
home list --room Wohnzimmer      # accessories + state
home get "Sofa"
home set "Sofa" power true       # power | brightness 0-100 | color_temperature
home set "Sofa" brightness 40 --dry-run
home automations                 # automations get "<name>" for detail
home events --since 1d           # what changed, what dropped off
```

## Rules

- **Do what was asked, nothing more.** A light or scene request is executed
  directly and reported in one line ("Chill an — Wohnzimmer"). Deleting
  scenes, removing accessories, editing or disabling automations: only on an
  explicit request, `--dry-run` first.
- **Names repeat across rooms** (`Bett`, `Esstisch`, `Küche`,
  `Schreibtisch`). Resolve with `home device-map`; if two match and the room
  is unclear, ask once.
- `live refresh failed` → retry the read with `--no-refresh` (last-known).
- `home: HomeClaw unreachable` → the HomeClaw app is not running on the
  mini. Report it; Johannes restarts it. Do not retry-loop.
- "What's broken?" → `home doctor`, then one line per accessory: room, name,
  brand, likely cause (Wi-Fi brand after the router swap: re-provision on
  2.4 GHz; Eve/Thread: power-cycle; via Hue Bridge: fix in the Hue app).
