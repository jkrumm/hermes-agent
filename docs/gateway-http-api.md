# Gateway HTTP exposure (iris and the CLI)

The gateway runs an OpenAI-compatible HTTP API alongside Slack. Its consumer is **iris**
(the voice and chat app on the mini, which delivers memos into Hermes sessions); the argo
dashboard chat that used to be the other consumer was removed 2026-10-30, so the
`tag:vps → tag:mac :8642` ACL grant is gone. Controlled by four env vars (framework keys in
`hermes_cli/config.py`), resolved at startup from `.env.tpl` via `secrets.command`
(see "Secrets" above) so a rebuild never silently drops the exposure:

- `API_SERVER_ENABLED=true`, `API_SERVER_PORT=8642` — literals.
- `API_SERVER_HOST` — the Mac Mini's Tailscale IP, **tailnet-only bind** (no LAN
  listener). Stored at `op://hermes/gateway/host` (never a literal in git — security rule).
  Every consumer is on the mini (iris reads the same op item), so loopback would do; the
  switch needs the gateway and iris restarted together and is not made yet.
- `API_SERVER_KEY` — bearer that auth-gates **every** request (even loopback).
  Canonical at `op://hermes/gateway/api-server-key`; iris reads the same item as
  `HERMES_TOKEN`.

**Rotate:** edit `op://hermes/gateway/api-server-key`, restart the gateway, then restart iris
(`make launchd-restart` in `~/SourceRoot/iris`). A key mismatch surfaces as **401** in iris's
Hermes adapter; connection-refused means the gateway isn't bound to the host iris uses.

**Verify (on the mini):** `curl http://<host>:8642/health` (no auth) → 200;
`curl -H "Authorization: Bearer $KEY" .../v1/models` → 200; iris `GET /health` shows no
`degraded` entry for hermes. Local bind: `lsof -nP -iTCP:8642 -sTCP:LISTEN` must show the
tailnet IP.
