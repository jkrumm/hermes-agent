---
name: alert-mechanism-forensics
description: Use when an alert needs a cause, not just liveness.
version: 1.0.0
metadata:
  hermes:
    tags: [alerts, triage, mechanism, deploy, traefik, clickhouse, hyperdx, argo, docker, 5xx, rollout, forensics]
    related_skills: [alert-liveness-forensics, homelab-ops, hyperdx, rollhook-deploys, warden-digest-triage, claude-dispatch]
---

# Alert mechanism forensics

`alert-liveness-forensics` answers *is it true now*. This skill answers the next two
questions: **what produced it**, and **is that producer a fault or an expected
side-effect of a deploy**. Liveness without a mechanism produces a report that is
correct and useless; a mechanism without liveness produces a fix for something that
already ended.

Load `alert-liveness-forensics` for the liveness half, `homelab-ops` before touching
anything, `hyperdx` for the query surface, `rollhook-deploys` when a deploy is
implicated. This skill is the crossing: the evidence that separates them.

## Procedure

1. **Establish liveness first** (sibling skill). Never diagnose a mechanism for a
   condition you have not shown to be current, or to have just cleared.
2. **Read the producer's own artifact, not the alert text** — the edge access log, the
   container's state and start time, the app's own log lines. The alert records what
   someone observed; the artifact records what the system did.
3. **Classify before you explain:** deploy window / telemetry self-noise / dependency
   blip / the service itself. Each has a different next action, and only the last one
   is a fix.
4. **Get the number that decides it** — bucket rate, error count, container start
   time, 7d/30d uptime ratio — and quote it. "Recurring" is a number, not a feeling.
5. **Report liveness, mechanism, class, and what you did NOT do.** Only then escalate,
   and only for a confirmed app-code mechanism.

## Read-only evidence paths

Auth once per shell:

```bash
set -a; source <(secrets-run export --env-file=$HOME/.hermes/.env.tpl | sed 's/^export //'); set +a
```

| Question | Path |
|-|-|
| Is anything actually down; do monitors disagree with Docker? | `GET https://argo.jkrumm.com/api/summary` |
| Per-monitor state + `uptime1d`/`uptime30d` (a chronic fault shows as low 30d) | `GET /api/uptime-kuma/monitors` |
| Exact container names, state, health, restart count, `startedAt` | `GET /api/docker/<host>/containers` |
| A container's own log lines | `GET /api/docker/<host>/logs/<exact-name>?tail=N` |
| Alert history and the recovery pairing | `GET /api/slack/channels/<alerts-channel>/messages?limit=N` |
| The Warden ledger: card text, occurrences, `last_seen` | `~/SourceRoot/warden` venv python, `file:…?mode=ro` |

**This table is a fallback, not a substitute.** When the bounded ops dispatcher is
usable, use it — it encodes the right host, target and post-check. When it refuses or
is unavailable to you, the reads above answer the read-only questions and the report
must say which path produced each number. Only a *mutation* (restart, redeploy, sync)
genuinely needs the ops verb; never improvise one.

**Container names are not service names.** `/api/docker/<host>/logs/<service>` answers
`Container "<service>" not found` — an HTTP 500 with a plain-text body, so a JSON parse
fails first and the error reads like a broken endpoint. Read the exact `name` from
`/api/docker/<host>/containers` first; it carries a compose suffix
(`<project>-<service>-<index>`).

### Edge symptoms via ClickStack

One self-contained call, no `jq` in the path — write it to a file, not a temp dir the
next session will not find:

```python
#!/usr/bin/env python3
# clickstack_sql.py — one SQL statement on stdin, parsed JSON out.
import json, os, sys, urllib.request
CONN = os.environ.get("CLICKSTACK_CONNECTION_ID", "69cd0b07911482e6218c0ef5")
def sql(q):
    body = json.dumps({"jsonrpc": "2.0", "id": 1, "method": "tools/call",
                       "params": {"name": "clickstack_sql",
                                  "arguments": {"connectionId": CONN, "sql": q}}}).encode()
    req = urllib.request.Request("https://hyperdx.jkrumm.com/api/mcp", data=body, headers={
        "Authorization": "Bearer " + os.environ["HYPERDX_AGENT_ACCESS_KEY"],
        "Content-Type": "application/json",
        "Accept": "application/json, text/event-stream"})
    raw = urllib.request.urlopen(req, timeout=90).read().decode()
    text = "".join(l[5:].strip() for l in raw.splitlines() if l.startswith("data:")) or raw
    return json.loads(json.loads(text)["result"]["content"][0]["text"])
if __name__ == "__main__":
    print(json.dumps(sql(sys.stdin.read()), indent=1, default=str))
```

Bucket the window — never just the current bucket, or a spike that already cleared
reads as "broken":

```sql
SELECT toStartOfFiveMinute(Timestamp) AS t, countIf(StatusCode='Error') AS err,
       count() AS total, round(err/total,3) AS rate
FROM default.otel_traces
WHERE ServiceName='traefik' AND SpanKind='Server'
  AND SpanAttributes['server.address'] != 'otel.jkrumm.com'
  AND SpanAttributes['url.scheme'] != 'wss'
  AND Timestamp > now() - INTERVAL 3 HOUR
GROUP BY t ORDER BY t DESC LIMIT 40
```

Then name the failing backend before escalating:

```sql
SELECT toStartOfMinute(Timestamp) AS t, SpanAttributes['server.address'] AS host,
       SpanAttributes['url.path'] AS path, count() AS n
FROM default.otel_traces
WHERE SpanKind='Server' AND StatusCode='Error' AND Timestamp > now() - INTERVAL 30 MINUTE
GROUP BY t, host, path ORDER BY t DESC LIMIT 25
```

## Separating a deploy window from a fault

A rolling deploy produces the same signature as an outage: edge 5xx, a health monitor
red for a few minutes, jobs cut short. Four artefacts separate them — read all four
before naming a cause.

- **Traefik-generated 5xx are not app errors.** In the access log they carry upstream
  `"-"` and `0ms` with a short body; in ClickHouse the matching span is
  `StatusCode='Error'` with an **empty** `http.status_code` and sub-millisecond
  duration. That is *no healthy endpoint* — a routing fact, not a fact about the app.
- **A fresh container `startedAt`, or a `Deployed <app> Image:` event in the Warden
  ledger, puts a deploy inside the window.** Compare it against the first failing bucket.
- **Traefik's own health-check warnings name a backend IP.** Warnings against the
  *previous* container's IP during a rollout are teardown and expected; the same IP
  failing across many minutes with no deploy in flight is the service.
- **How long, and how often.** A ~10-minute window bounded by a deploy is a rollout
  artefact. The same shape returning across weeks — visible as depressed 30d uptime on
  the monitor — is the standing defect, and that ratio is the number to report.

The two other easy mis-classifications: check whether slow/failing spans belong to the
estate's own telemetry ingest paths or to a single client before calling latency an
incident, and check whether the failing dependency is one the app already tolerates.

## Pitfalls

- **A re-delivered card is not a new incident.** Slack re-deliveries and in-place card
  edits carry the timestamps from when the card was first written. Compare the card's
  "last" line against the alert channel *and* the ledger row's `last_seen` before
  treating it as fresh.
- **A `last_seen` that never advances is a tracking defect in its own right.** If the
  channel shows new occurrences of a signature while its row stays put, the recurring
  signal is failing to reopen its item — say so, because the card will keep
  under-reporting until it is fixed.
- **Don't let one bucket become the story.** Read the per-bucket series around it; a
  five-minute excursion inside a flat window and a sustained climb are different
  findings with different actions.
- **A monitor's own ratio dates the fault better than the alert does.** `uptime1d`
  healthy with `uptime30d` depressed is a chronic problem that recently stabilised;
  both healthy means the alert is history.
- **Never turn the diagnosis into the fix.** Restart, redeploy, sync and prune are
  separate decisions with their own blast radius; name the evidence and the number and
  let the owner call it.

## When the mechanism is an app defect

Only when the mechanism is confirmed to be the service's own behaviour — not a deploy,
not a dependency, not telemetry — does it become repo work, and then it goes through
the dispatch bridge rather than improvised shell:

- `dispatch <repo> --tier author` — the episode investigates and files the issue from
  its own reading of the repo. The issue is picked up as a Warden item on its own, so
  the finding keeps moving after the conversation ends. Prefer this over `run` when the
  point is to leave something tracked: `run` caps the item's tier.
- Put the measured numbers in the brief — bucket rate, error counts, the exact failing
  timestamps, the container state now. The episode cannot see your session, and it is
  the second reader of your evidence.
- The brief can end up in a public issue: summarize internal detail, never paste host
  addresses, credentials or private channel content.
- A parked fix can arrive as a conflicting draft PR, and a merge can be refused
  outright for a repo with no declared auto-merge path. Both are owner decisions by
  design — report the refusal and the exact step it needs, never work around it.

## Report shape

Verdict first, then one line per finding, each stating the class before the cause:

- what the signature actually is, and whether it is live **now**;
- the mechanism — which producer, which artefact, which numbers;
- the class — deploy window / telemetry / dependency / the service itself;
- what you did, and what you deliberately did **not** do, and why (no restart, no
  policy write, no dispatch past a ceiling);
- anything you could not determine, labelled as inferred — an inferred mechanism
  marked as inferred is worth more than a confident guess.
