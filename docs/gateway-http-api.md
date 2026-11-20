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
`system_message` is the marker: `api_server_turn_profiles` in `config.yaml` matches "This turn comes from Iris", preloads the iris skill into the system prompt and rewrites the message's "Load skill_view('iris') and follow it" into "Follow the iris skill, which is already loaded" (applied once per admission in `admit_api_steps`, `docs/patches.md`). The skill ends every reply with one
```` ```iris ```` block (`{"kind","headline"}`; the spoken line is Iris's own `triage`). Legacy app builds append `The owner picked: <Mode>.`
Stream events (`gateway/platforms/api_server.py`, `_handle_session_chat_stream`): `assistant.delta`,
`tool.started` / `tool.completed` / `tool.failed` (`{message_id, tool_name, preview, args}`), `assistant.completed`
(`content`), `run.completed`, `done`. The skill, its note script and the validation recipe: `skills/iris/`. `SKILL.md` is the preloaded core (turn rules, decide table, reply, closing block); `references/note.md` (brain-note filing) and `references/artifacts.md` (`iris-show` / `iris-doc` fences) load only for a note or an artifact memo, so a chat turn pays for the core alone. Iris's own `IRIS_SYSTEM_MESSAGE` (iris repo, `server/src/adapters/hermes.ts`) is untouched.
**`assistant.delta` is live but bursty after thinking** (Issue 681): with adaptive thinking at `high`, Haiku 5.5 flushes the
thinking summary and a short answer in one write, so all deltas land within ~25 ms. Hermes and the inference gateway buffer nothing;
a per-request `model_options: {"reasoning_effort": "none"}` makes text stream from the first token. Measurements:
`docs/research/2026-11-10-assistant-delta-burst.md`.

### Measured before and after (Issue 2517)

Hermes log, real Iris system message, fresh session each. Before: production turns of 2026-11-16/17 (`agent.log`).
After: 2026-11-20 on the deployed change; note memos were dry runs (no vault writes), run while the host load average
was about 110, so seconds are inflated and only token and call counts compare cleanly. The first call's cache write
also moves with the core-tool set (15 tools on 11-16, 14 on 11-20, about 2.5k tokens).

| Fresh turn | API calls | Cache-write tokens | Output tokens | Seconds |
|-|-|-|-|-|
| Chat, before (2 turns) | 2 | 31,662 (25,001 system + 6,665 `skill_view`) | 636, 657 | 7.9, 8.3 |
| Chat, after (3 turns) | 1 | 24,803 (cold, the skill is in the system prompt) | 244, 448, 324 | 3.5, 5.0, 3.9 |
| Note, before (2 turns) | 5, 4 | 43,873, 44,162 | 4,795, 5,740 | 32.2, 37.7 |
| Note, after (N1, N3, N4) | 5, 5, 6 | about 15–16k after a warm 24.8k prefix | 3,794, 4,352, 2,347 | 36, 36, 55 (load ~110) |

What changed per turn: no `skill_view('iris')` decision call (the chat turn's second call is gone; a note turn loads
`references/note.md` and `obsidian` together in its first call), and the iris text is 7.4 KB instead of 16 KB
(about 3.4k tokens instead of 6.7k). The target of 6k fewer cache-write tokens is met only against the 15-tool
baseline (31.7k to 24.8k); at the same tool set it is 3.3k, the size of the skill itself. Note-turn time is dominated by
the 2–5k output tokens of thinking at `high`; the bench (docs/model-context-reasoning.md) kept `high`.

## Cold-start stall of 2026-11-18 (Issue 2517)

A note turn (Iris memo 8afcb5) logged nothing for 35 s between `inbound message` (19:22:49) and the first
`tools.registry` line (19:23:24), then took 11 s from `Turn ended` to `response ready`. What the logs show:

- **No evict before it.** The idle-TTL evict (3750 s) for that session is at 20:26, an hour after the turn; the turn
  was a brand-new session on a gateway that had been up for 30 h. A real evict followed by a rebuild (the same
  session on 2026-11-20 08:28) took 0.2 s from `inbound message` to the registry lines: agent construction after an
  evict does not stall.
- **The event loop was alive.** `GET /health` was answered at 19:23:22, inside the silent window. The wait was in a
  worker thread before `AIAgent()` ran (pre-agent setup, session resolve, history load).
- **Host load is the best remaining candidate, not proven.** On 2026-11-20 the load average was 110 while three
  leads ran checks; a gateway restart needed over 60 s to bind the API server (`make deploy` verify gave up twice).
  Hermes logs the load average only at shutdown, so 11-18 has no record. The skills snapshot was rewritten at 19:23
  that day (a cold scan); the same scan measures 0.4 s now, so it is not the 35 s.
- **Partly reproduced.** The first agent build after a gateway restart took `init=14.3 s` at load ~110 (09:31 on
  11-20); the ten builds after it took `init` 0.04–1.0 s and 0.1–1.0 s from `inbound message` to the build. So a
  cold process pays once, and host load multiplies it. The 11-18 turn came 30 h into a process, so that does not
  explain it; a repeat now shows up as a large `init` or as a large gap with a small one (below).

Telemetry that catches a repeat: `fresh agent built: session=<8> platform=<p> init=<s>` in `gateway.log`
(`patches/session-execution-build-timing.patch`). The `inbound message` line, minus this line's timestamp, minus its
`init`, is the pre-agent setup time; `Turn ended` to `response ready` is the post-turn persistence time. A gap
above a few seconds in either with a small `init` points at setup or persistence under host load, not at agent
construction. The slow `hermes` step also shows in Iris's own traces (HyperDX, `iris-server`), which is how this was found.

<!-- MOVED-GATEWAY-HTTP: moved verbatim from the root AGENTS.md (Gateway HTTP exposure and Iris turns, 2080 bytes) -->

## Gateway HTTP Exposure (iris)

The gateway runs an OpenAI-compatible HTTP API alongside the CLI and Desktop; **iris** (the voice and chat
app on the mini) is its consumer. The argo dashboard chat was removed 2026-10-30 and its
`tag:vps → tag:mac :8642` ACL grant with it. Four env vars (framework keys in
`hermes_cli/config.py`), resolved at startup from `.env.tpl` via `secrets.command`:

| Var | Value |
|-|-|
| `API_SERVER_ENABLED` / `API_SERVER_PORT` | `true` / `8642` — literals |
| `API_SERVER_HOST` | the mini's Tailscale IP — **tailnet-only bind**, no LAN listener. `op://hermes/gateway/host` (never a literal in git) |
| `API_SERVER_KEY` | bearer gating **every** request, even loopback. `op://hermes/gateway/api-server-key` (iris reads it as `HERMES_TOKEN`) |

Rotate the key, then restart the gateway and iris. Mismatch = **401**; connection-refused = not
bound to the host iris uses. Verify and rotation steps: **`docs/gateway-http-api.md`**.

**Iris turns (Wave 21, 2026-11-04):** Iris no longer classifies voice memos — every memo except mode
Transcribe goes to Hermes as a session turn whose per-turn `system_message` says "This turn comes from Iris…
Load skill_view('iris')". `skills/iris/` decides (answer / `capture` / `obsidian` note / `herdr` tab prompt to an existing terminal / `fleet`: read fleet state, or file agent work via `factory signal file` when the memo says *start*) and
ends the reply with one ```` ```iris ```` JSON block (`kind`, `headline` only) that Iris parses; legacy builds
append `The owner picked: Journal.|Chat.|Tab.`. Brain notes are filed straight to their home (log entry, existing page, new `wiki/` note — the obsidian skill's
*Filing a note*; vault-lint, then `scripts/brain-commit.sh`'s brain-sync lock); `skills/iris/scripts/iris-note.py` is the `Inbox/` path
for journal reflections and memos with no clear home (journal frontmatter). SOUL.md has one routing row; CLI and Desktop unaffected.
Tool events for Iris's `actions`: SSE `tool.started|completed|failed`, field `tool_name`. **`docs/gateway-http-api.md`**.
