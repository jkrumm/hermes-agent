---
name: alert-liveness-forensics
description: Use when deciding whether an alert is still live.
version: 1.0.0
metadata:
  hermes:
    tags: [alerts, monitoring, beszel, uptime-kuma, hyperdx, triage, liveness]
    related_skills: [warden-digest-triage, warden, homelab-ops, heartbeat-monitoring]
---

# Alert liveness forensics

An alert message is a **timestamped observation**, never a statement about now. A
digest line, a `#alerts` post and an UptimeKuma notification are all history; the
question "is this still true" is answered only by the source that owns the
measurement. Answer it before relaying anything as outstanding work.

This is the complement to `warden-digest-triage` (which owns Warden's ledger,
policy file and state machine). This skill owns the other half: **what the
producer's own state says right now.**

## Procedure

1. **Identify the producer behind the alert text.** The title names it: a bare
   sentence (`HomeLab CPU above threshold`) is a resource-scraper (Beszel); a
   bracketed one (`[Gluetun - Docker] [:red_circle: Down] …`) is UptimeKuma; an
   emoji-led one (`🚨 audio-gateway podcast.failed >= 1 (1h)`) is HyperDX. The
   producer, not the channel, holds the live state.
2. **Probe that producer read-only** (recipes below). Two facts are needed and
   they are different: *is the condition true now*, and *when did it last fire
   and clear*. A firing that resolved 40 minutes later is not an open incident.
3. **Check the alert is not already answered.** A `✅`-prefixed recovery message
   in the same channel is the positive pairing; a `200` from the service's own
   URL settles a "new incident" line outright.
4. **Report liveness first, mechanism second.** For each family: still triggered /
   last fired and cleared / answered 200 — then why it reached the surface it
   reached (which filter, which rule, which producer shape).
5. **Never turn a liveness check into a fix.** Restarting a service, clearing a
   flag or pruning storage is a separate decision with its own blast radius;
   name the number (reclaimable GB, disk %, free space) and let the owner call it.

## Recipes

### Beszel — homelab resource thresholds

Emits bare sentences with no bot-alert prefix, which is why this family reaches
Warden as "unstructured prose". Metrics: `CPU`, `Memory`, `Disk`, `LoadAvg5`,
`Temperature`, `Status`.

```bash
ssh homelab "python3 -c \"
import sqlite3
c = sqlite3.connect('/mnt/hdd/beszel/data.db')
c.row_factory = sqlite3.Row
for r in c.execute('select * from alerts'): print(dict(r))
for r in c.execute('select * from alerts_history order by rowid desc limit 15'): print(dict(r))
\""
```

- `alerts` = current state per metric: `name`, `value` (the threshold), `triggered`
  (0/1), `updated`. `triggered = 1` means it holds now.
- `alerts_history` = one row per firing, `created` + `resolved`. **An empty
  `resolved` means still firing** — this is the column that separates "cleared
  after 40 minutes" from "open now"; `alerts.triggered` alone cannot.
- `system_stats` = the time series (`type` is the bucket, e.g. `1m`; `stats` is a
  JSON blob with `cpu`, `la`/`la5`, `dp`/`du`/`dr` for disk, `t` for temperature).
  Use it for the value now, `alerts_history` for whether it is still firing.
- The bind mount is root-owned but world-readable, so no sudo is needed.

### Slack-sourced alerts (UptimeKuma, HyperDX, watchdogs)

```bash
set -a; source <(secrets-run export --env-file=$HOME/.hermes/.env.tpl | sed 's/^export //'); set +a
curl -s -H "Authorization: Bearer $HOMELAB_API_KEY" \
  "https://argo.jkrumm.com/api/slack/channels/C0AS1LAUQ3C/messages?limit=25"
```

- Firing history for one signature: `GET /slack/search?q=in:%23alerts "<exact alert text>"`.
  URL-encode the whole query (`urllib.parse.quote`) rather than hand-building it in
  the shell — a mis-encoded query returns an empty body that surfaces as
  `JSONDecodeError: Expecting value: line 1 column 1`, which reads like a broken
  endpoint instead of a malformed query.
- A `✅`-prefixed message is the recovery pairing; its absence is a reason a row
  can sit open, not evidence the service is down.
- Past digests live in the digest/card channel, not the alert channel. Diff today's
  headings against the last few days' before calling anything new.

### Public services

One call settles a "new incident" line:
`curl -s -o /dev/null -w '%{http_code}' https://<host>/`.

## Pitfalls

- **A distroless container has no shell — read its state from the host.**
  `docker exec <container> sh` dies `exec: "sh": executable file not found in
  $PATH` on the Beszel images. Its state is a SQLite file on a host bind mount, so
  `ssh <host> "python3 -c …"` reads it without the container cooperating.
- **A recurring digest line is not a new finding.** A digest that re-selects every
  open row will print the same lines for as long as the rows stay open. A family
  present for a week is a standing defect in the loop that reports it — say that
  once, with the mechanism, instead of re-reporting the lines daily.
- **An un-prefixed producer's alerts all land in the "needs a human look" bucket.**
  A watchdog emitting plain sentences never looks like a structured bot alert,
  however real it is. When a whole family surfaces as unstructured prose, suspect
  the producer's message shape, not the routing policy.
- **Never map an alert to an owner by an opaque numeric monitor id.**
  `uk:<number>` changes when the monitor is recreated; the stable form is derived
  from the title (`Warden Backup - Push` → `uk:warden-backup-push`). A rule written
  against the number silently stops matching.
- **A one-shot alert's ledger row keeps the firing timestamp, so an old-looking digest
  line can still be live.** Beszel fires once on the threshold crossing and emits nothing
  more until it resolves, so the event's `last_seen` stays at that moment while the
  condition holds — read `alerts_history.resolved`, never the row's age, before calling a
  resource-threshold line stale.
- **A duplicate-heavy rule file is its own finding.** Auto-appended rules are not
  deduplicated, so count *unique* match values as well as entries before reading a
  policy file as a rule set, and report the duplication rather than quietly
  working around it.

## Report shape

Lead with the count and the split, then one block per family, each stating
liveness before mechanism:

- **still live** / **last fired <time>, cleared <time>** / **answered 200**;
- the producer shape or filter that routed it to the surface it reached;
- for anything genuinely open, the concrete number (disk %, free space, GB
  reclaimable) — that is what decides an action;
- what was **not** done, and why (no policy write, no dispatch past a ceiling, no
  restart).

Group lines that share one producer into a single block. Eleven signatures from
one scraper is one finding.
