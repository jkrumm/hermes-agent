# Gateway HTTP exposure (argo dashboard chat)

Moved verbatim out of `CLAUDE.md` (2026-09-04, size pass). `CLAUDE.md` § Gateway HTTP Exposure points here — nothing was rewritten, only relocated.

The gateway runs an OpenAI-compatible HTTP API alongside Slack, so the **argo VPS
dashboard chat** can talk to Hermes. Controlled by four env vars (framework keys in
`hermes_cli/config.py`), resolved at startup from `.env.tpl` via `secrets.command`
(see "Secrets" above) so a rebuild never silently drops the exposure:

- `API_SERVER_ENABLED=true`, `API_SERVER_PORT=8642` — literals.
- `API_SERVER_HOST` — the Mac Mini's Tailscale IP, **tailnet-only bind** (no LAN
  listener). Stored at `op://hermes/gateway/host` (never a literal in git — security rule).
- `API_SERVER_KEY` — bearer that auth-gates **every** request (even loopback).
  Canonical at `op://hermes/gateway/api-server-key`.

**Shared secret (single source of truth):** the gateway's `API_SERVER_KEY` **must
equal** argo's `HERMES_API_KEY`. Canonical value = `op://hermes/gateway/api-server-key`,
mirrored to `op://vps/argo/HERMES_API_KEY`. Rotate by editing both op items to the same
value, then `ssh vps "cd ~/vps && ENV=prod make argo-env && ENV=prod make argo-up"` (argo
re-materializes its `.env` and recreates argo-api). A key mismatch surfaces as **401** on
the dashboard chat; connection-refused means the gateway isn't bound to the tailnet IP.

**Network path:** argo on the VPS holds `HERMES_BASE_URL=http://<mac-tailnet-ip>:8642/v1`
(`apps/argo/compose.yml` + `.env.tpl`). A Tailscale ACL grants `tag:vps → tag:mac` on
`tcp:8642`. The exposure needs **no gateway restart** to reconcile a key — the gateway is
static; only the argo side redeploys.

**Verify (from the VPS, reading URL+key from `apps/argo/.env`):** `curl .../health`
(no auth) → 200; `curl -H "Authorization: Bearer $KEY" .../v1/models` → 200; a real
`POST .../v1/chat/completions` returns a completion. Local bind: `lsof -nP -iTCP:8642
-sTCP:LISTEN` must show the tailnet IP, not `127.0.0.1`.
