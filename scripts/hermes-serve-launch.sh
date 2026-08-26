#!/bin/zsh
# Hermes backend server launcher — the ProgramArguments of com.jkrumm.hermes-serve.
#
# `hermes serve` is the JSON-RPC/WebSocket backend Hermes Desktop connects to
# (`GET /api/status` for auth discovery, `WS /api/ws` for the live session). It is
# NOT the OpenAI-compatible API server on :8642 — that one serves no /api/ws at all,
# which is why argo's dashboard chat can use it and Desktop cannot. It is also not
# the Slack gateway: upstream expects both processes to run, so this is additive.
#
# Loopback bind, fronted by Caddy at https://hermes-api.mini.jkrumm.com, which
# reaches the tailnet over the existing tag:mac|phone|tablet → tag:devhost:443
# grant. A raw :9119 tailnet bind would need its own grant AND could only be
# scoped to tag:mac — which is both Macs, so it would hand the work laptop a
# socket that drives the agent. The clean door is scoped to tag:devhost, the mini
# alone. Same reasoning as the WebUI's two doors.
#
# `dashboard.public_url` is set in config.yaml precisely so the auth gate engages
# despite the loopback bind: upstream turns auth on for a non-loopback bind OR an
# operator-declared external URL, and a reverse proxy in front of loopback is
# exactly the case the second clause exists for.

set -u

SECRETS_RUN="$HOME/.local/bin/secrets-run"
TPL="$HOME/.hermes/serve.env.tpl"
HERMES_DIR="$HOME/.hermes/hermes-agent"

export PATH="/opt/homebrew/bin:/usr/local/bin:$PATH"

[[ -x "$SECRETS_RUN" ]] || { print -u2 "hermes-serve: $SECRETS_RUN missing"; exit 78; }
[[ -f "$TPL" ]]        || { print -u2 "hermes-serve: $TPL missing — run make setup"; exit 78; }

# Assert every ref resolves BEFORE handing off. This is not belt-and-braces: an
# unset ${VAR} in config.yaml expands to the LITERAL STRING "${VAR}" (verified
# against hermes_cli.config._expand_env_vars), which is truthy — so a serve that
# started without these would come up with the password literally
# "${HERMES_DASHBOARD_BASIC_AUTH_PASSWORD}", a known constant, and authenticate
# anyone who typed it. Fail closed instead.
RENDERED=$(timeout 20 "$SECRETS_RUN" export --env-file="$TPL" 2>/dev/null | /usr/bin/grep -c '^export ')
WANT=$(/usr/bin/grep -cE '^[A-Za-z_][A-Za-z0-9_]*=' "$TPL")
if [[ -z "$RENDERED" || "$RENDERED" -lt "$WANT" ]]; then
  print -u2 "hermes-serve: only ${RENDERED:-0}/$WANT auth refs resolved — refusing to start."
  print -u2 "  An unresolved ref would become a LITERAL \${...} password. Seed them:"
  print -u2 "  create op://mini/hermes-serve/{username,password,session-secret}, add the"
  print -u2 "  refs to dotfiles-private/headless.refs, then \`make secrets-seed\` on the MacBook."
  exit 78
fi

# The gateway's own 26 refs come too: serve runs the same agent with the same
# toolset, so it needs the same credentials — the identical reason the WebUI
# launcher wraps its start. Both templates, gateway first so a name collision
# resolves in favour of the serve-specific value.
#
# --skip-build: the browser dashboard's Vite bundle is not needed. Desktop speaks
# to /api/status and /api/ws directly, and an npm build inside a launchd job is a
# slow, network-dependent step that would turn a restart into a failure mode.
exec "$SECRETS_RUN" run --env-file="$HOME/.hermes/.env.tpl" --env-file="$TPL" -- \
  "$HERMES_DIR/venv/bin/python3" -m hermes_cli.main serve \
  --host 127.0.0.1 --port 9119 --skip-build
