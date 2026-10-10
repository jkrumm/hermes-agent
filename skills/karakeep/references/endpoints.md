# KaraKeep endpoints and response envelopes

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
