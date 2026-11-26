---
name: obsidian
description: Read, search, and write Johannes's Obsidian vault (the PARA second brain at ~/SourceRoot/brain) via the Obsidian CLI (metadata-aware — backlinks, tags, Dataview) with a filesystem fallback. File a note or memo where it belongs (a log row, an existing page, a new wiki/ note; Inbox/ only when no home is clear), create resource/inspiration notes with the right frontmatter, search by text/tag/backlink.
version: 1.0.0
metadata:
  hermes:
    tags: [obsidian, vault, notes, note, second-brain, pkm, knowledge, inbox, search, backlinks, dataview, wikilink, markdown, capture, resource, inspiration]
    related_skills: [capture, karakeep, argo-api]
---

# Obsidian

Johannes's personal knowledge vault — plain-markdown, PARA-organised, the **source of truth** of the second brain. Capture lands here; durable knowledge lives here. The vault is a **git repo** at `~/SourceRoot/brain`, shared with Claude Code (its `/brain` skill); a LaunchAgent pulls and pushes it every 5 minutes between the mini and the MacBook — on this Mac Mini it never auto-commits, so a write isn't durable until it's committed. Git history is the review trail; there is no human gate before a write counts. The shared machine-facing contract both agents follow is `~/SourceRoot/brain/AGENTS.md` — read it for anything this skill doesn't cover.

**Vault root:** `~/SourceRoot/brain/`
**Access:** Obsidian.app runs on this Mac Mini, so prefer the **Obsidian CLI** — it goes through Obsidian's live API (metadata cache, backlinks, Dataview). Fall back to the **filesystem** only when the CLI is unavailable.

Use the terminal. Don't say you lack access to the vault — reading and writing it is this skill.

## Access model — CLI first, filesystem fallback

**Primary — Obsidian CLI** (`obsidian`, first on PATH; command form `obsidian <command> key=value`):
- `file=<name>` resolves by note name like a wikilink; `path=<folder/note.md>` is an exact path relative to the vault root.
- Quote values with spaces: `name="My Note"`. Use `\n` for newlines in `content=`.
- `content=` turns **every** `\n` into a newline and `\t` into a tab, with no escape, so text holding a backslash (LaTeX, a regex, a Windows path) is corrupted. Write such text, and any body over about 4 KB, to the file directly instead.
- **The CLI exits 0 even when a command fails** (`Error: File "…" not found.`, rc 0). Read the output before reporting a write as done.
- `vault=<name>` only works as the first parameter. A file name containing a dot needs its extension (`name="v1.2 notes.md"`).
- `append` and `prepend` take `heading=<name>` to write under an existing section. Rename and move with `obsidian rename` / `obsidian move`, never `mv`: only the app rewrites the links pointing at the note.
- Confirm it's live with `obsidian version`. If that errors (Obsidian not running), use the filesystem fallback.

**Fallback — filesystem** (`~/SourceRoot/brain/**/*.md`): raw markdown read/write. Works always, but no metadata cache, no backlink/Dataview resolution, and the running Obsidian only notices on its next file-watch tick. Use only when the CLI is down.

## Vault structure (actual on disk — trust this, not older docs)

| Folder | Holds | Naming |
|-|-|-|
| `Inbox/` | Unprocessed captures — only when a note has no clear home (and journal-tagged reflections) | free |
| `Projects/` | Active projects (`basalt-ui`, `iu` as folders; `free-planning-poker`, `rollhook` as single notes, no folder yet) — folder-note `{name}.md` + optional `notes/`, `specs/` | — |
| `Areas/` | Ongoing areas (`Engineering`, `Health`, `Photography`, `Reading`) | — |
| `wiki/` | **Agentic knowledge** — atomic English concept notes agents grow by traversal, domain-organized (`wiki/health/peptides/`) + per-level `index.md` MOC | — |

There is **no PARA `Resources` tier** — reference material (articles, videos, books) is a `wiki/` concept note or a page under an Area; raw captures land in `Inbox/` and are promoted from there. Tasks live in TickTick, not the vault. For the authoritative traversal + write contract shared with Claude Code, see `~/SourceRoot/brain/AGENTS.md`.

## Conventions (real, in active use)

- **Frontmatter on every note.** Universal keys: `title`, `date` (`YYYY-MM-DD`), `tags` (YAML list). These are the three most-used properties in the vault.
- **Tags** are hierarchical `#topic/subtopic` (e.g. `resource/article`, `area/engineering`). In frontmatter list them without the `#`.
- **Links** are `[[wikilinks]]`; add them to relate a note to projects/areas/other notes.
- **Dates** are `YYYY-MM-DD` everywhere. Resolve "today" before writing — nothing expands date tokens for you.
- **Never write to the vault root.** No clear home → `Inbox/`.
- **The vault has no templates or daily notes.** The `09_Templates/` and `02_Daily/` folders were removed 2026-08-02, and the backing `templates`/`daily-notes` core plugins are disabled — never pass `template=`/`templates`, and never call any `daily:*` CLI verb (`daily`, `daily:append`, `daily:path`, `daily:prepend`, `daily:read`); they're dead. Build the full frontmatter + body yourself from the schemas below and pass it via `content=`.
- **New subfolder → new folder note.** When adding a subfolder under `Projects/<project>/` or `Areas/<area>/` that will hold more than one note, create its folder note (`{foldername}.md`) in the same write rather than leaving it for the linter to flag — see `AGENTS.md` → Reserved filenames. A pure attachment/spec bucket already covered by the parent's folder note doesn't need one.

## Durable knowledge — two layers, shared discipline with Claude Code

Durable knowledge splits into two physical trees, shared with Claude Code's `/brain` skill against the same repo. Full contract: `~/SourceRoot/brain/AGENTS.md`. `Inbox/` keeps the loose capture schema above (`title`/`date`/`tags`) — no `type`/`description`/MOC discipline.

- **Agentic knowledge — `wiki/`.** The terse, structured, **English**, cross-linked concept notes agents grow by traversal, domain-organized (e.g. `wiki/health/peptides/`). **Strict:** required frontmatter beyond the universal keys is `type` (free string, e.g. `Reference`, `Playbook`, `Concept`) + `description` (one sentence); `[[wikilinks]]` must resolve; each domain level has an `index.md` MOC.
- **Curated human surface — `Projects/`, `Areas/`.** The pages Johannes reads and writes — Area/Project folder notes (`{name}.md`, Folder Notes plugin) as overviews, plus human pages. Any language, **light** discipline: no forced `type`/`description`, `status` is his free field, and they link *down* into `wiki/` for depth rather than duplicating it. Curated pages are rewritten, never appended — see Guardrails. A page may be distilled from `wiki/` via Claude Code's `/distill` skill; the voice pass and publish decision are always human, never automated. Any prose you write for either layer follows the vault's root `voice.md` (writing-voice guide — verdict first, terse, no AI filler). Longer pages go through the `prose` skill before they are written.
- Link notes with `[[wikilinks]]` — the knowledge graph, not decoration.
- A write to `wiki/` or the curated surface counts as done when `node .scripts/vault-lint.mjs` passes (0 errors) and it is committed (see **Filing a note**). Passing is necessary, not sufficient — read your own diff before the commit.

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

**Questions over the vault — `agw brain`.** For "was habe ich zu X notiert", "wie ist mein Setup für Y", anything whose answer is spread over several notes, ask the vault instead of grepping it:

```bash
AGW_CALLER=hermes agw brain "<question>" --format json   # waits ~110 s; exit 10 → AGW_CALLER=hermes agw run wait <runId> --format json
```

It reads the vault read-only and returns `output.answer`, `output.read[]` (the notes it opened) and `output.citations[]` (`path` + `claim`). Present the answer in German with the cited note paths; if `output.status` is `partial` or `warnings` is non-empty, say so. A "no note on this" answer is an answer — don't re-ask with other words.

| Need | Use |
|-|-|
| An answer synthesized from several notes | `agw brain` (checked 2026-11-15 on two questions: cited, correct, one call; `obsidian search` returned file lists for a human to open) |
| Find a note by name or word, list a folder, follow backlinks/tags/properties | `obsidian search` / `backlinks` / `files` — metadata-aware, instant |
| A quick words-in-lines scan with snippets, CLI down | `AGW_CALLER=hermes agw vault search "<words>" --format plain` (any-word match, capped) or the filesystem |
| Read one known note | `obsidian read` (or `agw vault read <path>`) |

`agw brain` is for questions; it never writes. Captures and edits still go through the CLI below.

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

# Move / rename / delete (the vault is git-backed — all reversible)
obsidian move file="<name>" to="Areas/Engineering"
obsidian delete path="<path>"        # goes to trash; `permanent` only on an explicit ask
```

## Workflows

- **"note this / remember this / add to my notes", a memo, a logged measurement** → **file it where it belongs** (next section). `Inbox/` only when no home is clear.
- **"save this article / video"** → capture note in `Inbox/` with `url` + `author`/`channel` (promoted to `wiki/` or an Area later).
- **"inspiration / competitor / tool for project X"** → `Projects/X/notes/inspiration-<slug>.md`.
- **"what do I have on X" / "find my note about X"** → `search` / `search:context`, then `read` the hit.
- **"what links to / relates to Y"** → `backlinks` + `links`.

## Filing a note — find its home, then write it there

Johannes asked for the note in this turn (chat, CLI, Desktop or an Iris memo), so it goes **straight to its home** — brain `AGENTS.md` → Ingestion, case 2. One note per write. Cron jobs and other unattended runs are case 1: `Inbox/` only.

**1. Search first.** `obsidian search query="<the topic's words>"` (also `search:context`, `files folder="wiki/<domain>"`); open the domain's `index.md`. For a spread-out topic `agw brain "<question>"`. Decide from what exists — never from the title alone.

**2. Pick the home — first match wins.**

| The note is | Home | How |
|-|-|-|
| A measurement or event for an existing **log** (a dial-in shot → `wiki/coffee/dial-in-log.md`) | that log | Read the log; add a new entry in **its own format** at its own end (dial-in-log: newest on top, a `## YYYY-MM-DD — <summary>` section with the field table: bean, dose, grind, temperature, pre-infusion, time, yield, channelling, verdict, plus a short **Read:**). Fields not stated: `not stated`, never invented. Bump `timestamp`. |
| New facts or an idea for something that **already has a page** (a `wiki/` concept note, an Area or Project page) | that page | Update the relevant section. **Curated pages (`Areas/`, `Projects/`) are rewritten, never appended** — no dated lines, no `Nachtrag`. A dated fact with no section to live in becomes a `wiki/` note linked down from the page. Bump `timestamp` on a `wiki/` note. |
| A durable concept, procedure or reference with no page yet | new `wiki/<domain>/<kebab-name>.md` | Full frontmatter (`type`, `description`, `title`, `tags`, `timestamp`; `source: iris` for a memo), English prose, every `[[wikilink]]` resolves, and the level's `index.md` gains a line in the same write. |
| A journal-style reflection, or **no clear home** | `Inbox/` | Iris: `iris-note.py` (tags `[journal, iris]`). Elsewhere: `Inbox/<slug>.md`, generic frontmatter. Journal-style → tag `journal`. |

A memo that touches two homes is two writes, one commit each. Update before you create: a new `wiki/` note beside an existing one on the same concept is the failure.

**3. Write.** Prose follows `~/SourceRoot/brain/voice.md` (verdict first, numbers over adjectives). A page longer than a few paragraphs goes through `agw prose` (`skill_view('prose')`) before it is written. The CLI's `obsidian create`/`append`/`property:set`, or a filesystem edit, both fine.

**4. Gate.** From the vault: `cd ~/SourceRoot/brain && node .scripts/vault-lint.mjs` — 0 errors required (the 5 standing warnings are not yours). Fix what you introduced, then rerun.

**5. Commit.** `~/.hermes/scripts/brain-commit.sh "<type>: <what changed and why>" <path> [<path>…]` — only the paths you wrote (`wiki: dial-in 2026-11-15 shot, grind 9`). Exit 3 = lock busy, **not committed**: say so, retry once.

**6. Report the path written** (`wiki/coffee/dial-in-log.md`), and say where a judgement call placed it.

## Routing — where a capture goes

The `capture` skill routes; this is the shared model:

- **Obsidian** (this skill) — a durable thought, idea, or piece of knowledge to develop; a reference note you'll edit/link.
- **KaraKeep** (`karakeep` skill) — a link/article to read or keep later (let it crawl + AI-tag). Reference you consume, not author.
- **TickTick** (via `capture`) — something a human must do.
- **GitHub** (`capture`) — a concrete code change.

## Guardrails

- **Do not write journal entries** — except notes from an Iris voice-memo turn, which `skill_view('iris')` owns (script `skills/iris/scripts/iris-note.py` → `Inbox/`, tags `[journal, iris]`, for reflections and memos with no home; it commits through `brain-commit.sh`, so the Sync guardrail below is met). Everything else: the voice-first journal is a separate, paused subsystem with its own tone rules and ingest pipeline — currently blocked pending a new vault target (see `journal/PRD.md`). If asked to journal, say it isn't wired up yet rather than improvising an entry.
- **Never write to the vault root**; no clear home → `Inbox/`.
- **The `daily:*` and `template:*`/`templates` CLI verbs are dead.** Their backing core plugins (`daily-notes`, `templates`) are disabled and the `02_Daily/`/`09_Templates/` folders were removed 2026-08-02. Never call them. If asked to "add to my daily note", say daily notes were retired rather than improvising a location.
- **`wiki/` and `Inbox/`** — prefer `append`/`property:set` over rewriting a whole file (a log takes its new entry where the log puts it).
- **`Areas/` and `Projects/` (the curated surface) are rewritten, never appended.** Appending is how a curated page accumulates decision logs, stale status lines, and superseded options. Anything dated — a status update, a `Nachtrag`, a rejected option, a decision log — belongs in `wiki/` or nowhere. If the only way to add something is at the bottom, it's the wrong layer: write a `wiki/` note and link down to it from the curated page instead.
- `node .scripts/vault-lint.mjs --drift` (run from the vault, `~/SourceRoot/brain`) reports the mechanically detectable tells for the rule above — necessary, not sufficient; the voice pass stays human.
- **Sync is git, not automatic.** A LaunchAgent pulls and pushes `~/SourceRoot/brain` every 5 minutes; on this Mac Mini it never auto-commits. A write isn't durable until it's committed — after writing and a clean vault-lint, commit.
- **Always name the vault in the git command — `git -C ~/SourceRoot/brain …`.** Your shell's working directory is not the vault, so a bare `git commit` lands in the wrong repo or none. Easiest is the helper:
  ```bash
  ~/.hermes/scripts/brain-commit.sh "note: <what changed>"          # add -A, commit, push
  ~/.hermes/scripts/brain-commit.sh "note: <what changed>" Inbox/x.md   # only these paths
  ```
  **Use the helper, not a hand-composed `git -C … commit`.** It takes brain-sync's single-instance lock (`~/Library/Caches/brain-sync.lock`) so a commit never races the 5-minute sync for `.git/index.lock`, then pushes (fail-soft — a rejected push is logged and the sync pushes on its next tick). Exit 3 means the lock was busy and **nothing was committed** — say so and retry in a minute. The equivalent by hand, only if the helper is missing, still names the vault: `git -C ~/SourceRoot/brain add -A && git -C ~/SourceRoot/brain commit -m "…"`.
  Every other repo under `~/SourceRoot` is not yours to commit to — file a GitHub issue (`capture`); Claude Code there loads that repo's own rules and lint.
- **Reading on the Kobo e-reader** (selected vault notes → KOReader) is a separate, planned surface (Readeck, Phase 4) — not this skill yet.
