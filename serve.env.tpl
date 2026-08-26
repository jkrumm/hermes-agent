# Secret refs for `hermes serve` (:9119) — the JSON-RPC/WebSocket backend Hermes
# Desktop connects to. Consumed by scripts/hermes-serve-launch.sh via
# `secrets-run run --env-file=`, never by the gateway.
#
# DELIBERATELY SEPARATE FROM .env.tpl, and that separation is load-bearing.
# `secrets-run` fails ATOMICALLY on any unresolvable ref, and config.yaml's
# `secrets.command` renders .env.tpl at gateway startup — so a ref added there
# before it is sealed into the offline cache does not degrade the gateway, it
# renders ZERO secrets and brings it up credential-less. The same file is also
# what hermes-liveness.sh counts against, so the gap would suppress the heartbeat
# and page for a gateway that was fine until the moment it restarted. A second
# template scopes that blast radius to the one service the refs belong to: serve
# refuses to start, and nothing else notices.
#
# All three are op:// rather than literals because config.yaml is tracked in a
# PUBLIC repo. Username is half a credential; a scrypt hash there would be an
# offline-crackable artifact. SECRET signs the session cookie — without it every
# restart invalidates every Desktop session, which presents as "Desktop keeps
# logging me out" rather than as a missing config value.
HERMES_DASHBOARD_BASIC_AUTH_USERNAME=op://mini/hermes-serve/username
HERMES_DASHBOARD_BASIC_AUTH_PASSWORD=op://mini/hermes-serve/password
HERMES_DASHBOARD_BASIC_AUTH_SECRET=op://mini/hermes-serve/session-secret
