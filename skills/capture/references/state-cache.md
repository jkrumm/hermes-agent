# State Cache

**File:** `~/.hermes/skills/capture/state.json` (gitignored, seeded from `state.example.json` on first `make setup`)

```json
{
  "repos": [
    {"name": "homelab", "description": "...", "visibility": "PUBLIC"},
    ...
  ],
  "repos_last_refresh": "2026-04-30T12:00:00Z",
  "ticktick_projects": [
    {"id": "69a32ea26de7515d72e6c664", "name": "🏠Personal"},
    {"id": "69a32ea26df1515d72e6c668", "name": "💼Work"},
    {"id": "69a32ea26dc8115d72e6c66c", "name": "📦Shopping"}
  ],
  "ticktick_last_refresh": "2026-04-30T12:00:00Z"
}
```

**Refresh policy:** never expire. Refresh **on miss only** — if the user mentions a repo or TickTick project not in the cache, refresh that cache once and try again.

## Read cache

```bash
cat ~/.hermes/skills/capture/state.json | jq '.repos[].name'
cat ~/.hermes/skills/capture/state.json | jq '.ticktick_projects'
```

## Refresh repos cache (run on miss)

```bash
TMP=$(mktemp)
gh repo list jkrumm --limit 200 --json name,description,visibility,isArchived \
  | jq '[.[] | select(.isArchived==false) | {name, description, visibility}]' > "$TMP"
jq --slurpfile repos "$TMP" \
  '.repos = $repos[0] | .repos_last_refresh = (now | strftime("%Y-%m-%dT%H:%M:%SZ"))' \
  ~/.hermes/skills/capture/state.json > "$TMP.merged"
mv "$TMP.merged" ~/.hermes/skills/capture/state.json
rm -f "$TMP"
```

## Refresh TickTick projects cache (run on miss)

```bash
TMP=$(mktemp)
curl -s -H "Authorization: Bearer $HOMELAB_API_KEY" \
  "https://argo.jkrumm.com/api/ticktick/projects" \
  | jq '[.data[] | select(.closed != true) | {id, name}]' > "$TMP"
jq --slurpfile projects "$TMP" \
  '.ticktick_projects = $projects[0] | .ticktick_last_refresh = (now | strftime("%Y-%m-%dT%H:%M:%SZ"))' \
  ~/.hermes/skills/capture/state.json > "$TMP.merged"
mv "$TMP.merged" ~/.hermes/skills/capture/state.json
rm -f "$TMP"
```
