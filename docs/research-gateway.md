# Research (research-gateway)

Moved verbatim out of `CLAUDE.md` (2026-09-04, size pass). `CLAUDE.md` § Research points here — nothing was rewritten, only relocated.

Deep cited research is served by the standalone **research-gateway** (`research.jkrumm.com`,
VPS, **Tailscale-only** — the Mac Mini reaches it; same grey-cloud DNS pattern as the
audio-gateway). Hermes consumes it through the **`research-gateway` skill** (`skills/research-gateway/SKILL.md`)
via the `terminal` tool: submit `POST /research/ {query, depth?}` → `{jobId}`, then poll
`GET /research/{jobId}` until `status: done` → `{result: {report, citations[], sources[]}}`.
Async submit+poll because deep research outlasts a single sync call — even `quick` depth runs
1–3 min. It is the **preferred path for substantive / factual / library-version questions** (the
`research-first` discipline), over Hermes's built-in Tavily web search, which stays for quick
single lookups. Runs on EU/IU models, off Max.

- **Auth:** `RESEARCH_API_KEY` = `op://vps/research-gateway/API_SECRET` (the gateway's own
  bearer, shared with the Claude Code `/research` skill). Wired in `.env.tpl` (resolved at
  startup by `secrets.command`). Base URL hardcoded in the skill (like argo / karakeep).
- **tirith + cron allowlists extended:** both `patches/tirith-hermes-guards.patch` and
  `patches/cronjob-tools-allowlist-argo-bearer.patch` now include `research.jkrumm.com` in their
  trusted-host sets, so `curl https://research.jkrumm.com/... | jq` doesn't trip the
  pipe-to-interpreter / exfil gates (see *Local Modifications*).
- **Routing guard (SOUL.md):** "research X now" → `research-gateway` skill; "remind me to
  research X later" → `capture` → TickTick; book / novel discovery → `reading`.
- **Name collision (why `research-gateway`, not `research`):** upstream ships a bundled skill
  *category* directory `~/.hermes/skills/research/` (containing `arxiv`, `blogwatcher`,
  `llm-wiki`, `polymarket`, `research-paper-writing`). A top-level `research` symlink would
  collide with that dir (and `make setup` would back the whole category up, only for `hermes
  update` to re-seed and reconflict). So our skill is named `research-gateway` and symlinks to
  `~/.hermes/skills/research-gateway` — no collision, no reconciliation step needed. Routing is
  by description/tags, so natural-language "recherchier mal" still triggers it.
