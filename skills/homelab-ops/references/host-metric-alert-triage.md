# Host metric alert triage

_Use when a host metric alert fires (temp, CPU, disk, load, memory, host silent)._

A host system-metric alert is not repo-readable and usually has no ops verb. Since Beszel's removal (2026-11-19) the
metrics live in ClickStack, reported by the per-host `host-agent` (`host.name` = `mini`, `homelab`, `vps`); the alert rules
are managed as code in the vps repo and their history is in ClickStack. **CPU temperature is the exception:** it is not
collected as a metric, and its alert is the homelab watchdog's `check_thermal`.

## Procedure

1. **Name the source before diagnosing.** `grep -rn` the repos for the alert string. Zero matches in a service repo is
   expected: the rule lives in the vps repo's ClickStack alert files, not next to the code. The title tells the family:
   `🚨 <name> …` is HyperDX (ClickStack), `🌡️ HomeLab CPU hot` is the watchdog's thermal check.
2. **Re-run the alert's own condition read-only** with `agw hdx query` (skill `hyperdx`): `clickstack_get_alert` lists
   alerts with state (`Infra memory >= 90% (15m)`, `Infra filesystem >= 85% (15m)`, `Infra mini filesystem >= 93% (15m)`,
   `Infra load5 per core >= 8 (30m)`, `<host> host silent < 1 sample (10m)`); `get_alert {"id"}` gives dashboard, tile,
   threshold and recent evaluations; `clickstack_query_tile` re-runs the tile over the firing window. Never `agw hdx write`.
3. **Pull the baseline, not just the spike.** Query the metric itself over days (list the Metrics source with
   `clickstack_list_sources`, never reuse an id), e.g. load for one host:

   ```bash
   AGW_CALLER=hermes agw hdx query clickstack_table '{"sourceId":"<Metrics source id>",
     "select":[{"aggFn":"max","metricType":"gauge","metricName":"system.cpu.load_average.5m","valueExpression":"Value","alias":"load5_max"}],
     "where":"ResourceAttributes['"'"'host.name'"'"'] = '"'"'homelab'"'"'","whereLanguage":"sql",
     "groupBy":"toStartOfHour(TimeUnix)","startTime":"<ISO>","endTime":"<ISO>"}' --format json
   ```

   Metric names: `system.cpu.utilization`, `system.memory.utilization`, `system.filesystem.utilization` (attribute
   `system.filesystem.mountpoint`), `system.cpu.load_average.{1m,5m,15m}`. A threshold a few units *inside* the normal
   band fires on routine work (a build storm, a nightly backup) and the finding is a **tuning** one.
4. **Check the shape, not the count.** A condition that cleared itself is a self-clearing flap; correlate each with what ran
   then (container start times, scheduled jobs, factory builds) before blaming ambient conditions.
5. **Then decide the class of finding** — tuning (threshold, the owner's call), physical (cooling/airflow/disk, a human at
   the box), or a genuinely bad metric (memory pressure, disk fill, a wedged process).

## Temperature

No ClickStack metric exists for it (the host-agent has no hardware scraper), so never answer a thermal question from
ClickStack or argo. The alert is `🌡️ HomeLab CPU hot` from `check_thermal` (homelab repo, `scripts/homelab_watchdog.sh`): the
mean of the last three 10-minute samples of the coretemp package, one alert at >= 90 °C and one "cool again" below 85 °C. Its
state dir is root-only, so read the live value from the kernel:

```bash
ssh homelab 'for d in /sys/class/hwmon/hwmon*; do echo "$(cat $d/name) $(cat $d/temp1_input 2>/dev/null)"; done; uptime'
```

`temp1_input` is millidegrees. The watchdog's firing history is the ntfy topic `alerts`, which you cannot read; work from what
the owner relays and the live reading.

## Rules

- **Judge the baseline against the hardware, not against the number's vibe.** An Intel N100 idling at ~84 °C package on load
  avg 0.3 is ~30 °C above typical → marginal cooling, the alert is correct and the action is physical. A baseline **flat over
  weeks** is the box's steady state, not accumulating dust — never sell a flat series as "recent degradation".
- **Report frequency from the source's own history** (`get_alert` history, the metric over the window), not from a triage
  card's "N× since <date>", which only counts occurrences while its item was in a live state and can understate by an order
  of magnitude.
- **Per-host thresholds differ on purpose.** The mini's disk line is 93 % (it runs at 88–92 % normally), everyone else's 85 %;
  load is per core (8 per core over two 15 m windows) with a fixed core count per host. Read the alert's own definition
  before calling a value high.
- **Never re-tune a monitoring threshold yourself.** Raising a threshold to silence an alert is a coverage decision; state the
  number, the baseline and the recommendation, and let the owner set it. Thresholds are changed in the vps repo, never in the
  ClickStack UI.
- **Absent fan RPM is not a fanless box.** Many mini-PCs do not expose one in hwmon. Say "no fan sensor exposed", never "no fan".
- **Not covered, so no alert will come:** a CPU-utilization alert (only a tile), temperature on the mini, kernel memory pressure
  and swap-out rate on the mini (the factory host heartbeat owns those). Absence of an alert there is not absence of a problem.
- **Remediation is `homelab-ops` territory**: its bounded verbs and `references/alert-patterns.md` (alert string → root
  cause → verb) own the fix. This skill owns the diagnosis and the numbers.
