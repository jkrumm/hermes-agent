---
name: personal-file-storage
description: Use when a file must land in the user's own archive.
version: 1.0.0
author: Hermes Agent
license: MIT
metadata:
  hermes:
    tags: [storage, archive, dokumente, documents, files, homelab, ssd, sha256, intake]
    related_skills: [homelab, karakeep, personal-finance]
---

# Filing a file into the user's own storage

When he sends a file or says "leg das in meine Dokumente", the job is not the
upload — it is the file landing in the right folder, under his filename, verified,
with the path named back to him. Leaving it in the Hermes cache
(`~/.hermes/cache/documents/…`) is a failure: that directory is scratch, not an
archive.

## When to Use

- He sends a document (contract, invoice, certificate, letter) or asks for one to
  be stored or archived.
- He asks where a document of his lives.
- Not for: a link/article he wants to re-find → `karakeep`; a durable idea or
  knowledge note → `obsidian`; a file he wants *public* → the `homelab` skill's
  DUFS path. Private documents never go to the public share.

## Where his archive lives

**Homelab, on the SSD: `/home/jkrumm/ssd/SSD/`** — `Dokumente/`, `Bilder/`,
`Bücher/`, `Hörbücher/`, `Videos/`, `Public/`, `Dev/`. "Meine Dokumente" means a
subfolder of `/home/jkrumm/ssd/SSD/Dokumente/`.

- `Dokumente/` is topic-foldered (`Steuer`, `IDs`, `Vermietung`, `Wallbox`, …).
  Pick the matching topic; when none fits, **create one** (`Auto/` for vehicle
  paperwork) rather than burying the file in the `Anderes/` catch-all.
- Two containers read the same tree: samba binds `/home/jkrumm/ssd` → `/mnt/ssd`,
  filebrowser binds `/home/jkrumm/ssd/SSD` → `/srv/ssd`. Always quote the host
  path above so the target is unambiguous.
- Keep his filename when it is meaningful — he refinds files by name.

## Procedure

1. **Pick the folder and create it if missing** (SSH to the homelab):
   `ssh homelab 'mkdir -p "/home/jkrumm/ssd/SSD/Dokumente/<Topic>"'`
2. **Copy from his machine by pipe**, then hash-check the far end:

```bash
cat /local/path/file.pdf | ssh homelab 'cat > "/home/jkrumm/ssd/SSD/Dokumente/<Topic>/<Name>.pdf" \
  && ls -la "/home/jkrumm/ssd/SSD/Dokumente/<Topic>/" \
  && sha256sum "/home/jkrumm/ssd/SSD/Dokumente/<Topic>/<Name>.pdf"'
shasum -a 256 /local/path/file.pdf    # must equal the remote hash
```

3. **Report the landing path and the hash match** in the reply — he checks it
   from filebrowser/Samba, and the path is the receipt.

## Pitfalls

- **`/mnt/ssd` and `/mnt/ssd/SSD` on the homelab are decoys**: leftover
  root-owned, **empty**, and not a mount at all (`mount | grep ssd` is silent,
  `df` resolves the real tree on the root LV). A file written there is invisible
  to samba, filebrowser and him. The tree is always `/home/jkrumm/ssd/SSD/…`.
- **`sudo` needs a password on the homelab** (no passwordless sudo), so a
  `sudo find …` returns nothing and reads like "no such folder" — explore as
  `jkrumm` with plain paths; the archive tree is his.
- **To locate a folder, `find`, don't guess**:
  `ssh homelab 'find /home/jkrumm /mnt -maxdepth 3 -type d -iname "*dokument*"'`.
  To learn what a path is exposed as, read the container mounts:
  `docker inspect <container> --format '{{json .Mounts}}'`.
- **Quote every path** — folder and file names carry spaces and umlauts.
- **Verify, never assume**: a completed `cat | ssh` is not evidence the file
  arrived complete; the matching sha256 sums are. Then read the target directory
  back.
- **Don't move or delete the original he sent** unless he asks — the archive is
  an additional copy, not a replacement.
