#!/bin/zsh
# Hermes WebUI launcher — the ProgramArguments of com.jkrumm.hermes-webui.
#
# The WebUI is a third-party app (github.com/nesquena/hermes-webui) checked out at
# ~/SourceRoot/hermes-webui. That clone is upstream's tree and stays that way: every
# local decision — which port, which python, where the password comes from — lives
# here, in git, so the checkout can be deleted and re-cloned without losing setup.
#
# WHY A WRAPPER AT ALL. The retired gateway wrapper (gateway-cache-launch.sh) died
# because `hermes gateway install` regenerates its plist and drops the wrapper. Nothing
# regenerates this plist except `make setup` in this repo, so that failure mode does
# not apply — and the wrapper buys the thing that matters: the password reaches the
# process as an environment variable resolved at launch, so there is no plaintext
# secret on disk. That is the same trade the gateway itself makes via config.yaml's
# `secrets.command`.
#
# WHY NO FALLBACK. `secrets-run read` is the only password source. A "use op://, else
# read this file" ladder is how a bootstrap becomes the real dependency (see the
# GITHUB_TOKEN note in CLAUDE.md for the same mistake one repo over). If the ref does
# not resolve the WebUI does not start, `make status` says so, and the paired UptimeKuma
# push monitor goes DOWN within ~6 min. A WebUI that is down is strictly safer than one
# serving on a credential nobody can rotate.

set -u

REPO="$HOME/SourceRoot/hermes-webui"
SECRETS_RUN="$HOME/.local/bin/secrets-run"
PASSWORD_REF="op://mini/hermes-webui/password"

# launchd hands the job a minimal PATH. secrets-run needs sops+jq from Homebrew, and
# `timeout` resolves there too. Prepend, never replace — the WebUI shells out to git.
export PATH="/opt/homebrew/bin:/usr/local/bin:$PATH"

if [[ ! -d "$REPO" ]]; then
  print -u2 "hermes-webui: $REPO is missing — re-clone it, then \`make setup\`."
  exit 78  # EX_CONFIG
fi

if [[ ! -x "$SECRETS_RUN" ]]; then
  print -u2 "hermes-webui: $SECRETS_RUN is missing — dotfiles is not installed."
  exit 78
fi

# `timeout` bounds a stuck backend. On the mini the cache backend never prompts, but a
# misconfigured backend=op would block on biometrics forever and launchd's KeepAlive
# would never see the process fail.
HERMES_WEBUI_PASSWORD=$(timeout 15 "$SECRETS_RUN" read "$PASSWORD_REF" 2>/dev/null)
if [[ -z "$HERMES_WEBUI_PASSWORD" ]]; then
  print -u2 "hermes-webui: $PASSWORD_REF did not resolve — refusing to start."
  print -u2 "  Seed it: create the item in 1Password, add the ref to"
  print -u2 "  dotfiles-private/headless.refs, then \`make secrets-seed\` on the MacBook."
  exit 78
fi
export HERMES_WEBUI_PASSWORD

# Non-secret config, deliberately literals here rather than in the clone's .env.
# start.sh sources .env with `set -a` AFTER inheriting our environment, so a stale
# .env would silently win over everything exported here — which is exactly how the
# rotated password would have failed to take effect. `make setup` deletes that file
# and `make status` asserts it stays gone.
export HERMES_WEBUI_AGENT_DIR="$HOME/.hermes/hermes-agent"
export HERMES_WEBUI_PYTHON="$HOME/.hermes/hermes-agent/venv/bin/python"
export HERMES_HOME="$HOME/.hermes"
# Loopback only. Tailscale Serve is the sole ingress (dotfiles-private's
# tailscale-serve.mini.conf publishes :8789 → 127.0.0.1:8789, tailnet-only, never
# funneled), and the ACL narrows reachability to tag:phone. Binding 0.0.0.0 here
# would put the UI on every LAN the mini touches and silently bypass both.
export HERMES_WEBUI_HOST="127.0.0.1"
export HERMES_WEBUI_PORT="8789"

# --foreground keeps the server as launchd's direct child, so KeepAlive tracks the
# real process instead of a bootstrap shim that exits 0 after spawning it.
exec "$REPO/start.sh" --foreground
