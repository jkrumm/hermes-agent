---
name: hyperdx
description: Triage OpenTelemetry traces/logs/metrics in ClickStack/HyperDX (VPS-only) via its authenticated REST + MCP API — never the browser UI, which needs an interactive login you cannot provide. Use when a HyperDX-authored alert lands in #alerts ("VPS edge 5xx rate > 5%", "VPS edge p95 > 3s", "VPS error logs >= 20"), or when asked "why are requests failing/slow on the VPS", "what's causing 5xx on <app>", "show me recent errors for <service>". Ends in a diagnosis you either report directly or escalate via claude-dispatch / capture.
version: 1.0.0
metadata:
  hermes:
    tags: [hyperdx, clickstack, clickhouse, otel, opentelemetry, observability, traces, tracing, logs, metrics, 5xx, latency, p95, error-rate, edge, traefik]
    related_skills: [homelab-ops, claude-dispatch, capture, argo-api]
---

# HyperDX / ClickStack — observability triage

One production instance, on the VPS: `clickhouse/clickstack-all-in-one`
(ClickHouse + OTel collector + HyperDX UI), reachable at
`https://hyperdx.jkrumm.com` — **Tailscale-only** (grey-cloud DNS). There is no
HomeLab instance. Full architecture: `vps/docs/observability.md`.

**Never open the HyperDX dashboard URL from a Slack link and expect to read it.**
It is a logged-in web app — a bare `curl`/fetch against it hits a login wall, not
data. A prior attempt did exactly this and gave up ("HyperDX verlangt lokale
Browser-Freigabe"), then fell back to grepping raw Traefik logs by hand and still
couldn't find the failing route. **That fallback should never be necessary** — a
dedicated read-only agent user already exists precisely so you don't need a
browser session. Use the MCP API below instead.

**Base URL:** `https://hyperdx.jkrumm.com`
**Auth:** `Authorization: Bearer $HYPERDX_AGENT_ACCESS_KEY` (in env — never run `op`, never print it)

---

## When to use this — and when NOT to

**Use this skill:**
- A HyperDX alert fires in `#alerts` — currently three, all posting to the "Slack #alerts"
  webhook: `VPS edge 5xx rate > 5% (5m)`, `VPS edge p95 > 3s (15m)`, `VPS error logs >= 20 (15m)`.
- "Why is `<service>` slow/erroring", "what's failing on the VPS", "show recent errors for X".
- Corroborating a `homelab-ops` finding ("container is healthy but the alert fired anyway" —
  exactly the transient-5xx case this skill exists to actually resolve instead of shrugging at).

**Do NOT use this skill for:**
- Container/monitor health, restarts, deploy state → `homelab-ops` first. Only reach for
  HyperDX once ops says the containers themselves look fine (the common case — a 5xx spike
  is application-level, not a crash) or once you need the specific failing route/trace.
- Anything code-shaped ("what changed", "read the source") → `claude-dispatch` once you have
  a service name and a symptom from here.

---

## Query path — MCP `clickstack_sql`, one curl template

The HyperDX UI proxies a stateless JSON-RPC/SSE MCP server at `/api/mcp`. There is exactly
one call shape you need — raw SQL via the `clickstack_sql` tool. Fill in `$SQL` and run:

```bash
curl -s -X POST \
  -H "Authorization: Bearer $HYPERDX_AGENT_ACCESS_KEY" \
  -H "Content-Type: application/json" \
  -H "Accept: application/json, text/event-stream" \
  -d "{\"jsonrpc\":\"2.0\",\"id\":1,\"method\":\"tools/call\",\"params\":{\"name\":\"clickstack_sql\",\"arguments\":{\"connectionId\":\"69cd0b07911482e6218c0ef5\",\"sql\":\"$SQL\"}}}" \
  https://hyperdx.jkrumm.com/api/mcp \
  | grep '^data:' | sed 's/^data: //' | jq -r '.result.content[0].text' | jq .
```

`connectionId` is the single registered ClickHouse connection ("Local ClickHouse") and is
stable for this single-instance setup — verified live. If a query ever comes back with a
connection-not-found error, re-resolve it once:

```bash
curl -s -X POST -H "Authorization: Bearer $HYPERDX_AGENT_ACCESS_KEY" -H "Content-Type: application/json" \
  -H "Accept: application/json, text/event-stream" \
  -d '{"jsonrpc":"2.0","id":1,"method":"tools/call","params":{"name":"clickstack_list_sources","arguments":{}}}' \
  https://hyperdx.jkrumm.com/api/mcp | grep '^data:' | sed 's/^data: //' | jq -r '.result.content[0].text' | jq .
```

Always include a `LIMIT` in `$SQL`. Default to a narrow time window (`INTERVAL 15 MINUTE`
or `1 HOUR`) and widen only if empty.

---

## Schema

Tables: `default.otel_traces`, `default.otel_logs`, `default.otel_metrics_gauge` /
`_sum` / `_histogram` / `_summary`.

- **otel_traces**: `Timestamp` (DateTime64 ns), `TraceId`, `SpanId`, `ParentSpanId`,
  `SpanName`, `SpanKind` (`Server`/`Client`/`Internal`), `ServiceName`, `Duration`
  (UInt64 ns — divide by 1e6 for ms), `StatusCode` (`Ok`/`Error`/`Unset`), `StatusMessage`,
  `SpanAttributes` `Map(String,String)` (`http.route`, `http.status_code`, `server.address`,
  `url.scheme`, `db.statement`), `ResourceAttributes` `Map(String,String)` (`host.name`,
  `deployment.environment`).
- **otel_logs**: `TimestampTime` (DateTime, use in `WHERE` — partition key), `SeverityText`
  (`INFO`/`WARN`/`ERROR`), `SeverityNumber` (17-20 = ERROR), `ServiceName`, `Body`,
  `LogAttributes` `Map(String,String)`.
- Map access: `SpanAttributes['http.status_code']`, `mapContains(SpanAttributes, 'http.route')`.

---

## The three live alerts, and the query behind each

Alert defs are code: `vps/observability/alerts/*.json`, referencing tiles in
`vps/observability/dashboards/vps-overview.json`. **Reuse these exact conditions when
triaging the alert that fired** — don't re-derive a different query and get a different
number.

**`VPS edge 5xx rate > 5% (5m)`** — edge-only (Traefik), excludes the OTel ingest route
itself and websocket upgrades:
```sql
SELECT
  countIf(StatusCode = 'Error') AS errors,
  count() AS total,
  errors / total AS rate
FROM default.otel_traces
WHERE ServiceName = 'traefik' AND SpanKind = 'Server'
  AND SpanAttributes['server.address'] != 'otel.jkrumm.com'
  AND SpanAttributes['url.scheme'] != 'wss'
  AND Timestamp > now() - INTERVAL 5 MINUTE
```
Once confirmed, find the actual failing backend — group by the downstream service, not
just Traefik:
```sql
SELECT ServiceName, SpanAttributes['http.route'] AS route, SpanAttributes['http.status_code'] AS code, count() AS n
FROM default.otel_traces
WHERE SpanKind = 'Server' AND StatusCode = 'Error' AND Timestamp > now() - INTERVAL 15 MINUTE
GROUP BY ServiceName, route, code ORDER BY n DESC LIMIT 20
```

**`VPS edge p95 > 3s (15m)`** — same edge scope, p95 of `Duration` (ns) over 15m.

**`VPS error logs >= 20 (15m)`**:
```sql
SELECT ServiceName, Body, count() AS n
FROM default.otel_logs
WHERE SeverityNumber >= 17 AND TimestampTime > now() - INTERVAL 15 MINUTE
GROUP BY ServiceName, Body ORDER BY n DESC LIMIT 20
```

**A green re-check after the alert window has passed is not a diagnosis.** "Currently
healthy, no active recovery needed" is a fine answer only when the query above genuinely
returns nothing for the alert's own window — always run it before concluding transient.

---

## Escalation — after you have a service name and evidence

| Finding | Action |
|-|-|
| Transient, self-resolved, evidence shows a brief spike with no pattern | Report it — no escalation needed. Name the window and the numbers. |
| Recurring / ongoing, root cause is app code (a specific service, route, error message) | `claude-dispatch` into that service's own repo, `--tier author` to file the issue with your evidence, or `--tier implement` only after Johannes confirms a fix. |
| Root cause is Traefik/ClickStack/compose config itself | `claude-dispatch dispatch vps --tier investigate` (the ceiling there — read-only). For a filed issue or a fix, use `capture` → `gh issue create` on `vps` directly, or report to Johannes; the dispatch bridge cannot author/implement on `vps`. |
| You cannot tell which service owns the failing route | `clickstack_sql` group-by above already answers this — don't guess or escalate before running it. |

**ServiceName → repo**, current mapping (services seen in `otel_traces.ServiceName`):

| ServiceName | Repo |
|-|-|
| `traefik`, `clickstack` | `vps` (investigate-only) |
| `argo-api`, `argo-dashboard` | `argo` |
| `fpp-server`, `fpp-analytics`, `free-planning-poker` | `free-planning-poker` |
| `audio-gateway` | `audio-gateway` |
| `research-gateway` | `research-gateway` |
| `imgproxy` | `vps` (off-the-shelf image; config-only, investigate-only) |

A `ServiceName` not in this table: check `apps/*/compose.yml` in `vps` for `OTEL_SERVICE_NAME`
to find the owning app, or ask rather than guess the repo.

---

## Dashboards / alerts metadata (secondary — REST v2)

Only for "what alerts exist" / "what's the current dashboard config" questions, never for
trace/log data:

```bash
curl -s -H "Authorization: Bearer $HYPERDX_AGENT_ACCESS_KEY" https://hyperdx.jkrumm.com/api/api/v2/alerts | jq .
curl -s -H "Authorization: Bearer $HYPERDX_AGENT_ACCESS_KEY" https://hyperdx.jkrumm.com/api/api/v2/dashboards | jq .
```

**Read-only.** Never `POST`/`PUT`/`DELETE` against this API — dashboards and alerts are
managed as code in `vps/observability/{dashboards,alerts}/*.json` via `make hyperdx-export`
/ `make hyperdx-apply`, run by Johannes, not this skill.

## Deep-linking

`https://hyperdx.jkrumm.com/dashboards/<id>?from=<epoch-ms>&to=<epoch-ms>&kiosk=true` — give
Johannes a direct link to the relevant dashboard/window when reporting a finding, so he can
look without you re-explaining every number in Slack.
