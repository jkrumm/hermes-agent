---
name: upstream-feed-outage-triage
description: Use when an ingest feed reports stale or missing data.
version: 1.0.0
metadata:
  hermes:
    tags: [ingest, feeds, staleness, observability, triage, verification, external]
    related_skills: [alert-liveness-forensics, defect-report-verification, homelab-ops]
---

# Upstream feed outage triage

The class: a scheduled collector reports staleness — a watchdog flags
`obs_freshness:<source>`, a table stops growing, an indexer or scanner goes quiet.
The question is whether the break is **upstream** (the provider stopped serving)
or **local** (credential, ref, parser, job). From the store the two look
identical, and the wrong answer aims a fix at a system that is working.

`alert-liveness-forensics` owns *is this alert still true*. This skill owns *which
side of the wire broke*, which is the question that decides whether anything
should be touched at all.

## Procedure

1. **Read the producer's own state, not the alert.** The alert is a timestamped
   observation. Pull the newest artifact the ingest writes plus its mtime, and the
   job's last exit: `launchctl print gui/$(id -u)/<label>`.
2. **Re-run the ingest's exact command from a shell.** Copy the argv out of the
   rendered plist (or the Makefile target) rather than reconstructing it, so the
   `--env-file`, the interpreter and the working directory match. Green here means
   the local path works — the staleness is upstream or in the schedule, not the
   code.
3. **Probe the provider directly: once with the real credential, once with a
   deliberately invalid one.** The bogus call is the control. It proves the
   transport reaches the provider and that the provider *distinguishes* auth
   failure from silence. A valid key returning an empty-but-successful envelope
   while a bogus key returns an explicit auth error is proof the credential is
   good and the provider has nothing to serve.
4. **Widen the query window before concluding.** Re-fetch with an older start
   date: rows up to a hard stop and nothing after means the provider's series ends
   there. That stop time is the outage's start and the number to report.
5. **Classify, then stop.** Upstream silence is reported as external/degraded with
   the last-good timestamp and the count of silent sources. Do not edit the
   parser, widen a threshold, or reseed a credential to turn the board green.
6. **Report:** what is stale, since when, the discriminating evidence, and what
   you deliberately did not touch.

## Pitfalls

- **A success-but-empty envelope is silence, not a shape change.** Providers that
  answer "campaign found, zero rows in this window" are telling you there is
  nothing to serve. Treating that as a parse failure converts an upstream outage
  into a false local bug — and a parser that raises on it usually fails the whole
  ingest cycle, taking every other source in the same run down with it.
- **Never reseed or rotate a credential before the control probe.** A rotated
  secret that was never the problem costs a human handoff and buries the real
  outage behind a cache reseed.
- **A stale error file is not a live failure.** `.err` files and a recorded
  `last exit code` outlive the run that wrote them; compare their mtime against
  the change that should have fixed them before reporting the failure as current.
- **Never widen a freshness threshold to clear an alert.** The threshold *is* the
  measurement; moving it destroys the only signal that a feed went quiet.
- **N silent sources are one finding.** Report the count and the oldest silence,
  not one line per source.
- **A feed that is silent upstream keeps its heartbeat.** If the dead-man's switch
  still fires, the collector is alive and only the data is missing — say that, so
  nobody restarts a healthy job.
