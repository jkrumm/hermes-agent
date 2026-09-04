# Observability triage (hyperdx)

Moved verbatim out of `CLAUDE.md` (2026-09-04, size pass). `CLAUDE.md` § Observability triage points here — nothing was rewritten, only relocated.

Added 2026-08-31, after a live triage attempt hit exactly the gap this closes:
asked to investigate a `VPS edge 5xx rate > 5%` alert, Hermes checked container
health and UptimeKuma (both green — correctly, since a 5xx spike is
application-level, not a crash), then tried to open the linked HyperDX dashboard
directly and gave up ("HyperDX verlangt lokale Browser-Freigabe, die ich hier
nicht automatisch bestätigen kann"), falling back to grepping raw Traefik logs
by hand and still not finding the failing route. The gap wasn't judgment — it
correctly ruled out an outage — it was tooling: it had no authenticated path
into ClickHouse, only the browser UI's login wall, even though a dedicated
read-only agent user (`op://vps/clickstack/AGENT_ACCESS_KEY`, provisioned by
`make hyperdx-agent-setup` in `vps`) already existed for exactly this and is
**already cached on the mini** (`dotfiles-private/headless.refs`) — it just
wasn't wired into `.env.tpl`, so no Hermes command ever saw it.

The **`hyperdx` skill** (`skills/hyperdx/SKILL.md`) closes it: `HyperDX
/ClickStack (VPS-only, `hyperdx.jkrumm.com`, Tailscale-only) exposes a stateless
JSON-RPC/SSE MCP server at `/api/mcp` — the same server sideclaw's `otel` MCP
tool and `~/.claude/skills/otel/scripts/hdx.py` use for Claude Code sessions,
same credential, different consumer. The skill gives Hermes one verified curl
template (`tools/call` → `clickstack_sql`, SSE response parsed with
`grep '^data:' | sed 's/^data: //' | jq`) against `default.otel_traces` /
`otel_logs` / `otel_metrics_*`, plus the exact SQL behind each of the three live
alerts (`vps/observability/alerts/*.json` — 5xx rate, p95 latency, error-log
count) so a triage re-runs the *same* condition that fired rather than deriving
a different number. `HYPERDX_AGENT_ACCESS_KEY` is wired in `.env.tpl` from the
same `op://vps/clickstack/AGENT_ACCESS_KEY` ref.

**Escalation reuses the existing dispatch bridge, not a new mechanism.** Once
the skill has a service name and evidence, it routes through `claude-dispatch`
exactly as any other code-shaped finding would — `--tier author` to file an
issue, `--tier implement` only after confirmation — with one documented
exception: a root cause inside Traefik/ClickStack config itself is scoped to
`vps`, which sits in `config/dispatch-repos.json`'s `investigate`-only tier (the
machine's own control plane), so the skill falls back to `capture` → `gh issue
create` there rather than pretending `author`/`implement` are available.

- **tirith + cron allowlists extended:** `hyperdx.jkrumm.com` joined both
  `patches/tirith-hermes-guards.patch`'s `_ALLOWED_PIPELINE_HOSTS` and
  `patches/cronjob-tools-allowlist-argo-bearer.patch`'s trusted-suffix tuple —
  same shape as the argo/karakeep/research entries, since the `clickstack_sql`
  curl is a `curl | grep | sed | jq` pipeline (see *Local Modifications*).
- **No ClickHouse HTTP (8123) on the tailnet.** `vps/compose.monitoring.yml`
  publishes no host port for it — only `:13133` (OTel collector health) is
  tailnet-bound. All querying goes through HyperDX's own MCP/REST, never a
  direct ClickHouse connection from the mini.
- **HomeLab has no parallel stack.** The VPS is the sole ClickStack instance;
  HomeLab only monitors it via UptimeKuma (`homelab/uptime-kuma/monitors.yaml`).
