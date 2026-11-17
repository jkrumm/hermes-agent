# second-brain

<!-- MOVED-SECOND-BRAIN: moved verbatim from the root AGENTS.md (Second Brain and Wild Rift, 2527 bytes) -->

## Second Brain (Obsidian + KaraKeep)

Two skills, deliberately distinct roles — don't blur them:

- **`obsidian`** — the **source of truth**: read/search/write the PARA vault at
  `~/SourceRoot/brain/`, also a git repo shared with Claude Code (`/brain`). A LaunchAgent
  pulls+pushes every 5 min; **on this mini it never auto-commits, so a write isn't durable until
  committed**. **CLI-first** (`obsidian-cli` through the running app's API), filesystem fallback
  when Obsidian is down. No secret. Two layers: strict atomic English concept notes in `wiki/`,
  light curated `Projects`/`Areas` linking *down* into it. Contract: `~/SourceRoot/brain/AGENTS.md`.
- **`karakeep`** — the **read-later bucket**: REST on `https://karakeep.jkrumm.com/api/v1`
  (Bearer `$KARAKEEP_API_KEY`, Tailscale-only). Links/text, full-text search, lists, tags,
  highlights, async AI auto-tagging.

**Routing** (`capture` is the router): KaraKeep = reference/reading you consume · Obsidian =
durable knowledge you author · TickTick = human action · GitHub = code change.

**Bundled-skill collision:** upstream's stock `obsidian` skill was removed from
`~/.hermes/skills/note-taking/obsidian/` so ours is canonical, and it **re-seeds on `hermes
update`** — `/hermes-update` carries the `rm -rf` step. **Kobo/e-reader (not built):** reading
vault notes on the Kobo via KOReader would use Readeck (bidirectional highlight sync via
`iceyear/readeck.koplugin`), not KaraKeep (save-only) or Wallabag (no sync-back) — a homelab
container + a new `readeck` skill pushing curated content and pulling highlights back, nothing
scheduled.

## Wild Rift (champion pool tracker)

`skills/wildrift/SKILL.md` maintains the **eleven-champion pool** across jungle, support, mid and
baron. **Vault-first:** builds, runes, matchups, bans and a dated stats snapshot live at
`~/SourceRoot/brain/Areas/Gaming/Wild Rift/*.md` (curated surface, not `wiki/`); the open web
via `agw-research` only *refreshes* a note when a patch moved. No secret, no external API.
Writes use the `obsidian` CLI-first contract and `git -C ~/SourceRoot/brain …`
(never push — the LaunchAgent syncs).

**Web facts go through `agw-research`** — build sites are JS-heavy and contradict each
other; the gateway cross-verifies. **Stats are China-server only**
and swing hard by rank tier (0-4 — Hecarim ~45% WR at tier 0 vs ~53.7% at tier 4): qualify every
answer by rank. An Argo `/wildrift/*` group is **built but not deployed**; the skill tells the
agent not to call it.
