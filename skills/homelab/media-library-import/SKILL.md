---
name: media-library-import
description: Use when media downloads are missing from Jellyfin.
version: 1.0.0
metadata:
  hermes:
    tags: [jellyfin, media, import, library, torrent, downloads, shows, movies, pipeline]
    related_skills: [homelab/torrent-stack-diagnostics, homelab-ops, argo-api]
---

# Media Library Import Diagnostics

Use when a movie or show was downloaded but does not appear in Jellyfin, or when a completed torrent seems stuck between the download directory and the media library. This is a diagnosis skill: do not move, delete, re-download, or trigger a library mutation unless the user explicitly asks for remediation.

## User-facing operating rule

When the user says a downloaded show is missing, inspect the actual pipeline first. Do not answer from a short current container-log tail, do not lead with generic “all containers are running” status, and do not ask for the title before checking whether the filesystem identifies recent candidates. Report evidence and uncertainty plainly.

## Evidence chain

Prove each transition independently:

1. **Download source** — completed media files exist in the completed-download directory, with modification times and recognizable titles.
2. **Torrent-app state** — the authenticated queue and persistent app history show whether the torrent was seen, completed, copied, moved, or failed.
3. **Host/library destination** — the same content exists below the host directory mounted into Jellyfin, not merely in the download source.
4. **Jellyfin inventory** — Jellyfin exposes the series/movie and the expected season/episode or movie path.
5. **Notification** — an optional `Ready to Watch` message corroborates the import; its absence is not conclusive.

The evidence chain below doubles as the failure matrix: each step names the transition it proves and the interpretation rules cover the taxonomy.

## Read-only workflow

1. Load and follow `homelab/torrent-stack-diagnostics` for torrent/VPN/API checks and `argo-api` for the required endpoint reference.
2. Determine the user's time window. If “a few days ago” is stated, inspect at least 7 days; never assume the current Docker log tail covers it.
3. Query the torrent-app's persistent logs with authentication. Filter for:
   - `COMPLETED`, `COPIED`, `MOVED`
   - `COPY_FAILED`, `MOVE_FAILED`
   - qBittorrent connection failures
   - Jellyfin sync failures
   Include timestamps converted to the user's local timezone.
4. Query the authenticated current download list. Treat `torrents=[]` as only current state: completed torrents can be removed while source files remain.
5. Enumerate recently changed media files in both the completed-download source and the host-side Jellyfin library. Prefer a deterministic, read-only file listing with path, size, and mtime. Do not inspect only one capitalization or one guessed subdirectory.
6. Verify container mount configuration before interpreting paths. `/media/shows` inside Jellyfin and `/media/Shows` inside torrent-app may be separate container paths backed by the same host directory; container path spelling alone does not establish a bug.
7. Query Jellyfin for both top-level items and episodes/files, including `Path` and `DateCreated`. A successful library sync means Jellyfin read its configured library; it does not prove torrent-app imported anything.
8. Search the media notification channel for the app's `Ready to Watch` message when the Slack/API surface is available.
9. Correlate timestamps. A qBittorrent outage only explains a missing import if it overlaps the relevant completion/processing window; an outage earlier than completion is background context, not the root cause.
10. Stop at diagnosis unless the user asks to repair. If the title is identifiable from files, name it. If not, say the evidence cannot identify it rather than inventing a title.

## Interpretation rules

- **Source present, destination absent:** import pipeline failure; Jellyfin scanning is not the primary problem.
- **Source present, no `COMPLETED`/`COPIED`/`COPY_FAILED`:** likely no matching torrent-app pending configuration, a torrent added outside the app, or a scheduler path that never matched the item. Say “likely”; do not claim certainty without the app's config/history data.
- **Destination present, Jellyfin absent:** inspect Jellyfin path/mount, permissions, scan timing, and episode metadata.
- **`COPY_FAILED` or `MOVE_FAILED`:** report the exact recorded reason and source/destination paths before proposing remediation.
- **Jellyfin has the series but not the season/episode:** query episode paths and dates; do not call this a missing-series problem.
- **Current queue empty:** never conclude “nothing downloaded” without checking source files and persistent history.
- **No notification:** supporting evidence only; notifications can fail independently.

## Reporting format

Use a compact evidence-first report:

- **Found:** concrete title(s), file count, completion/mtime window, source path.
- **Missing transition:** e.g. “source → library copy absent” or “library → Jellyfin inventory absent.”
- **Correlated failures:** exact qBittorrent/Jellyfin errors and whether their timestamps overlap.
- **Conclusion:** confirmed fact followed by a clearly labelled likely cause.
- **Action boundary:** state whether anything was changed; default is “nothing moved or deleted.”

Do not bury the answer beneath a running narrative of every probe or speculative explanations.

## Relationship to other skills

- `homelab/torrent-stack-diagnostics` owns qBittorrent, torrent-app, VPN, and stack-health diagnosis.
- `homelab-ops` owns bounded infrastructure operations and prohibits improvised production mutations.
- `argo-api` owns the REST endpoint details and curl conventions.
- This skill owns the cross-system import evidence chain and the missing-Jellyfin-item interpretation.
