#!/bin/zsh
# Hermes backend server launcher — the ProgramArguments of com.jkrumm.hermes-serve.
#
# `hermes serve` is the JSON-RPC/WebSocket backend Hermes Desktop connects to
# (`GET /api/status` for auth discovery, `POST /api/auth/ws-ticket` + `WS /api/ws`
# for the live session). It is NOT the OpenAI-compatible API server on :8642 — that
# one has no /api/ws at all. It is also not the Slack gateway: upstream expects both
# processes to run, so this is additive.
#
# Loopback bind, fronted by Caddy at https://hermes-api.mini.jkrumm.com (dotfiles
# Caddyfile `hermes-api.test`), which reaches the tailnet over the existing
# tag:devhost:443 grant. A raw :9119 tailnet bind could only be scoped to tag:mac —
# both Macs, the work laptop included. The Caddy door is scoped to the mini alone.
#
# `dashboard.public_url` in config.yaml engages the auth gate despite the loopback
# bind: upstream gates a non-loopback bind OR a non-loopback public_url, and with the
# gate on and no provider registered `hermes serve` exits rather than serve open.

set -u

SECRETS_RUN="$HOME/.local/bin/secrets-run"
TPL="$HOME/.hermes/serve.env.tpl"
HERMES_BIN="$HOME/.hermes/hermes-agent/.hermes/bin/hermes"

export PATH="/opt/homebrew/bin:/usr/local/bin:$PATH"

[[ -x "$SECRETS_RUN" ]] || { print -u2 "hermes-serve: $SECRETS_RUN missing"; exit 78; }
[[ -f "$TPL" ]]        || { print -u2 "hermes-serve: $TPL missing — run make setup"; exit 78; }
[[ -x "$HERMES_BIN" ]] || { print -u2 "hermes-serve: $HERMES_BIN missing — hermes install broken"; exit 78; }

# Assert every ref resolves BEFORE handing off. Upstream fails closed on a missing
# username/password (no provider → exit), but a missing SECRET silently falls back to
# a random per-process key, so sessions die on every restart. Count the full set.
RENDERED=$(timeout 20 "$SECRETS_RUN" export --env-file="$TPL" 2>/dev/null | /usr/bin/grep -c '^export ')
WANT=$(/usr/bin/grep -cE '^[A-Za-z_][A-Za-z0-9_]*=' "$TPL")
if [[ "$RENDERED" -lt "$WANT" ]]; then
  print -u2 "hermes-serve: only $RENDERED/$WANT auth refs resolved — refusing to start."
  print -u2 "  Seed op://mini/hermes-serve/{username,password,session-secret} (listed in"
  print -u2 "  dotfiles-private/headless.refs), then \`make secrets-seed\` on the MacBook."
  exit 78
fi

# The gateway's own refs arrive through config.yaml's `secrets.command`, which every
# hermes invocation runs — serve included — so only the serve template is passed here.
#
# Through the install's launcher (.hermes/bin/hermes, managed Python 3.14), never
# venv/bin/python3: since v0.21.6+669 the runtime is the managed interpreter and its
# committed dependency environment.
#
# --skip-build: Desktop speaks to /api/* directly; `hermes update` builds the web UI
# itself, and an npm build inside a launchd job would turn a restart into a failure mode.
exec "$SECRETS_RUN" run --env-file="$TPL" -- \
  "$HERMES_BIN" serve --host 127.0.0.1 --port 9119 --skip-build
