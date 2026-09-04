# `hermes serve` — the Hermes Desktop backend

Moved verbatim out of `CLAUDE.md` (2026-09-04, size pass). `CLAUDE.md` § `hermes serve` points here — nothing was rewritten, only relocated.

Upstream's **own** desktop client (`hermes desktop`, Electron, in-tree at
`apps/desktop/`) does not talk to the Slack gateway and **cannot** use the
OpenAI-compatible API on `:8642`. It speaks to `hermes serve`: a JSON-RPC/WebSocket
backend, default `:9119`, whose two load-bearing routes are `GET /api/status` (auth
discovery) and `WS /api/ws` (the live session). `:8642` has no `/api/ws` at all —
that is the whole reason argo's dashboard chat can use it and Desktop cannot.
`hermes dashboard` is the same server with a browser UI bolted on; `serve` is the
headless form. **It is a separate process from `hermes gateway` and upstream expects
both to run** — Slack does not move to it.

| Piece | Where |
|-|-|
| Launcher | `scripts/hermes-serve-launch.sh` |
| Service + heartbeat plists | `launchd/com.jkrumm.hermes-serve{,-liveness}.plist.template` |
| Auth refs | `serve.env.tpl` → `op://mini/hermes-serve/{username,password,session-secret}` |
| Door | `dotfiles/config/Caddyfile` → `hermes-api.test` ⇒ `https://hermes-api.mini.jkrumm.com` |
| Monitor | homelab → `Hermes Serve - Push` |

**Client side:** Desktop keeps a connection registry — *Settings → Gateways → Add
connection → Remote gateway* — persisted to Electron `userData/connection.json`
(`mode: local | remote | cloud | ssh`). `HERMES_DESKTOP_REMOTE_URL` /
`HERMES_DESKTOP_REMOTE_TOKEN` are the app-wide **override**, not the normal route,
and setting the URL without the token is a hard error.

**In remote mode the mini is the execution boundary.** Terminal commands, file
operations and every tool run there; the MacBook is only drawing the UI. That is the
point, but it means Desktop-on-MacBook browses the *mini's* filesystem.

**`serve.env.tpl` is deliberately NOT `.env.tpl`, and the split is the interesting
part.** `secrets-run` fails **atomically** on any unresolvable ref, and config.yaml's
`secrets.command` renders `.env.tpl` at gateway startup — so a ref added there before
it is sealed into the offline cache does not degrade the gateway, it renders **zero**
secrets and brings it up credential-less at the next restart. The same file is what
`hermes-liveness.sh` counts against, so the gap would also suppress the heartbeat and
page for a gateway that was fine until it restarted. A second template scopes the
blast radius to the one service the refs belong to: serve refuses to start and nothing
else notices.

**An unset `${VAR}` in config.yaml expands to the LITERAL STRING `${VAR}`** —
verified against `hermes_cli.config._expand_env_vars` — and that string is *truthy*.
So a serve that started with its auth refs unresolved would come up with the password
literally `${HERMES_DASHBOARD_BASIC_AUTH_PASSWORD}`: a known constant that
authenticates. The launcher therefore **counts** the rendered refs and refuses below
the full set rather than spot-checking one, and `make status` reports the same count.

**Auth engages despite the loopback bind, on purpose.** Upstream turns the gate on for
a non-loopback bind **or** an operator-declared `dashboard.public_url` — the second
clause exists exactly for "reverse proxy in front of loopback", which is this. Do not
add a second auth layer in Caddy; it breaks Desktop's `/api/status` discovery
handshake. `--insecure` is a documented no-op since the June 2026 hardening.

**The heartbeat asserts `auth_required`, not liveness.** `/api/status` is a *public*
path by design — it is how a client discovers whether auth is needed — so a serve with
a misconfigured auth provider answers 200 and looks healthy while exposing a socket
that drives the agent. `hermes-serve-liveness.sh` requires `auth_required == true`
before it pings.

> **Three front-ends now share one `~/.hermes` and one `state.db`**: the Slack
> gateway, the third-party WebUI's in-process agent, and `hermes serve`. Upstream
> sanctions gateway + serve; the WebUI is the addition. Nothing has misbehaved, but if
> sessions ever start behaving oddly — vanishing, interleaving, locking — this is the
> first thing to suspect, and `hermes serve --isolated` is the documented escape.
