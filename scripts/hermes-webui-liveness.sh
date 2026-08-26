#!/bin/zsh
# Hermes WebUI liveness ping — LLM-free, no dependency on the gateway.
#
# Probes the WebUI's own /health on loopback and pings the UptimeKuma push URL only
# on success. Run every 5 min by com.jkrumm.hermes-webui-liveness; the paired monitor
# `Hermes WebUI - Push` runs at 360s with maxretries 0, so one skipped tick cannot page
# on its own and a real failure surfaces in ~6 min.
#
# WHY PUSH AND NOT AN HTTP PROBE FROM KUMA. The Tailscale ACL grants tag:phone →
# tag:mac on :8789 and nothing else; homelab (where Kuma runs) has no grant to the mini
# at all. Opening an inbound grant purely so a monitor can knock is new attack surface
# for a check the mini can make about itself — the same reasoning homelab's own
# monitors.yaml gives for every other MacMini monitor being push.
#
# WHY IT ASSERTS AUTH, NOT JUST /health. /health answers before the password middleware
# is wired, so a WebUI that came up with HERMES_WEBUI_PASSWORD empty — the one failure
# that actually matters, because it serves every Hermes session and memory to anyone who
# can reach the port — would still look green. Requiring the unauthenticated root to
# redirect is what makes this heartbeat mean "protected and serving" rather than
# "listening". The launcher refuses to start without the password, so this is the
# second layer, not the first.

set -u

SECRETS_RUN="$HOME/.local/bin/secrets-run"
BASE="http://127.0.0.1:8789"
export PATH="/opt/homebrew/bin:/usr/local/bin:$PATH"

[[ -x "$SECRETS_RUN" ]] || exit 0

PUSH_URL=$(timeout 10 "$SECRETS_RUN" read op://hermes/uptime-kuma/webui-push-url 2>/dev/null)
[[ -z "$PUSH_URL" ]] && exit 0   # unresolvable → no ping → UK alerts on the gap

# /health must answer 200.
CODE=$(/usr/bin/curl -s -o /dev/null -w '%{http_code}' --max-time 10 "$BASE/health" 2>/dev/null)
[[ "$CODE" == "200" ]] || exit 0

# Unauthenticated root must NOT return 200 — a 302 to the login is the healthy shape.
# Anything in 2xx means the UI is serving without a password and the ping is withheld
# deliberately: a DOWN monitor is the correct signal for an exposed WebUI.
ROOT=$(/usr/bin/curl -s -o /dev/null -w '%{http_code}' --max-time 10 "$BASE/" 2>/dev/null)
[[ "$ROOT" == 2* ]] && exit 0
[[ -z "$ROOT" ]] && exit 0

/usr/bin/curl -fsS --max-time 10 "$PUSH_URL" >/dev/null
