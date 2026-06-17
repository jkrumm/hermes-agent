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

## Response envelopes

- **List + search** (`/bookmarks`, `/bookmarks/search`, `/lists/{id}/bookmarks`, `/tags/{id}/bookmarks`) → `{ "bookmarks": [...], "nextCursor": "..." | null }`. Page with `cursor=<nextCursor>`.
- **Tags** (`/tags`) → `{ "tags": [{id, name, numBookmarks, numBookmarksByAttachedType}], "nextCursor" }`.
- **Lists** (`/lists`) → `{ "lists": [{id, name, icon, type, query?, parentId?}] }`.
- **Single bookmark** → bare object: `{id, createdAt, title, archived, favourited, taggingStatus, tags[], content{type,url|text,...}, ...}`.
- Pass `includeContent=false` on list/search calls for light responses (metadata only) — default is heavy.

## Endpoint reference

### Bookmarks
| Method | Path | Key params / body | Description |
|-|-|-|-|
| POST | `/bookmarks` | `{type:"link", url}` · `{type:"text", text, sourceUrl?}` · `+title?, note?, favourited?, archived?, tags?` | Create a bookmark (link or text) |
| GET | `/bookmarks` | `archived?`, `favourited?`, `sortOrder?` (default `desc`), `limit?`, `cursor?`, `includeContent?` | List bookmarks (newest first) |
| GET | `/bookmarks/search` | `q!`, `limit?`, `cursor?`, `sortOrder?`, `includeContent?` | Full-text search (Meilisearch) + query qualifiers |
| GET | `/bookmarks/check-url` | `url!` | Dedup — does this URL already exist? |
| GET | `/bookmarks/{id}` | — | Single bookmark with full content |
| PATCH | `/bookmarks/{id}` | `title?, note?, archived?, favourited?, summary?` | Update fields |
| DELETE | `/bookmarks/{id}` | — | Delete |
| POST | `/bookmarks/{id}/summarize` | — | Server-side AI summary (writes `summary`) |
| POST | `/bookmarks/{id}/tags` | `{tags:[{tagName}|{tagId}, attachedBy?]}` | Attach tags |
| DELETE | `/bookmarks/{id}/tags` | `{tags:[...]}` | Detach tags |
| GET | `/bookmarks/{id}/lists` | — | Lists this bookmark is in |
| GET | `/bookmarks/{id}/highlights` | — | Highlights on this bookmark |

### Lists
| Method | Path | Key params / body | Description |
|-|-|-|-|
| GET | `/lists` | — | All lists |
| POST | `/lists` | `name!`, `icon?`, `type?` (`manual`\|`smart`), `query?` (smart only), `parentId?` | Create a list. **Smart lists** auto-populate from a search `query` |
| GET | `/lists/{id}/bookmarks` | `limit?`, `cursor?` | Bookmarks in a list |
| PUT | `/lists/{id}/bookmarks/{bookmarkId}` | — | Add bookmark to a manual list |
| DELETE | `/lists/{id}/bookmarks/{bookmarkId}` | — | Remove bookmark from a list |
| PATCH | `/lists/{id}` | `name?, icon?, query?` | Update list |
| DELETE | `/lists/{id}` | — | Delete list |

### Tags / Highlights / Feeds / Assets
| Method | Path | Description |
|-|-|-|
| GET | `/tags` | All tags with counts (incl. ai vs human split) |
| POST | `/tags` | Create a tag (`{name}`) |
| GET | `/tags/{id}/bookmarks` | Bookmarks with a tag |
| GET / POST | `/highlights` | List all / create a highlight (`{bookmarkId, text, color?, startOffset, endOffset, note?}`) |
| GET / POST | `/feeds` · `POST /feeds/{id}/fetch` | RSS feed subscriptions + manual fetch |
| POST | `/assets` · `GET /assets/{id}` | Upload / fetch a binary asset |
| GET | `/users/me` · `/users/me/stats` | Account + counts (numBookmarks, numTags, byType, topDomains) |

## Core workflows

```bash
KK="Authorization: Bearer $KARAKEEP_API_KEY"
B="https://karakeep.jkrumm.com/api/v1"

# Keep a LINK (the default "save this / read later" action)
curl -s -X POST -H "$KK" -H "Content-Type: application/json" \
  -d '{"type":"link","url":"https://example.com/article"}' "$B/bookmarks" | jq '{id, "url": .content.url}'

# Keep a NOTE / snippet (raw text worth re-finding; sourceUrl optional)
curl -s -X POST -H "$KK" -H "Content-Type: application/json" \
  -d '{"type":"text","title":"Idea: deep modules","text":"Prefer few well-encapsulated modules…"}' "$B/bookmarks" | jq '{id}'

# Dedup before saving (optional)
curl -s -H "$KK" "$B/bookmarks/check-url?url=https://example.com/article" | jq

# Search (Meili full-text + qualifiers — see below)
curl -s -H "$KK" "$B/bookmarks/search?q=rust async&limit=10&includeContent=false" \
  | jq '.bookmarks[] | {id, title, "url": .content.url, tags: [.tags[].name]}'

# Recent saves (e.g. last 24h triage — newest first)
curl -s -H "$KK" "$B/bookmarks?limit=20&includeContent=false" \
  | jq '.bookmarks[] | {id, createdAt, title, "url": .content.url, tagged: .taggingStatus}'

# Attach a tag
curl -s -X POST -H "$KK" -H "Content-Type: application/json" \
  -d '{"tags":[{"tagName":"kobo"}]}' "$B/bookmarks/<id>/tags" | jq

# Create a SMART list that auto-collects everything tagged #kobo
curl -s -X POST -H "$KK" -H "Content-Type: application/json" \
  -d '{"name":"Reader","icon":"📖","type":"smart","query":"#kobo"}' "$B/lists" | jq '{id, name, type}'
```

### Search query qualifiers

The `q` parameter is plain free-text by default (Meilisearch). KaraKeep also understands inline qualifiers you can combine with free text:

- `#tagname` — has tag · `-#tagname` — excludes tag
- `is:fav`, `is:archived`, `is:tagged`, `is:link`, `is:text`
- `list:<name>` — in a named list
- `after:YYYY-MM-DD`, `before:YYYY-MM-DD`
- `url:<substr>`, `domain:<host>`

When unsure, fall back to plain free-text `q=` — it always works. **Note:** semantic / embedding search is *not* active on this instance (KaraKeep 0.32.0); search is full-text only.

## State cache (`state.json`)

Like `capture`, this skill keeps a small `state.json` (gitignored, seeded empty from `state.example.json`) caching **lists** and **tags** so the agent can resolve a name → id without re-listing every turn:

```json
{ "lists": [], "lists_last_refresh": null, "tags": [], "tags_last_refresh": null }
```

Refresh **on miss only** (a name you don't have): re-`GET /lists` or `/tags`, rewrite the cache. Never expire on a timer. If a write fails with a stale id, refresh and retry once.

## Routing — where does a capture go?

KaraKeep is one of four capture destinations. The mental model (`capture` skill owns the router):

| Destination | What lands there |
|-|-|
| **KaraKeep** (this skill) | A link/article/video to **read or keep** later; a text snippet worth re-finding. Reference, not action. |
| **Obsidian** (`obsidian` skill) | Durable **knowledge / an idea / a note** that belongs in the second brain. |
| **TickTick** (via `capture`) | Something a **human must do** (errand, decision, research-to-do, appointment). |
| **GitHub** (`capture`) | A concrete **code change** a coding agent can execute. |

Rule of thumb: *"I want to read/remember this"* → KaraKeep. *"I need to act on this"* → TickTick/GitHub. *"This is a thought I want to develop"* → Obsidian. A social/media link the user wants to read later → KaraKeep (let KaraKeep crawl + tag it); the `capture` social-media-extraction path is for items destined for TickTick/GitHub.

## Notes

- **AI tagging is automatic and async** (DeepSeek-V4-Flash via the IU endpoint). Don't manually tag what the crawler will tag — only add tags the user explicitly asks for or that the AI can't infer (e.g. `#kobo` for the reading queue).
- **Smart lists** are the right tool for auto-collections (a reading queue, "everything from a domain", "favourites tagged X"). Manual lists are for hand-curated sets.
- **iOS app**: KaraKeep has a native app, so the user reads on their phone there directly — Hermes doesn't proxy phone reading.
- **Kobo / KOReader**: saving *from* the Kobo and exporting KOReader highlights into KaraKeep works via the community `karakeep.koplugin`; on-device *browsing/reading* of the KaraKeep library is not yet supported by that plugin. The dedicated e-reader reading surface is handled separately (see the `obsidian` skill's reader-push capability / project docs) — don't promise Kobo reading through KaraKeep alone.
- This instance is fresh — lists start empty; create them on demand. Read-only by default beyond explicit "save/keep" intents; never delete a bookmark without confirmation.
