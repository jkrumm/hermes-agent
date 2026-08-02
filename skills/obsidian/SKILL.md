---
name: obsidian
description: Read, search, and write Johannes's Obsidian vault (the PARA second brain at ~/SourceRoot/brain) via the Obsidian CLI (metadata-aware — backlinks, tags, Dataview) with a filesystem fallback. Capture notes to the inbox, create resource/inspiration notes with the right frontmatter, search by text/tag/backlink.
version: 1.0.0
metadata:
  hermes:
    tags: [obsidian, vault, notes, note, second-brain, pkm, knowledge, inbox, search, backlinks, dataview, wikilink, markdown, capture, resource, inspiration]
    related_skills: [capture, karakeep, argo-api]
---

# Obsidian

Johannes's personal knowledge vault — plain-markdown, PARA-organised, the **source of truth** of the second brain. Capture lands here; durable knowledge lives here. The vault is a **git repo** at `~/SourceRoot/brain`, shared with Claude Code (its `/brain` skill); a LaunchAgent pulls and pushes it every 5 minutes between the mini and the MacBook — on this Mac Mini it never auto-commits, so a write isn't durable until it's committed. Git is the deliberate `git diff` review + history gate. The shared machine-facing contract both agents follow is `~/SourceRoot/brain/AGENTS.md` — read it for anything this skill doesn't cover.

**Vault root:** `~/SourceRoot/brain/`
**Access:** Obsidian.app runs on this Mac Mini, so prefer the **Obsidian CLI** — it goes through Obsidian's live API (metadata cache, backlinks, Dataview). Fall back to the **filesystem** only when the CLI is unavailable.

Use the terminal. Don't say you lack access to the vault — reading and writing it is this skill.

## Access model — CLI first, filesystem fallback

**Primary — Obsidian CLI** (`/usr/local/bin/obsidian`, command form `obsidian <command> key=value`):
- `file=<name>` resolves by note name like a wikilink; `path=<folder/note.md>` is an exact path relative to the vault root.
- Quote values with spaces: `name="My Note"`. Use `\n` for newlines in `content=`.
- Confirm it's live with `obsidian version`. If that errors (Obsidian not running), use the filesystem fallback.

**Fallback — filesystem** (`~/SourceRoot/brain/**/*.md`): raw markdown read/write. Works always, but no metadata cache, no backlink/Dataview resolution, and the running Obsidian only notices on its next file-watch tick. Use only when the CLI is down.

## Vault structure (actual on disk — trust this, not older docs)

| Folder | Holds | Naming |
|-|-|-|
| `Inbox/` | Unprocessed captures — the default dump for anything unclassified | free |
| `Projects/` | Active projects (`basalt-ui`, `iu` as folders; `free-planning-poker`, `rollhook` as single notes, no folder yet) — folder-note `{name}.md` + optional `notes/`, `specs/` | — |
| `Areas/` | Ongoing areas (`Engineering`, `Health`, `Photography`, `Reading`) | — |
| `wiki/` | **Agentic knowledge** — atomic English concept notes agents grow by traversal, domain-organized (`wiki/health/peptides/`) + per-level `index.md` MOC | — |

There is **no PARA `Resources` tier** — reference material (articles, videos, books) is a `wiki/` concept note or a page under an Area; raw captures land in `Inbox/` and are promoted from there. Tasks live in TickTick, not the vault. For the authoritative traversal + write contract shared with Claude Code, see `~/SourceRoot/brain/AGENTS.md`.

## Conventions (real, in active use)

- **Frontmatter on every note.** Universal keys: `title`, `date` (`YYYY-MM-DD`), `tags` (YAML list). These are the three most-used properties in the vault.
- **Tags** are hierarchical `#topic/subtopic` (e.g. `resource/article`, `area/engineering`). In frontmatter list them without the `#`.
- **Links** are `[[wikilinks]]`; add them to relate a note to projects/areas/other notes.
- **Dates** are `YYYY-MM-DD` everywhere. Resolve "today" before writing — nothing expands date tokens for you.
- **Never write to the vault root.** Unclassified content → `Inbox/`.
- **The vault has no templates or daily notes.** The `09_Templates/` and `02_Daily/` folders were removed 2026-08-02, and the backing `templates`/`daily-notes` core plugins are disabled — never pass `template=`/`templates`, and never call any `daily:*` CLI verb (`daily`, `daily:append`, `daily:path`, `daily:prepend`, `daily:read`); they're dead. Build the full frontmatter + body yourself from the schemas below and pass it via `content=`.
- **New subfolder → new folder note.** When adding a subfolder under `Projects/<project>/` or `Areas/<area>/` that will hold more than one note, create its folder note (`{foldername}.md`) in the same write rather than leaving it for the linter to flag — see `AGENTS.md` → Reserved filenames. A pure attachment/spec bucket already covered by the parent's folder note doesn't need one.

## Durable knowledge — two layers, shared discipline with Claude Code

Durable knowledge splits into two physical trees, shared with Claude Code's `/brain` skill against the same repo. Full contract: `~/SourceRoot/brain/AGENTS.md`. `Inbox/` keeps the loose capture schema above (`title`/`date`/`tags`) — no `type`/`description`/MOC discipline.

- **Agentic knowledge — `wiki/`.** The terse, structured, **English**, cross-linked concept notes agents grow by traversal, domain-organized (e.g. `wiki/health/peptides/`). **Strict:** required frontmatter beyond the universal keys is `type` (free string, e.g. `Reference`, `Playbook`, `Concept`) + `description` (one sentence); `[[wikilinks]]` must resolve; each domain level has an `index.md` MOC.
- **Curated human surface — `Projects/`, `Areas/`.** The pages Johannes reads and writes — Area/Project folder notes (`{name}.md`, Folder Notes plugin) as overviews, plus human pages. Any language, **light** discipline: no forced `type`/`description`, `status` is his free field, and they link *down* into `wiki/` for depth rather than duplicating it. A page may be distilled from `wiki/` via Claude Code's `/distill` skill; the voice pass and publish decision are always human, never automated. Any prose you write for either layer follows the vault's root `voice.md` (writing-voice guide — verdict first, terse, no AI filler).
- Link notes with `[[wikilinks]]` — the knowledge graph, not decoration.
- Before a write to `wiki/` or the curated surface counts as done, a human reviews the `git diff` and `node .scripts/vault-lint.mjs` passes (0 errors) — necessary, not sufficient; judgment stays human.

## Frontmatter schemas by note type

Build these literally (example values shown — substitute real title/date):

```yaml
# Inbox/<slug>.md  — generic capture
---
title: "<title>"
date: 2026-06-17
tags: [inbox]
---

# Inbox/<title>.md  — article (captured; promoted to wiki/ or an Area later)
---
title: "<title>"
date: 2026-06-17
tags: [resource/article]
url: "https://…"
author: "<author>"
---

# Inbox/<title>.md  — YouTube (captured; promoted later)
---
title: "<title>"
date: 2026-06-17
tags: [resource/youtube]
url: "https://…"
channel: "<channel>"
---

# Projects/<project>/notes/inspiration-<slug>.md
---
title: "<title>"
type: inspiration
category: ""   # architecture | feature | competitor | tool | research
relevance: ""  # high | medium | low
date: 2026-06-17
tags: [inspiration]
url: ""
author: ""
project: "[[<project>]]"
---

# Projects/<name>.md  — project folder note
---
title: "<name>"
type: project
status: personal
lifecycle: active   # active | paused | completed — the Projects dashboard Dataview filters on this key, not status
tags: [project]
dateCreated: 2026-06-17
repo: ""
---
```

## Read / query (CLI)

```bash
obsidian version                                   # liveness check (gate the CLI path)
obsidian search query="deep modules" format=json   # full-text search → matching files
obsidian search:context query="ACWR" limit=10      # search WITH matching line context
obsidian read path="Areas/Engineering/north-star-stack.md"
obsidian files folder="Inbox"                      # list notes in a folder
obsidian backlinks file="basalt-ui" format=tsv     # what links to a note
obsidian links file="basalt-ui"                    # outgoing links from a note
obsidian tags                                      # all tags in the vault
obsidian properties counts format=tsv              # all frontmatter properties + usage counts
obsidian outline path="…"                          # heading structure of a note
```

**Dataview escape hatch** — for queries beyond search/backlinks, run JS in Obsidian's context via `eval` (Dataview API is loaded):

```bash
obsidian eval code="app.plugins.plugins.dataview.api.pages('\"Projects\"').where(p => p.status=='active').length"
```

## Write (CLI)

```bash
TODAY=$(date +%F)

# Capture an unclassified note to the inbox (the default "note this" target)
obsidian create path="Inbox/<slug>.md" content="---
title: \"<title>\"
date: $TODAY
tags: [inbox]
---

# <title>

<body>"

# Save an article as a capture (lands in the inbox; promoted later)
obsidian create path="Inbox/<title>.md" content="---
title: \"<title>\"
date: $TODAY
tags: [resource/article]
url: \"<url>\"
author: \"<author>\"
---

# <title>

## Summary

<summary>"

# Append under an existing note; set a single frontmatter property
obsidian append path="<path>" content="\n## New section\n…"
obsidian property:set name=status value=completed type=text path="Projects/<name>.md"

# Move / rename / delete (delete needs explicit confirmation)
obsidian move file="<name>" to="Areas/Engineering"
obsidian delete path="<path>"        # ask the user first; add `permanent` to skip trash
```

## Workflows

- **"note this / remember this / add to my notes"** → create in `Inbox/` (generic frontmatter). Inbox is the trusted dump; processing into Projects/Areas or `wiki/` happens later.
- **"save this article / video"** → capture note in `Inbox/` with `url` + `author`/`channel` (promoted to `wiki/` or an Area later).
- **"inspiration / competitor / tool for project X"** → `Projects/X/notes/inspiration-<slug>.md`.
- **"what do I have on X" / "find my note about X"** → `search` / `search:context`, then `read` the hit.
- **"what links to / relates to Y"** → `backlinks` + `links`.

## Routing — where a capture goes

The `capture` skill routes; this is the shared model:

- **Obsidian** (this skill) — a durable thought, idea, or piece of knowledge to develop; a reference note you'll edit/link.
- **KaraKeep** (`karakeep` skill) — a link/article to read or keep later (let it crawl + AI-tag). Reference you consume, not author.
- **TickTick** (via `capture`) — something a human must do.
- **GitHub** (`capture`) — a concrete code change.

## Guardrails

- **Do not write journal entries.** The voice-first journal is a separate, paused subsystem with its own tone rules and ingest pipeline — currently blocked pending a new vault target (see `journal/PRD.md`). If asked to journal, say it isn't wired up yet rather than improvising an entry.
- **Never write to the vault root**; unclassified → `Inbox/`.
- **The `daily:*` and `template:*`/`templates` CLI verbs are dead.** Their backing core plugins (`daily-notes`, `templates`) are disabled and the `02_Daily/`/`09_Templates/` folders were removed 2026-08-02. Never call them. If asked to "add to my daily note", say daily notes were retired rather than improvising a location.
- **Confirm before delete, move, or overwrite** an existing note. Prefer `append`/`property:set` over rewriting a whole file.
- **Sync is git, not automatic.** A LaunchAgent pulls and pushes `~/SourceRoot/brain` every 5 minutes; on this Mac Mini it never auto-commits. A write isn't durable until it's committed — after writing, commit (the human reviews `git diff`).
- **Always name the vault in the git command — `git -C ~/SourceRoot/brain …`.** A bare `git commit` is **refused** by the local repo-write guard (`raw_repo_write`), which blocks every git write that does not state which repo it is writing to. That guard exists because Hermes was observed committing straight to a code repo's `master` instead of using the dispatch bridge. The vault is the single exemption — it is denied by the dispatch policy, so there is no episode to route through — but the exemption only applies when the command *names* it:
  ```bash
  git -C ~/SourceRoot/brain add -A
  git -C ~/SourceRoot/brain commit -m "note: <what changed>"
  ```
  Every other repo under `~/SourceRoot` is off-limits to git writes entirely; those go through `claude-dispatch`.
- **Reading on the Kobo e-reader** (selected vault notes → KOReader) is a separate, planned surface (Readeck, Phase 4) — not this skill yet.
