# macOS host memory pressure — reading the kernel signal correctly

Use when a MacMini push-monitor heartbeat names memory pressure, swap, or a
degraded host health check. This is interpretation only — never kill processes,
restart Colima, or restart the Hermes gateway from inside a triage; report the
evidence and a bounded next step.

## The kernel pressure level, not swap, is the real signal

```bash
sysctl -n kern.memorystatus_vm_pressure_level
sysctl -n vm.swapusage
memory_pressure -Q
```

`kern.memorystatus_vm_pressure_level` maps `1` = normal, `2` = WARN (the kernel
may start reclaiming/jetsam-killing), `4` = CRITICAL. macOS grows and shrinks
the swap file dynamically, so a stable, modest swap number is not evidence of
health by itself — trust the pressure level over swap.

**Free-page percentage is a different metric and does not override it.**
`memory_pressure -Q` can report roughly half the pages free while
`kern.memorystatus_vm_pressure_level` reads `2`. That is not a contradiction —
free-page fraction and the kernel's own pressure verdict answer different
questions. **Never downgrade a level-2 (or 4) alert because free pages look
comfortable.**

## Rank consumers, don't sum them

```bash
ps -axo rss=,comm= | awk '{sum[$2]+=$1; count[$2]++} END {for (k in sum) if (sum[k] > 100*1024) printf "%8.0f MB\t%2d proc\t%s\n", sum[k]/1024,count[k],k}' | sort -nr | head -30
```

RSS is a ranking signal for finding the pressure source, not a physical-memory
accounting total. Shared pages, compressed memory, GPU mappings, and VM
accounting all break naive summation on Apple Silicon — a large, stable VM
(Colima and similar) is not automatically a leak; look for growth over time or
corroborating restart/health-check evidence instead.

## Two log predicates that look like an OOM kill and aren't

```bash
log show --last 2h --style compact --predicate \
  '(eventMessage CONTAINS[c] "killed for memory" OR \
    eventMessage CONTAINS[c] "jetsam event" OR \
    eventMessage CONTAINS[c] "jetsam kill" OR \
    eventMessage CONTAINS[c] "memorystatus: killing")'
```

- `killing_idle_process … due to idle-exit` is routine kernel housekeeping
  (idle daemon reclamation), not evidence a foreground workload was
  OOM/Jetsam-killed.
- `runningboardd memorystatus_control … Invalid argument` is diagnostic noise
  on its own — only treat it as a real kill when it's paired with an actual
  process termination or a service outage.

An explicit pressure/OOM/Jetsam event naming a real workload is the only thing
that confirms impact; either false friend alone does not.

## The state-race explanation has one precondition

A red push monitor can look like a stale UptimeKuma state race, but that
explanation is only valid **after** the kernel pressure level has returned to
normal (`1`) **and** the next heartbeat is healthy. If the level is still
WARN/CRITICAL, the red state is a real current condition — don't wave it off
as a race while the kernel itself still disagrees.
