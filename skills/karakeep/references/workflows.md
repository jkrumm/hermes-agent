# Core workflows

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
