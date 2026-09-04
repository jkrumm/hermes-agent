# Hermes WebUI (third-party browser UI)

Moved verbatim out of `CLAUDE.md` (2026-09-04, size pass). `CLAUDE.md` § Hermes WebUI points here — nothing was rewritten, only relocated.

A **third-party** app — `github.com/nesquena/hermes-webui`, cloned at
`~/SourceRoot/hermes-webui` — that reads `~/.hermes` directly and gives Hermes a browser
UI, used from the iPhone. It is Python + vanilla JS despite what its README-adjacent
material suggests, and it deliberately runs inside the **gateway's own venv**
(`HERMES_WEBUI_PYTHON`): its only hard deps are `pyyaml` + `cryptography`, both already
there, and upstream's design expects `HERMES_WEBUI_AGENT_DIR` to point at a real agent
install. That coupling is the one thing to remember when touching either — a WebUI dep
bump lands in the venv the gateway runs from.

**The clone is upstream's tree and stays that way.** Every local decision lives in this
repo, so the checkout can be deleted and re-cloned without losing setup:

| Piece | Where |
|-|-|
| Launcher (env + secret resolution) | `scripts/hermes-webui-launch.sh` |
| Service definition | `launchd/com.jkrumm.hermes-webui.plist.template` |
| Heartbeat | `scripts/hermes-webui-liveness.sh` + its own plist template |
| Tailnet ingress, phone | `dotfiles-private/tailscale-serve.mini.conf` (`:8789`) + ACL `tag:phone → tag:mac tcp:8789` |
| Tailnet ingress, Macs | `dotfiles/config/Caddyfile` → `hermes-web.test` ⇒ `https://hermes-web.mini.jkrumm.com` |
| Password | `op://mini/hermes-webui/password` |
| Monitor | homelab `uptime-kuma/monitors.yaml` → `Hermes WebUI - Push` |

**Two doors, and both stay.** `https://mini.<tailnet>.ts.net:8789` is the
`tailscale serve` row — tailscaled mints its own cert, so it needs no Cloudflare, no
DNS token and no Caddy, and it is what the **phone** is configured against.
`https://hermes-web.mini.jkrumm.com` is the mini's Caddy clean door, and it is the one
the **MacBook** uses. That split is forced by the ACL, not by taste: the serve row's
grant is `tag:phone → tag:mac`, and **both Macs are `tag:mac`** — so widening it to
reach the MacBook would equally hand the *work* laptop a UI that reads every Hermes
session, memory and log. The clean door is already scoped to the additive `tag:devhost`,
which the mini alone carries, so it expresses exactly the distinction the port grant
cannot. Adding it was one `hermes-web.test` block; `caddy-tailnet.sh` derives the
hostname from the Caddyfile automatically. **No `portdoor` flag** — that would make Caddy
bind 8789 on the tailnet interface and collide head-on with the serve row.

**`.env` in the clone must not exist, and `make status` asserts that.** `start.sh` sources
it with `set -a` *after* inheriting the launcher's environment, so a stale file silently
overrides everything exported — including the password. That is not hypothetical: it is
precisely how a rotation would appear to succeed and change nothing.

**The launcher resolves the gateway's whole `.env.tpl`, not just the password — and that
is load-bearing.** The WebUI runs its **own in-process agent**, reading the same
`~/.hermes/config.yaml`, whose `base_url: ${OPENAI_BASE_URL}` and 25 sibling
placeholders are expanded by `secrets.command` **at `hermes_cli.main` startup**. The
WebUI is not that entry point — `server.py` imports the agent modules directly — so the
placeholders reached httpx unexpanded and every model call died. The symptom names
nothing: the UI says *"Error: Connection error."*, and the log says
`base_url=${OPENAI_BASE_URL} exception_chain=APIConnectionError <- UnsupportedProtocol`
— httpx refusing a URL whose scheme is a literal `$`. The fallback model fails
identically, because it shares the same placeholder, and the **gateway looks perfectly
healthy throughout** since it resolved its own secrets normally. So the launcher wraps
`start.sh` in `secrets-run run --env-file=~/.hermes/.env.tpl`. There is no smaller set
that works: the WebUI runs the agent with its full toolset, so it needs what the gateway
needs.

**The launcher has no fallback, deliberately.** `secrets-run read op://mini/hermes-webui/password`
is the only source; an unresolvable ref exits 78 with instructions and the service does not
start. A "use 1Password, else read this file" ladder is how a bootstrap becomes the real
dependency (the `gho_` GITHUB_TOKEN note under the dispatch bridge is the same mistake one
repo over). A WebUI that is down is strictly safer than one serving on a credential nobody
can rotate — it holds every session, memory and log the agent has.

**The heartbeat asserts auth, not just liveness.** `/health` answers before the password
middleware is wired, so a WebUI that came up with an empty password would look green on a
naive probe — and that is the single failure that matters here. `hermes-webui-liveness.sh`
therefore requires `/health` → 200 **and** unauthenticated `/` → non-2xx (a 302 to the
login) before it pings. Anything else withholds the ping, and `Hermes WebUI - Push` goes
DOWN in ~6 min. **Push and not an HTTP probe** because the ACL grants `tag:phone → tag:mac`
on `:8789` and nothing else: Kuma on homelab has no grant to the mini at all, and opening
an inbound one purely so a monitor can knock is new attack surface for a check the mini can
make about itself. Every other MacMini monitor is push for the same reason.

> **How this got here, and what it cost.** Hermes built the whole thing unattended on
> 2026-08-25 from a handover prompt, and the *infrastructure judgement was good* — it
> caught that the requested `:8787` was already Collie's, picked a dedicated `:8789`
> rather than overwriting it, refused to bind `0.0.0.0`, and wrote a correctly-scoped
> declarative ACL grant. What it got wrong was everything about **durability and
> secrets**: a plaintext password in a `.env` inside a third-party checkout, the same
> password posted to Slack in clear, a hand-written `com.parantoux.hermes-webui` plist
> under a foreign reverse-DNS prefix that no `make` target owned, logs in `~/.hermes`
> where nothing rotates them, and no monitor at all — so a service that had just been
> made reachable from a phone was invisible the moment it died. It also committed and
> pushed the ACL change to `dotfiles-private` directly, which is a separate finding:
> the `raw_repo_write` guard should have refused and did not (see the newline bypass
> under *Local Modifications*). The lesson is not "don't let it build things" — the
> ports and the ACL were better than a rushed human would have done. It is that **an
> agent optimises for the thing working now**, and every property that only matters
> later — rotation, ownership, rotation of logs, a monitor — has to be someone else's
> checklist.
