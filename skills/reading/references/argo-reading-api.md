# Argo Reading API

Bearer auth for every call: `Authorization: Bearer $HOMELAB_API_KEY` (already in env — do NOT run `op`).

## GET /api/reading — shelf (step 1)

```bash
# Hardcover shelf via Argo (Bearer already in env — do NOT run `op`)
curl -s -H "Authorization: Bearer $HOMELAB_API_KEY" \
  https://argo.jkrumm.com/api/reading | python3 -m json.tool
```

Response shape:
```jsonc
{
  "summary": { "total","wantToRead","currentlyReading","read","paused",
               "dnf","ratedCount","avgRating" },
  "shelf": [ {
      "hardcoverBookId",          // stable Hardcover id — use for dedup / linking
      "title","subtitle","slug",  // slug → hardcover.app/books/<slug>
      "authors":[],"genres":[],
      "pages","releaseYear","coverUrl",
      "communityRating","ratingsCount",
      "statusId",   // 1=Want to Read 2=Currently Reading 3=Read 4=Paused 5=DNF
      "status","rating","hasReview",
      "startedDate","readDate","lastReadDate","dateAdded",
      "stats": null // reading time/pace telemetry, populated only once matched
  } ]
}
```

> **Stale shelf?** The shelf is cached from Hardcover. If Johannes just rated or
> shelved something and it's missing, trigger a one-shot resync before reading:
> `curl -s -X POST -H "Authorization: Bearer $HOMELAB_API_KEY" https://argo.jkrumm.com/api/reading/sync`,
> then re-`GET /api/reading`. Don't do this on every run — only when freshness matters.

## POST /api/reading/want-to-read (step 5)

- **Mark Want to Read on Hardcover** — `POST /api/reading/want-to-read` is live.
  Offer to queue an accepted pick straight onto the Hardcover shelf so it shows up
  and feeds the next run. Body is `{title, author?}` — pass the **English** title +
  author (Hardcover matches its own catalog), even when you presented the German edition.
  ```bash
  curl -s -X POST -H "Authorization: Bearer $HOMELAB_API_KEY" -H "Content-Type: application/json" \
    -d '{"title":"Tress of the Emerald Sea","author":"Brandon Sanderson"}' \
    "https://argo.jkrumm.com/api/reading/want-to-read"
  ```
  Offer, don't auto-add — confirm the pick first, then queue it. The new entry may
  land unmatched briefly (`GET /api/reading/unmatched` lists pending matches; Argo's
  reconcile confirms them) — that's why a just-added book's `stats` start null.
