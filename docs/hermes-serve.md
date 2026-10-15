# `hermes serve` — the Hermes Desktop backend

**Restored 2026-10-15** (owner decision: Hermes Desktop on the MacBook, Slack, the `:8642` API
server and the CLI are the surfaces; Collie stays as it is). It had been torn down on 2026-09-07
together with the third-party WebUI clone in `797af74`; the WebUI stays gone. This revision is
adapted to v0.22.2's serve and auth model.

Upstream's **own** desktop client (`apps/desktop/`, Electron) does not talk to the Slack gateway
and **cannot** use the OpenAI-compatible API on `:8642`. It speaks to `hermes serve`: a
JSON-RPC/WebSocket backend whose load-bearing routes are `GET /api/status` (public, auth
discovery), `POST /api/auth/ws-ticket` (single-use, 30 s WebSocket ticket, needs a session
cookie) and `WS /api/ws` (the live session; the ticket rides the `hermes-gateway-ticket.<t>`
subprotocol next to `hermes-gateway-v1`). `:8642` has none of these. **It is a separate process
from `hermes gateway`, and upstream expects both to run.** Slack does not move to it.

| Piece | Where |
|-|-|
| Launcher | `scripts/hermes-serve-launch.sh` → `.hermes/bin/hermes serve --host 127.0.0.1 --port 9119 --skip-build` |
| Service + heartbeat plists | `launchd/com.jkrumm.hermes-serve{,-liveness}.plist.template` (KeepAlive / 300 s) |
| Gate trigger | `config.yaml` → `dashboard.public_url: https://hermes-api.mini.jkrumm.com` |
| Auth refs | `serve.env.tpl` → `op://mini/hermes-serve/{username,password,session-secret}` (listed in `dotfiles-private/headless.refs`) |
| Door | `dotfiles/config/Caddyfile` → `hermes-api.test` ⇒ `https://hermes-api.mini.jkrumm.com` (`make caddy-tailnet`) |
| Monitor | homelab `uptime-kuma/monitors.yaml` → `Hermes Serve - Push` (push URL `op://hermes/uptime-kuma/serve-push-url`) |
| Logs | `~/Library/Logs/hermes-serve{,-liveness}.{log,err}` (declared in `dotfiles/scripts/log-rotate.sh`) |

## Desktop connection

Settings → Connections → remote gateway, persisted to Electron `userData/connection.json`:

- **URL** `https://hermes-api.mini.jkrumm.com`
- **Auth mode** `oauth`. Desktop derives it from `/api/status`: `auth_required: true` means
  `oauth`, which covers *any* gated server, password providers included. `/api/auth/providers`
  advertises `basic` with `supports_password: true`, so Desktop shows a username/password form,
  not a browser redirect.
- **Login:** username and password from the 1Password item `mini/hermes-serve`.

**In remote mode the mini is the execution boundary.** Terminal commands, file operations and
every tool run there; the MacBook only draws the UI.

## Why it is shaped this way

**Loopback bind + Caddy, not a tailnet bind.** A raw `:9119` tailnet bind could only be granted to
`tag:mac`, which means both Macs, the work laptop included: a socket that drives the agent. The
Caddy door sits on the existing `tag:devhost:443` grant (the mini alone). Do not add a second auth
layer in Caddy, because it breaks Desktop's `/api/status` discovery.

**The gate engages despite the loopback bind, on purpose.** Upstream gates a non-loopback bind
**or** a non-loopback `dashboard.public_url` (`should_require_dashboard_auth`). The second clause
exists for "reverse proxy in front of loopback", which is this setup. With the gate on and no
provider registered, serve exits (`SystemExit`) rather than serving open. `--insecure` has been a
no-op since the June 2026 hardening. Desktop-spawned loopback backends (SSH mode) are exempt from
`public_url` by design (`_desktop_loopback_auth_exempt`); this always-on server is not one of them.

**Credentials are env, not config.yaml.** The basic provider (`plugins/dashboard_auth/basic`)
reads `HERMES_DASHBOARD_BASIC_AUTH_*`, and env wins over `dashboard.basic_auth`. So the public
`config.yaml` carries only `public_url`, with no placeholder. (The 2026-08 revision used
`${VAR}` placeholders there; an unset one expanded to a literal, truthy `${VAR}` string, which
would have been a known-constant password.) The plaintext password is scrypt-hashed in memory at
startup.

**`serve.env.tpl` is deliberately NOT `.env.tpl`.** `secrets-run` fails **atomically** on any
unresolvable ref, and `config.yaml`'s `secrets.command` renders `.env.tpl` for every hermes
invocation. A serve ref placed there before it is sealed would bring the *gateway* up with zero
secrets at its next restart. The separate template scopes that blast radius to serve alone. The
gateway's refs still reach serve, because `secrets.command` runs for it too
(`Command helper: applied 28 secrets` in `hermes-serve.err`).

**The launcher counts the refs (3/3) and exits 78 below that.** A missing username or password
already makes upstream refuse (no provider). A missing `SECRET`, however, silently falls back to
a random per-process key, so every restart logs every Desktop session out. With the secret set,
a session cookie survives `kickstart -k` (verified).

**The heartbeat asserts the gate, not just liveness.** `/api/status` is public by design, so a
serve that came up ungated answers 200 and looks healthy. `hermes-serve-liveness.sh` requires
`auth_required == true` **and** a 401 on an unauthenticated ticket mint before it pings.

**Patched code runs here too.** `serve-speak-summary` (`hermes_cli/web_routers/audio.py`) is
serve-side, and serve imports patched modules once at startup. After `hermes update` or a patch
change, restart both the gateway and `launchctl kickstart -k gui/$(id -u)/com.jkrumm.hermes-serve`.

> **Two long-lived front-ends share one `~/.hermes` and one `state.db`**: the Slack gateway and
> `hermes serve`. Upstream sanctions the pair. If sessions start vanishing, interleaving or
> locking, suspect this first; `hermes serve --isolated` is the documented escape.

## Verify (from the mini)

```bash
U=https://hermes-api.mini.jkrumm.com
curl -s $U/api/status | jq '{version, auth_required}'            # 200, auth_required: true
curl -s $U/api/auth/providers                                     # basic, supports_password
curl -s -o /dev/null -w '%{http_code}\n' -X POST $U/api/auth/ws-ticket   # 401
launchctl kickstart -k gui/$(id -u)/com.jkrumm.hermes-serve       # back in ~6 s
make status                                                        # serve auth 3/3, :9119 auth_required
```

The authenticated half is `POST /auth/password-login`
(`{"provider":"basic","username":…,"password":…}`, `Origin` header set) → cookie →
`POST /api/auth/ws-ticket` → 200 `{ticket, ttl_seconds: 30}` → `wss://…/api/ws` with
subprotocols `hermes-gateway-v1, hermes-gateway-ticket.<ticket>` opens. A replayed or missing
ticket gets 403.

## Rotate the password

Edit `mini/hermes-serve` in 1Password, run `make secrets-seed` on the MacBook (it reseals the
mini's cache), then `launchctl kickstart -k gui/$(id -u)/com.jkrumm.hermes-serve`. Rotating
`session-secret` logs every Desktop out once.
