---
name: torrent-stack-diagnostics
description: Diagnose idle torrents, VPN/API health, and stack updates.
version: 1.0.0
metadata:
  hermes:
    tags: [torrent, qbittorrent, gluetun, vpn, prowlarr, flaresolverr, queue, download, watchtower, self-healing, homelab]
    related_skills: [homelab-ops, argo-api]
---

# Torrent Stack Diagnostics

Use for questions about a torrent not downloading, qBittorrent connectivity, the torrent-app queue, VPN safety, morning stack updates, or self-healing.

## Core rule

Do not equate `container=running`, UptimeKuma `UP`, or a scheduler message such as `job executed successfully` with a functioning download. A useful diagnosis must separate:

1. **Process health** — containers are running and not restarting.
2. **VPN health** — Gluetun is healthy, public IP is the VPN exit, and forwarded port is active.
3. **Application/API health** — torrent-app and qBittorrent APIs respond and authenticate.
4. **Queue state** — the expected item exists, has the intended status, and is not skipped or paused.
5. **Transfer health** — trackers/peers and byte/rate progress show actual downloading.

## Read-only workflow

1. Use the bounded homelab operations dispatcher for container state and logs:
   - `hermes-ops.sh containers homelab --json`
   - `hermes-ops.sh logs homelab torrent-app 200 --json`
   - `hermes-ops.sh logs homelab qbittorrent 120 --json`
   - `hermes-ops.sh logs homelab gluetun 120 --json`
   - `hermes-ops.sh logs homelab vpn-watchdog-logs 120 --json`
2. Check the named monitors for `Torrent`, `VPN Watchdog`, and `Auto-Update`; inspect leaf monitors rather than only group status.
3. Run `hermes-ops.sh env-check --json` before attributing cron/update failures to missing secrets.
4. Read the torrent-app logs for concrete actions, not just scheduler cadence. Repeated `_process_torrents ... executed successfully` with no add/resume/error/status details is evidence of insufficient observability, not proof the queue is healthy.
5. Reach the public app and verify `/health` and `/api/health`. The app's protected endpoints require its own bearer token; an unauthenticated `401` on `/api/downloads` is an auth failure for the probe, not evidence that the service is down.
6. In an authenticated browser session, inspect the app's queue and history endpoints:
   - `GET /api/downloads`
   - `GET /api/downloads/global/history?hours=24`
   - `GET /api/health/vpn`
   The token is stored by the frontend under `localStorage` key `torrent_app_token`; never expose its value in Slack or logs.
7. Correlate the app queue with qBittorrent state: existence, state (`downloading`, `paused`, `stalled`, etc.), progress, download rate, tracker status, peers, category, and save path.

## Interpreting common results

- Gluetun healthy + VPN watchdog `OK` + forwarded port present rules out a broad VPN outage, but not qBittorrent API or tracker problems.
- qBittorrent and torrent-app running with `health=none` means Docker cannot detect internal failure; treat this as a monitoring gap.
- Scheduler success without a concrete queue action can mean empty queue, deduplication, a skipped business rule, paused item, or swallowed qBittorrent/API error.
- A successful browser request to protected endpoints proves the API path works; direct curl without the app bearer token does not.
- A green group monitor is only an aggregate symptom. Count and inspect leaf monitors.

## Auto-update and self-healing verification

The torrent stack may be intentionally updated by a dedicated morning job, while the rest of the homelab is handled by Watchtower. Verify the torrent-specific mechanism from its own monitor and logs; do not infer its scope from Watchtower's generic `Scanned=N` count.

For a morning run, verify:

- the `Auto-Update` push monitor is current;
- the torrent containers' start timestamps align with the update window;
- the update log reports success and no failures;
- qBittorrent, torrent-app, Gluetun, Prowlarr, and FlareSolverr all return running afterward;
- the VPN exits safely and the forwarded port is restored;
- the queue and transfer state survived/recovered after recreation.

Self-healing coverage must be described by failure class. Existing VPN/Watchdog and container restart behavior does not automatically recover a logically stuck download. A proper functional watchdog should test API reachability plus queue/transfer progress, not only container state.

## Do not mutate prematurely

Do not restart the stack merely because a torrent is idle when VPN, containers, scheduler, and API health are green. First inspect the authenticated queue, qBittorrent state, and recent app logs. Use bounded remediation only after identifying a wedged container or a documented transient failure. Code-level queue logic or missing observability belongs in a code-change escalation, not improvised production edits.

## Reference

Endpoint discovery and the evidence matrix live in the app itself and in
`hermes-ops.sh`'s read verbs — there is deliberately no checked-in copy to drift.
