# Search query qualifiers

The `q` parameter is plain free-text by default (Meilisearch). KaraKeep also understands inline qualifiers you can combine with free text:

- `#tagname` — has tag · `-#tagname` — excludes tag
- `is:fav`, `is:archived`, `is:tagged`, `is:link`, `is:text`
- `list:<name>` — in a named list
- `after:YYYY-MM-DD`, `before:YYYY-MM-DD`
- `url:<substr>`, `domain:<host>`

When unsure, fall back to plain free-text `q=` — it always works. **Note:** semantic / embedding search is *not* active on this instance (KaraKeep 0.32.0); search is full-text only.
