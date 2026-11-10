# Gateway HTTP exposure (iris and the CLI)

The gateway runs an OpenAI-compatible HTTP API (the Slack platform is gone; Iris is the chat surface). Its consumer is **iris**
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

## Iris turns

Iris posts `POST /api/sessions` `{id: <memo uuid>, source}` then `POST /api/sessions/<id>/chat/stream`
`{message: <transcript>, system_message}`. `source` is only Iris's label (unknown values map to `api_server`), so the
`system_message` is the marker: it tells Hermes to load `skill_view('iris')`, which ends every reply with one
```` ```iris ```` block (`{"kind","headline"}`; the spoken line is Iris's own `triage`). Legacy app builds append `The owner picked: <Mode>.`
Stream events (`gateway/platforms/api_server.py`, `_handle_session_chat_stream`): `assistant.delta`,
`tool.started` / `tool.completed` / `tool.failed` (`{message_id, tool_name, preview, args}`), `assistant.completed`
(`content`), `run.completed`, `done`. The skill, its note script and the validation recipe: `skills/iris/`.
**`assistant.delta` is live but bursty after thinking** (Issue 681): with adaptive thinking at `high`, Haiku 5.5 flushes the
thinking summary and a short answer in one write, so all deltas land within ~25 ms. Hermes and the inference gateway buffer nothing;
a per-request `model_options: {"reasoning_effort": "none"}` makes text stream from the first token. Measurements:
`docs/research/2026-11-10-assistant-delta-burst.md`.
