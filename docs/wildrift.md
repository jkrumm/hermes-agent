# Wild Rift champion pool tracker

Moved verbatim out of `CLAUDE.md` (2026-09-04, size pass). `CLAUDE.md` § Wild Rift points here — nothing was rewritten, only relocated.

`skills/wildrift/SKILL.md` answers and maintains Johannes's four-champion Wild Rift pool —
Thresh, Pyke (support), Rammus, Hecarim (jungle). **Vault-first:** builds, runes, matchup
tables, ban notes and a dated stats snapshot all live at
`~/SourceRoot/brain/Areas/Gaming/Wild Rift/{Wild Rift,Thresh,Pyke,Rammus,Hecarim,Items,Sourcing}.md`
— the curated human surface, not `wiki/`. Reads answer from the notes; the open web
(via `research-gateway`) is only for *refreshing* a note when a patch has moved. No secret,
no external API. Vault writes follow the `obsidian` skill's CLI-first/filesystem-fallback
contract and the same `git -C ~/SourceRoot/brain …` commit exemption other second-brain
writes use (never push — the LaunchAgent syncs).

**Why never a build site directly:** tirith's trusted-pipeline hosts
(`_ALLOWED_PIPELINE_HOSTS`) and the cron scanner's `_trusted_api_suffixes` allowlist exactly
`argo.jkrumm.com`, `karakeep.jkrumm.com`, `research.jkrumm.com` — no Tencent/Riot/build-site
host is trusted, so every web fetch routes through `research-gateway`. **Stats are
China-server only** (Riot publishes no Wild Rift API at all) and swing hard by rank tier
(ordinal 0-4) — Hecarim runs ~45% win rate at tier 0 vs ~53.7% at tier 4 — so every answer
must be qualified by rank.

An Argo `/wildrift/*` endpoint group (daily CN ingest, `/champions`, `/bans`, `/diff`,
`/sync`) is **built but not deployed**; the skill documents it as a future upgrade and
explicitly tells the agent not to call it. Shipping it would replace the dated snapshot with
a live feed and make patch diffs real rather than a research call.
