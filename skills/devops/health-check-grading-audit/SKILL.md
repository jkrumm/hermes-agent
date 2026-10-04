---
name: health-check-grading-audit
description: "Use when a health check's own grading is the open question."
version: 1.0.0
metadata:
  hermes:
    tags: [health-check, grading, fail, warn, threshold, composite, monitor, devhost, launchd, memory, disk, false-positive, forensics]
    related_skills: [homelab-ops, warden, host-metric-alert-triage, alert-noise-suppression]
---

# Health-check grading audit

A composite health check (this estate's is `dotfiles/scripts/devhost-health-check.sh`,
run by a LaunchAgent every 300s, pushing one Uptime Kuma monitor) collapses sixteen
components into one grade. Its exit code *is* the monitor's state: `0` up, `2` WARN
(named in the line, never pages), anything else FAIL → the monitor goes DOWN.

Use this when a host-metric alert fires and the **check's own logic**, not the host,
is the open question: an unattributable FAIL, a component that keeps paging for a
benign condition, or a rendered line whose text contradicts its own numbers. The
mechanism of the alert is `alert-mechanism-forensics`; this skill audits the grader;
the bounded ops verbs are `homelab-ops`.

## Procedure

1. **Read the check's control flow in order, on the live checkout.** The file the
   LaunchAgent executes, not the default branch: `grep -n <symbol>
   ~/SourceRoot/dotfiles/scripts/devhost-health-check.sh`, and confirm the fix is
   actually *in* that file before reasoning about behaviour.
2. **Verify every gate is reachable with the values the host really has.** Walk the
   branches top-down and ask whether the numbers in `sysctl`/`df`/`launchctl` can
   reach each threshold at all. An early `return` for the mild grade sits *above* a
   stricter gate far more often than anyone intends — that gate becomes dead code
   and the check silently loses the protection its comment advertises.
3. **Make the message and the numbers agree.** The rendered line is what the operator
   reads, so a line that says one thing while quoting the opposite is a finding in
   itself. Quote it verbatim; it is the fastest proof of a control-flow defect.
4. **Read the grading convention before proposing a grade.** Components are
   level-triggered — they must fail `TRANSIENT_FAILS_BEFORE_ALERT` (3) consecutive
   300s runs before the failure is set, which is the `persisted N runs` suffix —
   unless they are in the immediate/edge set, which reports a *delta* off a state
   file. Grading a recovered, edge-shaped event as level-triggered FAIL is how one
   event becomes a sustained outage.
5. **Decide with the blast radius, then with the doctrine.** One FAIL takes the whole
   composite DOWN and implicates every healthy component in that push. The file's own
   comments carry the doctrine (`LEVEL` vs `EDGE`, why a benign class reports at
   WARN/exit 2) — cite it instead of inventing a rule.
6. **Never re-tune a threshold yourself.** It is a coverage decision on Johannes's
   hardware: state the gate and its configured value, what fired versus what passed,
   hand over the options (raise the ceiling / reclaim or fix the producer), and
   dispatch only the *defect* — a check that cannot see what it claims to grade.

## Threshold shapes that mislead

- **Percentage gates with an absolute floor.** A strict `pct < MAX` fails at exactly
  the ceiling while a generous free-space floor passes by a wide margin — a volume at
  90% with ~98 GB free. Quote both numbers and say which gate fired; "plenty of space
  left" is not a rebuttal to a percentage gate.
- **A cumulative metric read as a level.** `vm.swapusage` is a high-water mark, not
  current pressure: tens of GB of used swap against a fraction of that in total RSS
  means the box paged once and never gave it back. A gate on cumulative swap **never
  clears**, so the honest leak signal is a *rate* — the `Swapouts`/`Pageouts` delta
  between two runs — or an actual jetsam/OOM event.
- **A level that has become the steady state.** When a host sits at the same pressure
  level for days, a gate keyed on that level pages forever. Measure transient versus
  new-normal before recommending a grade.

## Pitfalls

- **The card's component list is a projection of the last push.** Recompute the
  current component states from the check's own log before attributing a FAIL; the
  push you were notified about may already have cleared. `tail` the composite lines
  (the long ones, not the per-component `✓` lines above them).
- **A FAIL that names a restart may be the estate's own deploy.** A plist rewrite plus
  `bootout`/`bootstrap` produces a clean exit-0 respawn; a check that grades only on
  `last terminating signal` files it under the crash bucket. Date it with the plist
  mtime and `launchctl print`'s `last exit code` before calling it a fault.
- **Do not widen a glob to catch more.** An age-gated check that globs broadly picks
  up unrelated artifacts in the same directory and WARNs on a healthy host; name the
  exact filename shapes instead.
- **Fixing the check is not fixing the cause.** A mis-grade explains a false alarm and
  hides nothing else: when a metric really is trending (job round times, fill rate),
  say so in the same report, separately from the grading defect.

## Turning the audit into work

A confirmed grading defect is repo work: `run <repo> --tier implement` through the
dispatch bridge, brief via `--brief-file`, no `--wait`, and the brief **ends with the
question** — the item dispatches investigate first. Put the live values, the branch
order at file:line, the gate's configured default, the rendered line, and the
measurement that rules out the naive fix (a reinstated cumulative threshold would page
forever) into it. The implement tier re-reads the investigate *verdict*, not the brief,
so the remedy has to survive that hop.
