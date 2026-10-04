---
name: hyperdx-alert-as-code
description: Use when changing a HyperDX alert or dashboard as code.
version: 1.0.0
metadata:
  hermes:
    tags: [hyperdx, clickstack, alerts, observability, alerts-as-code, vps, calibration]
    related_skills: [alert-noise-suppression, alert-liveness-forensics, hyperdx, warden]
---

# Changing a HyperDX alert as code

HyperDX alerts and dashboards are **declared state in the `vps` repo**, not UI state:
`observability/alerts/*.json` and `observability/dashboards/*.json` are the source of
truth, and `scripts/hyperdx-sync.sh` (through `make hyperdx-export` / `make hyperdx-apply`)
is the only writer. Warden's `config/triage-policy.json` gives `vps`'s `observability/**`
`autoMergePaths` with `deploy: hyperdx-apply` and `autoDeploy: true` — so a change confined
to those paths is pre-approved and lands without an owner click. **Whether** a family should
be changed at all is `alert-noise-suppression`; **how** the change is made is this skill.

## Procedure

1. **Export first — it makes the edit a diff against live state, and it surfaces drift.**

   ```bash
   cd ~/SourceRoot/vps
   set -a; source <(secrets-run export --env-file=$HOME/.hermes/.env.tpl | sed 's/^export //'); set +a
   export HYPERDX_PROD_BASE_URL="https://hyperdx.jkrumm.com" HYPERDX_PROD_ACCESS_KEY="$HYPERDX_AGENT_ACCESS_KEY"
   make hyperdx-export ENV=prod && git diff --stat
   ```

   That env pair short-circuits the script's own `secrets-run read op://vps/clickstack/AGENT_ACCESS_KEY`;
   the agent access key is the same credential the `hyperdx` SQL/MCP path already uses, so it
   arrives with the normal `.env.tpl` resolution. Drift on files you are not touching is the
   server normalizing its own documents — commit it separately or leave it, never inside the change.
2. **Edit the one file.** The fields that decide behaviour: `interval`, `threshold` +
   `thresholdType`, `numConsecutiveWindows`, `source` (`tile` | `savedSearch`), and the
   `dashboard` / `tile` / `savedSearch` / `channel.webhook` references — those are **names**,
   resolved to ids per environment at apply time.
3. **Apply with the full run, never a file list.**

   ```bash
   make hyperdx-apply ENV=prod
   ```

   `FILES=…` is the trap: an explicit list is treated as dashboards and the alerts pass is
   *skipped* (`skipping alerts (explicit dashboard files given)`). The full apply is
   upsert-by-name and idempotent — which is exactly why step 1 exported first.
4. **Verify from the service, never from the file.**

   ```bash
   curl -s -H "Authorization: Bearer $HYPERDX_AGENT_ACCESS_KEY" \
     "$HYPERDX_PROD_BASE_URL/api/api/v2/alerts"
   ```

   Read the alert's `interval`, `threshold`, `numConsecutiveWindows` and its `state` (should be
   `OK`). The configuration lives in the server; a green apply log line is not proof the row
   changed — the read-back is.
5. **Land it.** PR against `jkrumm/vps` with `--rebase` (squash merges are disabled on that
   repo), or let Warden's pre-approved path merge an episode PR. Then discharge the tracking
   item with the measured numbers in the reason — the next session cannot re-derive them from a card.

## Choosing the guard: express what the platform can actually evaluate

- A `"source": "tile"` alert evaluates the dashboard tile's formula over **one** window and
  cannot express a traffic floor (`if(B < 30, 0, A/B)`).
- `numConsecutiveWindows` **is** expressible on a tile alert and removes exactly the
  single-window blip: a transient spike clears on the next window, a real incident holds many
  consecutive bad windows. `2` doubles the detection delay, not the threshold.
- Do the arithmetic against the real firings before naming a value: a floor of 30 suppresses
  nothing on a 52-span window, while two consecutive windows keeps a 15-window outage and drops
  a 3-error blip. A number chosen without that arithmetic is a guess with a plausible shape.
- A genuine volume floor needs a `savedSearch`-sourced alert with a `HAVING total >= N` — a new
  saved search plus a rewritten alert. Say it is the bigger change rather than implying the tile
  can carry it.
- Excluding a path from the tile's numerator **and** denominator is the other expressible lever;
  it changes the dashboard for every viewer, so name that as the trade.

## Pitfalls

- **`make hyperdx-apply FILES=…` silently skips alerts** — see step 3. Scope a change by
  editing one file and running the full apply, not by passing a file list.
- **Ids do not cross environments.** Export writes source/connection/dashboard/tile/webhook
  references as names precisely because ids are per-env; hand-editing an id into a file makes
  apply fail in the other environment with the reference named.
- **A monitor's own probe path counts in an edge error ratio.** A CDN-origin probe (a resized
  image fetched through the internal bypass check rather than the public edge) lands as 5xx
  spans and can cross a 5% ratio on its own. Read the failing spans' paths before calling an
  application broken — this is also the cheapest candidate for a path exclusion.
- **Verify a "still firing" claim with spans, not alert text.** Re-run the ratio per window and
  name the errors behind the crossing bucket; the alert's message line carries no detail.
- **A change to a tile is a change to every alert sourced from it.** Check which alerts point
  at the tile before editing the query.
- **Export round-trips are asymmetric for server-owned fields** (`containers: []` and friends
  vanish), so a one-line diff on a dashboard you never touched is the server normalizing, not a
  defect you introduced.
