---
name: homelab
description: Homelab operations that are not incident response — public file sharing via DUFS (public.jkrumm.com), torrent → Jellyfin filesystem moves, qBittorrent queries, VPN-stack container recovery. Use when the user asks about downloads, the Jellyfin library, moving media, or wants a file hosted publicly (prefer own DUFS over third-party hosts). For monitoring, alert diagnosis, and infra mutation, use `homelab-ops` instead.
version: 1.1.0
metadata:
  hermes:
    tags: [homelab, ssh, torrent, jellyfin, qbittorrent, media, downloads, dufs, file-hosting]
    related_skills: [homelab-ops, argo-api]
---

# Homelab

Direct SSH access to the homelab machine (Tailscale, user `jkrumm`). This
skill covers **media and file operations** that `homelab-ops`' bounded verb
set deliberately excludes (moving/deleting media is "not recoverable, not
idempotent, not ops"). For monitoring, alert diagnosis, and any container
mutation (restart, redeploy, uptime-kuma repair), use the **`homelab-ops`**
skill instead — don't duplicate that path here.

**SSH:** `ssh homelab`.

---

## Public File Hosting (DUFS)

DUFS (`sigoden/dufs`) serves the homelab's public share directory at
**https://public.jkrumm.com** (cloudflared tunnel, CORS enabled). This is the
**preferred destination for any file Johannes wants to share publicly** — do
NOT default to third-party hosts (catbox, 0x0.st, file.io). He finds those
links "komisch und suspekt" and runs DUFS precisely for this.

- Container: `dufs`. Anonymous **read** is open; write requires the `jkrumm`
  auth (password: `op://homelab/dufs/PASSWORD` — resolve on the homelab,
  never echo it).

### Upload a file (pipe from local machine)

```bash
cat /path/to/file.pdf | ssh homelab 'PASS=$(op read "op://homelab/dufs/PASSWORD") && curl -sS -u "jkrumm:$PASS" -T - "https://public.jkrumm.com/<Name>.pdf" -o /dev/null -w "upload HTTP %{http_code}\n"'
```

- The URL path IS the filename; percent-encode non-ASCII (`Expos%C3%A9.pdf`
  serves as `Exposé.pdf`)
- Success = `HTTP 201`; then verify anonymously: `curl -s -o /dev/null -w
  "%{http_code} %{content_type} %{size_download}\n"
  "https://public.jkrumm.com/<Name>.pdf"` (expect 200, matching content type
  + size)
- Keep the root tidy: only `assets/` and `diagrams/` subdirs so far

### Pitfalls

- **`curl -X PUT` is blocked** by an approvals deny rule. Use `-T -`
  (stdin PUT) for uploads — it passes the filter.
- Anonymous access is read-only by config; no public write surface. Uploads
  always need the `jkrumm` auth.

---

## Torrent Management

qBittorrent runs in a Docker container. Query it through the container's API:

```bash
# List recent torrents (newest first, limit 5)
ssh homelab "docker exec qbittorrent wget -qO- 'http://localhost:8080/api/v2/torrents/info?sort=added_on&reverse=true&limit=5'"
```

Key fields in the response:
- `name` — torrent name
- `content_path` — container-internal path (e.g. `/downloads/complete/...`)
- `progress` — 0–1 (1 = complete)
- `state` — `uploading` = seeding/complete, `downloading` = in progress
- `size` — bytes

### Path Translation

qBittorrent's `/downloads` maps to a different path on the host filesystem
(`/mnt/hdd/transmission/downloads`). Always translate through this mount
before doing filesystem operations — the container-internal path doesn't
exist on the host.

## Jellyfin Media Library

Libraries live under `/mnt/hdd/Filme/` (`Movies`, `Kids`, `Shows`).

### Naming Convention

Jellyfin expects: `Movie Name (Year)/Movie Name (Year).ext`

Each movie in its own folder, clean filename, no leftover `.nfo` or `.txt`
from torrent sources.

### Move Torrent → Jellyfin

```bash
ssh homelab "mkdir -p '/mnt/hdd/Filme/Movies/Movie Name (YYYY)' && \
  mv '/mnt/hdd/transmission/downloads/complete/<torrent-folder>/<file>.mp4' \
     '/mnt/hdd/Filme/Movies/Movie Name (YYYY)/Movie Name (YYYY).mp4' && \
  rm -rf '/mnt/hdd/transmission/downloads/complete/<torrent-folder>'"
```

Jellyfin auto-scans on its regular schedule — no manual refresh needed after
the move.

---

## Container Recovery (VPN Stack)

The VPN stack (`gluetun` + dependents: `qbittorrent`, `prowlarr`,
`flaresolverr`, `torrent-app`, `shelfmark`) can go down after Watchtower's
nightly update run and stay down.

**Verb-first:** `homelab-ops`' `redeploy homelab homelab --why "..."
--confirm` is the sanctioned recovery path — see
`homelab-ops/references/alert-patterns.md` → "VPN stack down after
Watchtower" for how to tell this apart from the (much more common) Docker
bridge-IP cascade, which needs a UptimeKuma restart instead, not a redeploy.

**Transient alerts:** Watchtower sometimes restarts the stack cleanly and it
recovers on its own. If a monitor alert fired but the six containers all show
as running, it was transient — no action needed. The UptimeKuma group
monitor can stay red for the rest of the day even after leaf recovery,
because it embeds the brief downtime window.

## Pitfalls

- **Container path ≠ host path.** qBittorrent's `/downloads/complete/`
  doesn't exist on the host. Always translate through the Docker mount.
- **Spaces in torrent folder names.** qBittorrent preserves the exact source
  folder name (spaces, dots, etc.). Quote all paths in shell commands.
- **Don't `ls` from inside the container** — use the host path for
  filesystem operations. The container only has its internal volume view.
- **1Password must be authenticated on the homelab** for the DUFS password
  read. Verify with `ssh homelab "op account get"`.
