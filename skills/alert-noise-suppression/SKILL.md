---
name: alert-noise-suppression
description: Use when an alert family keeps firing benignly.
version: 1.0.0
metadata:
  hermes:
    tags: [alerts, false-positive, suppression, triage, ignore, ingest-filter, thresholds, monitoring, warden]
    related_skills: [warden, hermes-log-alert-forensics, alert-liveness-forensics, alert-mechanism-forensics, homelab-ops]
---

# Alert noise: cut it at the layer that owns the distinction

A recurring alert has two halves: a **producer** that emits a signal, and a **gate**
that turns signals into cards, items and dispatches. Suppression belongs to whichever
layer can still tell the benign instance from the real one. Pick the deepest layer
that keeps that distinction — never the shallowest one that merely hides it.

This is the second half of triage: `alert-liveness-forensics` decides whether a
signal is still live, `alert-mechanism-forensics` why it fired, and this skill what
to do when the answer is "it is live, it is benign, and it will fire again".

## Procedure

1. **Prove the benign reading from raw producer evidence, not from the card.** A card
   is a projection: it is rendered from a state column, and its `×N` counts *matched
   lines*, not incidents. Read the producer's own output for the firing — the log
   lines and their session/trace id, the metric series, the trace — and establish the
   real count before anything else. A family whose "3 occurrences" is really one
   event has no suppression problem at all, only a discharge.
2. **Name the discriminating token** — the field in the raw signal that separates the
   benign instance from the real one: a sentinel or placeholder id, a below-threshold
   direction, a "recovered / resolved" wording, a specific item name. If no such token
   exists, the family is **not** suppressible — escalate the design question instead of
   silencing a class of alerts.
3. **Choose the layer by where that token is still visible**, deepest first:
   - **the gate's own match logic** — cheapest and most precise; it drops the benign
     instance and leaves every real one alerting.
   - **the gate's static policy list** (an ignore/snooze/allowlist entry) — only when
     the key that list matches on carries the token intact; see the pitfall below.
   - **the producer** (log level, wording, exit code) — only when the line genuinely
     is not an error for *any* consumer. That is a change in another repo and it makes
     the evidence disappear for everyone, so say so explicitly when you choose it.
4. **Verify the change is not a blinding.** Run a positive case through the changed
   path — a synthetic instance of the family that is *real* — and assert it still
   reports. Make it a regression test in the repo that owns the gate, then run the
   repo's whole suite.
5. **Record the mechanism where the next session looks**: the discriminating token,
   the layer chosen and why the others were not, in the policy/commit/state-log entry
   and in the triage skill for that family. Change the gate's own documentation in the
   same pass — a filter nobody knows about reads as a gate that misses things.

## Pitfalls

- **A policy ignore/snooze list keyed on a truncated or derived id cannot
  discriminate — and it fails silently in the worst direction.** Gates typically build
  the dedup key by truncating the producer message (e.g. the first ~120 chars of
  `module: message`), which routinely cuts off exactly the field the decision needs. An
  entry for such a key suppresses the benign instance *and* every real one, forever, in
  the same silent stroke. Before writing an entry, compute and print the key the gate
  would actually match, and check the token is inside it.
- **A retry loop turns one event into N lines, and N landing exactly on the configured
  minimum is not a coincidence.** A family whose observed count equals the alert
  threshold is a producer/threshold mismatch, not a spike: the retry numbering
  (`attempt 1/3`, one session id, one trace) tells you it was a single unlucky event.
  Report the real count; never quote the card's inflated one.
- **A deliberate self-test is the classic benign producer.** A scheduled or
  post-change probe that drives a failure path on purpose (a placeholder model id, a
  missing file, a bad credential) produces exactly the shape of a real outage. Check
  whether the firing correlates with a deploy/restart/config change before treating it
  as an incident, and prefer filtering that specific sentinel over relaxing the family.
- **Suppressing at the gate is not the same as the producer being wrong.** Leaving a
  benign ERROR line in place is correct when other consumers need it. Say which side of
  that fence the fix is on, so nobody later "tidies" the producer and blinds the other
  consumers.
- **One discharge is not a fix.** Closing or snoozing the item stops *this* card; the
  family re-fires on its own cooldown. Do both, in this order: discharge the open item
  first (it has its own deadline and will otherwise escalate to a human), then land the
  gate change, then report the two as one outcome.
- **Never move a shared threshold to silence one benign case.** The threshold is a
  brake over the whole family; a per-instance filter is precise, a moved threshold is
  not.
- **Prefer the expressible proximity guard over the floor you cannot write.** A
  tile-sourced HyperDX alert (`"source": "tile"`) evaluates one window of a dashboard
  formula, so a traffic floor (`if(B < 30, 0, A/B)`) is *not* expressible in it —
  `numConsecutiveWindows` is, and it removes exactly the single-window blip while a
  real incident (which holds many consecutive bad windows) still fires. Do the
  arithmetic against the actual firings before picking a value: on a 52-span window a
  floor of 30 suppresses nothing, two consecutive windows keeps a 15-window outage and
  drops a 3-error blip. Check the units too — the field counts *consecutive evaluation
  windows* of the alert's own `interval`, so `2` is a doubling of the detection delay,
  not of the threshold.
- **`vps` observability noise is fully expressible and pre-approved**: warden's
  `config/triage-policy.json` gives `observability/**` `autoMergePaths`, `deploy:
  "hyperdx-apply"` and `autoDeploy: true` — the alert JSON in `vps` is the source of
  truth and the apply is the deploy. Recipe: edit
  `observability/alerts/<slug>.json`, then `HYPERDX_PROD_BASE_URL=https://hyperdx.<domain>
  HYPERDX_PROD_ACCESS_KEY=$HYPERDX_AGENT_ACCESS_KEY make hyperdx-apply ENV=prod` (that
  env-var pair short-circuits the script's `secrets-run read`; the agent key is the
  same credential the `hyperdx` MCP path uses). **`make hyperdx-apply FILES=...` skips
  alerts entirely** ("explicit dashboard files given") — scope it by editing one file
  and running the full apply, which is upsert-by-name and idempotent. Then read the
  alert back from `GET /api/api/v2/alerts`: the config lives in the server, so the file
  alone is not the verification.
- **A single-firing calibration is still a live monitor.** After applying, confirm the
  alert's own `state` on the API (it should read `OK`) and leave the discharge reason
  carrying the measured numbers — the next session cannot re-derive them from a card.

## Report shape

Verdict first: benign, discharged, and where the family was cut. Then one line per
finding — the mechanism, the layer chosen (and why not the others), the real count
against the card's. Close with the rest-state of the gate in one line (health, poller
ages, suites green). No PID dumps, no step-by-step narration.
