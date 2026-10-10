---
name: karakeep
description: Save links and notes to KaraKeep (self-hosted read-it-later / bookmark "everything bucket") and query them — keep a URL or text, full-text search, manage lists (incl. smart lists) and tags, read AI summaries and highlights. Use curl with Bearer $KARAKEEP_API_KEY.
version: 1.0.0
metadata:
  hermes:
    tags: [karakeep, bookmark, bookmarks, read-later, readlater, save, link, links, article, reading, search, lists, tags, highlights, rss, hoarder]
    related_skills: [capture, obsidian, argo-api]
---

# KaraKeep

Personal read-it-later and bookmark "everything bucket" (self-hosted KaraKeep, formerly Hoarder). Save a link or a piece of text, then find it again by full-text search. KaraKeep crawls each link, archives a readable copy, and auto-tags it with AI — so the bucket stays searchable without manual filing.

**Base URL:** `https://karakeep.jkrumm.com/api/v1`
**Auth:** `Authorization: Bearer $KARAKEEP_API_KEY` (available in env)
**Network:** Tailscale-only — reachable from the Mac Mini (Hermes host); not exposed publicly.

Use `curl` via the terminal. Do not say you lack tooling — saving and searching bookmarks is this skill.

## When to use this skill

- **"keep this" / "save this" / "read later" / "bookmark"** + a URL → save a link bookmark.
- **"keep this note/snippet"** (raw text, a quote, a thought worth re-finding) → save a text bookmark.
- **"what did I save about X" / "find my bookmark on X" / "show my read-later"** → search.
- Organizing saves: lists (manual or smart), tags, favourites, archive.

This is the **reference / reading bucket**. It is *not* the task system. See **Routing** below — actionable items go to TickTick/GitHub via `capture`; durable knowledge goes to the vault via `obsidian`.

## Async behaviour (important)

`POST /bookmarks` returns immediately with the new bookmark `id`, but the crawl (title, readable content, screenshot) and **AI auto-tagging** (DeepSeek-V4-Flash via the IU endpoint) run in the background and land a few seconds later. So:

- After saving a link, the response `title`/`content`/`tags` may still be empty — that's normal. Confirm the save with the `id` and the URL; don't block waiting for the crawl.
- If the user needs tags/summary right now, re-`GET /bookmarks/{id}` after a short pause, or trigger `POST /bookmarks/{id}/summarize`.

## References (load on demand, paths relative to this skill)

- `references/endpoints.md` — response envelopes (list/search cursor paging, `includeContent=false`) and the full endpoint tables (bookmarks, lists, tags, highlights, feeds, assets, users)
- `references/workflows.md` — curl recipes: keep a link or note, dedup, search, recent saves, attach a tag, create a smart list
- `references/search-qualifiers.md` — `q=` inline qualifiers (`#tag`, `is:`, `list:`, `after:`/`before:`, `url:`/`domain:`) and the full-text-only note

## State cache (`state.json`)

Like `capture`, this skill keeps a small `state.json` (gitignored, seeded empty from `state.example.json`) caching **lists** and **tags** so the agent can resolve a name → id without re-listing every turn:

```json
{ "lists": [], "lists_last_refresh": null, "tags": [], "tags_last_refresh": null }
```

Refresh **on miss only** (a name you don't have): re-`GET /lists` or `/tags`, rewrite the cache. Never expire on a timer. If a write fails with a stale id, refresh and retry once.

## Routing

KaraKeep is the reference/reading bucket: *"I want to read/remember this"* → here; actionable → TickTick/GitHub via `capture`; durable knowledge/ideas → `obsidian`. The `capture` skill owns the router (AGENTS.md *Second Brain* has the table); a social/media link to read later still goes here — `capture`'s social-media-extraction path is only for items destined for TickTick/GitHub.

## Notes

- **AI tagging is automatic and async** (DeepSeek-V4-Flash via the IU endpoint). Don't manually tag what the crawler will tag — only add tags the user explicitly asks for or that the AI can't infer (e.g. `#kobo` for the reading queue).
- **Smart lists** are the right tool for auto-collections (a reading queue, "everything from a domain", "favourites tagged X"). Manual lists are for hand-curated sets.
- **iOS app**: KaraKeep has a native app, so the user reads on their phone there directly — Hermes doesn't proxy phone reading.
- **Kobo / KOReader**: saving *from* the Kobo and exporting KOReader highlights into KaraKeep works via the community `karakeep.koplugin`; on-device *browsing/reading* of the KaraKeep library is not yet supported by that plugin. A dedicated Kobo/Readeck reading surface is **not built** (the `obsidian` skill lists it as planned) — don't promise Kobo reading through KaraKeep alone.
- This instance is fresh — lists start empty; create them on demand. Read-only by default beyond explicit "save/keep" intents; never delete a bookmark without confirmation.
