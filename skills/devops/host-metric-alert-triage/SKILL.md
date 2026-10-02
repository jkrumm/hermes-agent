---
name: host-metric-alert-triage
description: "Use when a host metric alert fires (temp, CPU, disk, load)."
version: 1.0.0
metadata:
  hermes:
    tags: [alert, temperature, thermal, cpu, memory, disk, load, beszel, monitoring, threshold, baseline, homelab, metrics]
    related_skills: [homelab-ops, warden, argo-api]
---

# Host metric alert triage

A host system-metric alert (temperature, CPU, memory, disk, load) is not
repo-readable and usually has no ops verb: the rule is configured in a monitoring
UI and its history lives in that service's own database. Diagnose it from there.

`references/beszel-host-metrics.md` carries the concrete store, schema and
ready-to-run read queries for this estate's host-metric provider (Beszel on the
homelab). Read it before answering any temperature/thermal question.

## Procedure

1. **Name the source before diagnosing.** `grep -rn` the repos for the alert
   string. **Zero matches is the expected result, not a phantom alert** — a
   UI-managed rule (Beszel hub + per-host agent) is not version-controlled, and the
   repo's own monitor config (uptime-kuma `monitors.yaml`) covers HTTP/Docker/push
   only. Say which component can produce the metric, then go to its store.
2. **Read the source's own store read-only instead of escalating.** The threshold,
   the sensor and the full firing history are one SSH + read-only SQLite read away
   (`references/beszel-host-metrics.md`). "A human must open the UI" is the wrong
   answer when the store is readable — the user should get the numbers, not the
   login wall. Open the DB `mode=ro` and never write to it.
3. **Pull two things before judging:** the rule row (`value` = threshold) and the
   metric's own baseline over the whole retention window (coarsest bucket, weeks).
   A threshold a few units *inside* the normal band fires on routine work (a
   nightly backup, a container recreate) and the finding is a **tuning** one.
4. **Check the shape, not the count.** Durations that `resolved` themselves are
   self-clearing flaps; correlate each with what ran then (container start times,
   scheduled jobs) before blaming ambient conditions.
5. **Then decide the class of finding** — tuning (threshold, the user's call),
   physical (cooling/airflow/disk, a human at the box), or a genuinely bad metric
   (memory pressure, disk fill, a wedged process).

## Rules

- **Judge the baseline against the hardware, not against the number's vibe.** An
  Intel N100 idling at ~84 °C package on load avg 0.3 is ~30 °C above typical →
  marginal cooling, the alert is correct and the action is physical. A baseline
  **flat over weeks** is the box's steady state, not accumulating dust — never sell
  a flat series as "recent degradation".
- **Report the frequency from the source's history table.** A triage card's
  "N× since <date>" only counts occurrences while its own item was in a live state,
  so it can understate by an order of magnitude; the provider's own history table is
  authoritative. Understating an alert's frequency is how a real pattern gets waved
  off as a one-off.
- **Never re-tune a monitoring threshold yourself.** Raising a threshold to silence
  an alert is a coverage decision on the user's own hardware; state the number, the
  baseline and the recommendation, and let him set it. Same for any write to the
  monitoring store.
- **Absent fan RPM is not a fanless box.** Many mini-PCs do not expose one in hwmon.
  Say "no fan sensor exposed", never "no fan".
- **Take a live second opinion from the kernel** (`/sys/class/thermal/thermal_zone*`,
  `/sys/class/hwmon/hwmon*/temp*_input`, `/proc/cpuinfo` for the CPU model, `uptime`
  for load) — it confirms the stored series and dates the current state.
- **Temperature is not in the argo API.** `/docker/*/summary` gives container counts
  and host CPU/RAM only; never answer a thermal question from argo.
- **Remediation is `homelab-ops` territory**: its bounded verbs and its
  `references/alert-patterns.md` (alert string → root cause → verb) own the fix.
  This skill owns the diagnosis and the numbers.

## Report shape

Verdict first, German, 3–6 lines: what actually fired and when, the real numbers
(threshold, peak, current, baseline), the class of finding, and the one thing that
is the user's to decide. Name the mechanism, not the state name. Route any physical
check as a task (`capture` → TickTick) with the measurements in the body, and leave
an already-correct open triage item open.
