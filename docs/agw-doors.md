# agw-doors

<!-- MOVED-AGW-DOORS: moved verbatim from the root AGENTS.md (agw doors: research, web, WeatherOrb, hyperdx, podcast, transport, 5544 bytes) -->

## Research (`agw research`)

Deep cited research is the platform's `research` workflow, used through `skills/agw-research/SKILL.md`
via `terminal`: `AGW_CALLER=hermes agw research "<q>" [--depth quick|standard|deep] [--context …]
[--follow-up <runId>] --format json`. It waits ~110 s (under the terminal tool's 180 s cap), then exits
10 `pending` with the `runId`; `agw run wait <runId>` resumes. Result: `{runId, status, output:
{report, citations[], sources[], unverified[], status ok|partial, warnings[], grounding}, cost}`.
**Preferred path for substantive / factual / library-version questions** over built-in Tavily
search, which stays for quick lookups.

- **Auth:** none — `agw` reads its own config (`~/.config/agw/env`); `RESEARCH_API_KEY` left
  `.env.tpl` when Hermes moved to `agw` (Wave 10). No host or key in this repo.
- **Routing (SOUL.md):** "research X now" → `agw-research`; "remind me to research X later"
  → `capture` → TickTick; book/novel discovery → `reading`.
- **Named `agw-research`, not `research`** — upstream's bundled skill *category* dir
  `~/.hermes/skills/research/` would collide with a top-level `research` symlink. Routing is by
  description/tags, so "recherchier mal" still triggers it.

## Web reading and vault questions (`agw web`, `agw brain`)

`skills/agw-web/SKILL.md` is the reading half of agw: `agw web read <url> --ask "<q>" --format plain`
for any public URL (fetch chain with a headed Chrome for bot walls, PDFs as text, a cheap model
extracts the answer), `agw web youtube <url>` (transcript + metadata), `agw web docs <lib>` and
`agw web package <registry> <name>` (library docs, live registry version). **Preferred over the
built-in Tavily extract for every URL** — it names why a page is unreadable instead of failing
silently. `agw brain "<question>"` (in `skills/obsidian/SKILL.md`) answers questions over the vault
with cited note paths; `obsidian search` stays for finding a note, backlinks and tags.

- **Auth:** none — `agw` reads its own config; callers prefix `AGW_CALLER=hermes`. No key in this repo.
- **Routing (SOUL.md):** a URL/video to read now → `agw-web`; several sources cross-checked →
  `agw-research`; keep a link for later → `karakeep` (a memo with a link and a question wants both).
- **Left out on purpose:** `agw review`, `eval`, `check`, `factory-*` (no Hermes use), `agw image`
  (one mention in `image-delivery`).
- **Adding or changing a skill needs `make setup` and a gateway restart** (the skills index is
  cached); `make deploy` does both.

## WeatherOrb (MCP)

`config.yaml` `mcp_servers.weatherorb` launches weatherorb's `packages/mcp` (stdio, Bun): six
read-only tools (`mcp__weatherorb__weatherorb_{pointcast,probe,astro,surf,spots_search,spot}`)
over the public `/v1` data API only. Its own key (`key:xm99s48mmee8`, account "Hermes") sits in
`~/.config/weatherorb/mcp-key` (chmod 600, outside every repo, minted with weatherorb's account
CLI); this public file holds only `${HOME}` paths. Loaded per process: a new `hermes chat` sees it,
the gateway after a restart. Rotate: revoke the key, `create-key` a new one into the same file.

## Observability triage (hyperdx)

`skills/hyperdx/SKILL.md` gives Hermes an authenticated path into ClickStack instead of a browser
login wall. HyperDX/ClickStack is **VPS-only** (`hyperdx.jkrumm.com`, Tailscale-only). Reads go
through **`agw hdx query <tool> '<json>'`** (read-only, allow-listed ClickStack MCP tools; `agw hdx
tools` / `guide` list them) and **`agw otel "<investigation>"`** for an open triage (a workflow that
exits 10 like `agw research`); `agw` holds the HyperDX credential, so no key or MCP URL lives here.
Raw `clickstack_sql` is CLI-only behind `agw hdx write … --commit` (not proven read-only, never granted
to an agent), so the three live alerts are re-run by their own dashboard tile (`clickstack_get_alert` →
`clickstack_query_tile`) and the follow-ups use `clickstack_table`. Escalation is `capture` → `gh issue create`
in the owning repo (`vps` for a root cause inside Traefik/ClickStack config itself). No ClickHouse HTTP on the tailnet. `HYPERDX_AGENT_ACCESS_KEY` stays in
`.env.tpl` only for the alert-as-code export flow (`skills/hyperdx/references/`); its host is in both
allowlist patches (see `docs/patches.md`).

## Podcast generation (podcast)

`skills/podcast/SKILL.md` turns notes into a long-form two-host German episode via **`agw podcast`**
(the agent-workflows CLI, on the terminal tool's `PATH` — the gateway plist carries `~/.local/bin` and
`/opt/homebrew/bin`) and publishes the MP3 (chapters + cover) into Audiobookshelf. Submit-and-wait like
`agw-research`, **not** a single `/v1/audio/speech` call like `briefing-tts`: `agw podcast … --format json`
exits 10 with the `runId` after ~110 s, `agw run wait <runId>` is called again until exit 0, `agw
podcast-publish <runId> --commit` repeats only the upload. **No secret in this repo** — `agw` reads its own
config (`~/.config/agw/env`). SOUL.md's TTS rule 4 ("NEVER curl an audio
endpoint") exempts `agw podcast` — there is no native tool for this pipeline.

## agw transport

`project-narratives.py` and `prose.py` reach
the platform only through `scripts/agw_run.py` (shells out to `agw … --format json`, `AGW_CALLER=hermes`,
no credential, no base-URL env knob). A run that outlives the CLI's wait budget exits 10; `agw_run.run`
resumes it with `agw run wait <runId>` and prints a progress line to stderr per resume (the cron
idle-output watchdog's liveness signal).
