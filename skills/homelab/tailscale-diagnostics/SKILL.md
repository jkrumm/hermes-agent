---
name: tailscale-diagnostics
description: Diagnose Tailscale device reachability (serve, ACL, tags).
version: 1.0.0
metadata:
  hermes:
    tags: [tailscale, tailnet, serve, funnel, acl, magicdns, collie, rb, unreachable, vpn, device]
    related_skills: [homelab-ops, homelab-watchdog, argo-api]
---

# Tailscale Diagnostics

> Hostnames and tailnet addresses are placeholders on purpose — this repo is
> public. Resolve the real ones at run time:
> `/opt/homebrew/bin/tailscale status --json | jq -r .MagicDNSSuffix` for the
> tailnet, `tailscale ip -4` for a node address.

Owns the "why can't device X reach service Y" class of problem on Johannes's tailnet: reachability checks, serve/funnel mappings, ACL grants, node/tag presence, MagicDNS. Covers all tailnet-served services (Collie, rb, IU dashboard, dev vhosts) and all device classes (phone, tablet, TV, Macs, e-reader).

## When to use
- "Can't reach X anymore from iPhone / device" — especially when UptimeKuma says the service is UP but a device can't connect
- tailscale serve / funnel questions ("why is :8788 not reachable", "should X be funneled")
- ACL / tag questions, new-device onboarding, "why is my phone blocked"

## Golden rules (learned from incidents)
1. **Service-up ≠ reachable.** UptimeKuma push monitors (e.g. `MacMini Collie - Push`) only prove the process is alive and pushing heartbeats. Device reachability is gated by THREE independent things: (a) device on the tailnet with the right tag, (b) the ACL grant, (c) the serve mapping. Check all three before concluding anything.
2. **The ACL is the real access control.** The tailnet is tag-based (no human logins for `tailscale serve`). A device present but missing its tag = **silently blocked** (connection timeout, looks like "service down"). A device NOT in the peer list at all = logged out / removed / expired key — different fix entirely.
3. **Serve rows are HTTPS-only.** `tailscale serve` terminates TLS at the serve port; plain `http://` to a serve port returns **HTTP 400**. Always test/use `https://`.
4. **Tailscale CLI path pitfall (Mac Mini):** `tailscaled` runs via Homebrew. `/usr/local/bin/tailscale` is a dead wrapper pointing at the removed `/Applications/Tailscale.app` (returns nothing / "No such file or directory"). Always use **`/opt/homebrew/bin/tailscale`** — bare `tailscale` from PATH may resolve to the broken wrapper and silently fail.

## Diagnostic chain (verdict first)
1. **Service itself up?** UptimeKuma via argo (`/uptime-kuma/status` + monitor detail) AND local curl to the loopback port, e.g. `curl -s -o /dev/null -w '%{http_code}' http://127.0.0.1:8787/` → expect 200.
2. **Serve mapping active?** `/opt/homebrew/bin/tailscale serve status` — expect the row `https://<node>.ts.net:PORT (tailnet only) |-- / proxy http://127.0.0.1:<loopback>`. `--json` gives the shape `{TCP:{PORT:{HTTPS:true}}, Web:{...Handlers}}`.
3. **Test the endpoint from the host** (proves bridge + serve + Host-guard all pass): `curl -sk https://mini.<tailnet>.ts.net:8788/` → 200. Also `--resolve mini.<tailnet>.ts.net:8788:<mini-tailscale-ip>` to bypass local DNS. If this works, the fault is device/tailnet-side, not the service.
4. **Is the device on the tailnet with the right tag?** `/opt/homebrew/bin/tailscale status --json` → `Peer{}` map (note: peers list ALL tailnet devices incl. offline ones, so a missing device is truly gone, not just asleep). Check the device's `Tags` and `Online`/`LastSeen`.
5. **Does the ACL allow it?** Read `~/SourceRoot/dotfiles-private/tailscale-acl.jsonc` — find the grant for the service port; check src/dst/ip. The grant names the SERVE LISTENER port, not the loopback port.
6. **Check declared serve state** for drift: `~/SourceRoot/dotfiles-private/tailscale-serve.mini.conf`, applied via `make tailscale-serve` in dotfiles (a `serve reset` precedes re-adds — imperative `tailscale serve` bindings get wiped on next convergence). Collie runs `COLLIE_SKIP_SERVE=1` so the .conf is authoritative for it.

## Serve rows on `mini` (as of 2026-08)
| Port | Target | Funnel | Service | ACL grant |
|-|-|-|-|-|
| 7730 | http://127.0.0.1:4050 | no | rb (learning tracker, colima container) | src tag:mac, tag:client, tag:phone → dst tag:mac, tcp:7730 |
| 8443 | http://localhost:5173 | yes | IU dashboard (colima container) | funnel capability via tag:iu-dashboard-funnel (whole-device attr, never port-scoped) |
| 8788 | http://127.0.0.1:8787 | no | Collie (herdr web bridge) | src tag:phone → dst tag:mac, tcp:8788 |

## Collie specifics
- herdr plugin web bridge: bridge on `127.0.0.1:8787`, launchd agent `herdr.collie`, log `~/.config/herdr/plugins/config/herdr.collie/collie.log`, ctl script `~/.config/herdr/plugins/github/herdr.collie-<hash>/scripts/collie-ctl.sh`
- Config `.env` in the plugin config dir: `COLLIE_SKIP_SERVE=1` (serve is declared state, never imperative), `COLLIE_PUBLIC_HOSTS=mini.<tailnet>.ts.net:8788,mini.<tailnet>.ts.net`
- **"rebind guard"** in health pushes = collie's Host-header allowlist (EXACT string match, ported form `:8788` is load-bearing — bare name alone 403s phone requests while loopback still works)
- Phone URL: `https://mini.<tailnet>.ts.net:8788` (http → 400, wrong Host → 403)
- Deliberately NEVER funneled: one bridge call types arbitrary keystrokes into a live terminal pane (shell-equivalent as jkrumm). Port is the access-control decision — dedicated port per service keeps ACL grants scoped.

## Pitfalls
- First `tailscale status` attempt returning EMPTY output is the broken-wrapper symptom, not "tailnet down" — retry with `/opt/homebrew/bin/tailscale` before concluding anything.
- `funnel-ingress-node` peers (many, tag:ingress) in `status --json` are normal Tailscale funnel replicas — ignore them.
- Offline devices STILL appear in the peer list with a `LastSeen`. Absence = removed/expired/logged-out; offline = client-side power/sleep issue.
- Don't rely on `brew services list` for tailscale: Homebrew shows `none` even when tailscaled is running (launchd-managed, not brew-tracked).

## References
- Node/tag/ACL truth is the tailnet itself and `~/SourceRoot/dotfiles-private/tailscale-{acl.jsonc,serve.mini.conf}` — read those, never a copy checked in here.
