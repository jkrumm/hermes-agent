---
name: wildrift
description: Answer and maintain Johannes's Wild Rift (mobile MOBA) champion pool — Thresh, Pyke (support), Rammus, Hecarim (jungle) — from the curated build/rune/matchup notes in the Obsidian vault, refreshing them from the web via research-gateway when a patch moves. Use for "refresh my <champ> build", "baue mir den Rammus build neu", "did the patch change my builds", "hat das neue Update meine Builds beeinflusst", "what should I ban", "was soll ich bannen", "how do I play X into Y", "wie spiele ich X gegen Y", "welchen build für Thresh". Read the vault with the `obsidian` CLI.
version: 1.1.0
metadata:
  hermes:
    tags: [wildrift, wild rift, wr, moba, league, lol, build, builds, champion, ban, bans, counter, counters, matchup, patch, meta, thresh, pyke, rammus, hecarim, jungle, support, draft]
    related_skills: [obsidian, research-gateway]
---

# Wild Rift

Johannes's Wild Rift champion pool — four champions: **Thresh** (support),
**Pyke** (support), **Rammus** (jungle), **Hecarim** (jungle).

**The vault is the source of truth.** Builds, runes, matchup tables, ban notes
and a stats snapshot all live in `~/SourceRoot/brain`. Answer from the notes
first, every time. The web (via `research-gateway`) is for *refreshing* a note
when a patch has moved — not for answering a question you could have read.

Read the vault with the `obsidian` CLI. Don't say you lack tooling — checking
builds, bans and matchups is this skill's job.

## Where everything lives

| Note | Holds |
|-|-|
| `Areas/Gaming/Wild Rift.md` | Draft cheat sheet — pool table, ban rules, fallbacks |
| `wiki/gaming/wildrift/index.md` | MOC + how to read the numbers |
| `wiki/gaming/wildrift/thresh.md` | Thresh — build, runes, matchups, ban note |
| `wiki/gaming/wildrift/pyke.md` | Pyke — same shape |
| `wiki/gaming/wildrift/rammus.md` | Rammus — same shape |
| `wiki/gaming/wildrift/hecarim.md` | Hecarim — same shape |
| `wiki/gaming/wildrift/items.md` | Patch 7.2 item system + situational buy table |

All paths are relative to `~/SourceRoot/brain/`.

## Data reality — read this before quoting a number

- **China-server only.** Riot publishes **no** Wild Rift API — not for stats,
  not for matches, not for anything. CN Diamond+ aggregate data is the only
  objective source that exists, and every third-party site resells it. Never
  claim a "global" win rate; there isn't one.
- **Rank level changes everything.** Rank tiers are an ordinal `0..4`,
  ascending in skill. The same champion swings hard across it: **Hecarim is
  ~45% win rate at tier 0 and ~53.7% at tier 4.** Always qualify advice by rank
  tier. Default to tier 2 unless Johannes names one.
- **The precise CN tier names are not documented.** Don't put a name like
  "Diamond" or "Challenger" on a rank level — only the ordering is verified.
- **`strengthLevel` is Tencent's grade, lower is better**, and it blends win
  rate with play rate. Rammus at grade 4 on a 55% win rate is the proof — it's
  punishing his low pick rate, not his strength. Don't quote it as power.
- **The snapshot in the notes is dated.** Each champion note carries the date
  its stats were taken. If Johannes asks for current numbers and the snapshot
  is older than the current patch, say so and offer a refresh.

### Champion pool

| Champion | Hero ID | Role | Note |
|-|-|-|-|
| Thresh | `10130` | Support | Flat ~51% at every rank — the safe main |
| Pyke | `10124` | Support | Almost never banned (<3%); rewards mechanics |
| Rammus | `10064` | Jungle | Best win rate in the pool; counterpick, not blind pick |
| Hecarim | `10019` | Jungle | Hard skill check — 45% low rank, 54% high |

Position codes, if a number ever carries one: `1=mid, 2=baron, 3=dragon,
4=support, 5=jungle`.

## Reaching the open web

Only through the **`research-gateway`** skill. Hermes' tirith guard trusts
exactly three hosts for a curl-pipe pattern — `argo.jkrumm.com`,
`karakeep.jkrumm.com`, `research.jkrumm.com`. **Never curl a Tencent endpoint,
a Riot page, or a build site directly**; it gets blocked or stalls on an
approval gate. Route the question through `research-gateway` and let it fetch.

Good research queries for this domain: the current Wild Rift patch number and
date; what a named patch changed for a specific champion; the current core
build for a champion on a named patch. Ask for the patch version explicitly —
it's the thing that decides whether a note is stale.

## Writing to the vault

Follow the **`obsidian`** skill's access model exactly: **CLI first**
(`obsidian version` is the liveness gate), filesystem fallback only when
Obsidian.app is down. Load `skills/obsidian/SKILL.md` before writing.

**Pull before writing** — `git -C ~/SourceRoot/brain pull`. The MacBook writes
to this vault too.

**`wiki/` is strict-linted.** Every note under `wiki/gaming/wildrift/` needs
`type` + `description` frontmatter, every `[[wikilink]]` must resolve, and each
level needs its `index.md`. `Areas/Gaming/Wild Rift.md` is light-linted
(dead-link check only).

**No escaped pipes inside table cells.** `[[note\|Alias]]` in a markdown table
fails the linter's wikilink parser. Put aliased links outside the table, or use
a plain bold name in the cell.

**Stats live in two places — update both.** Each champion note carries its
numbers in frontmatter (`winRate`, `pickRate`, `banRate`, `statDate`) *and* in
its per-rank table; the summary row for that champion is in
`Areas/Gaming/Wild Rift.md`. If you refresh stats, update all three. (A
Dataview block would remove this dual-write, but it was deliberately not used —
it doesn't render outside Obsidian, which matters for the planned phone
read-access.)

**Validate — 0 errors required:**
```bash
node ~/SourceRoot/brain/.scripts/vault-lint.mjs
```

**Icons are remote, never local.** Item and rune icons are
`https://img.jkrumm.com/blog/wildrift/{items,runes,spells}/<slug>.webp` URLs
already embedded in the notes. The slug is the item name lowercased with all
non-letters stripped — `Dead Man's Plate` → `deadmansplate`. Render with a
transform prefix and **`f:png`** to keep transparency:
`https://img.jkrumm.com/rs:fit:40/f:png/blog/wildrift/items/thornmail.webp`.
**Never download an image into the vault.** If a build gains an item with no
mirrored icon, write the item name as plain text and say so in the reply — do
not invent a URL, it will 404 silently.

**Commit after writing, and name the vault.** The repo-write guard refuses a
bare `git commit`; the vault is the one exemption and only when named:
```bash
git -C ~/SourceRoot/brain add -A
git -C ~/SourceRoot/brain commit -m "wildrift: refresh Hecarim build (patch 7.2b)"
```
**Never `git push`** — a LaunchAgent syncs every 5 minutes.

## Workflows

### "what should I ban?" / "was soll ich bannen"

Read-only, answer from the vault. `Areas/Gaming/Wild Rift.md` has the draft
rules; the per-champion notes have the counter tables. The short version, which
you should still verify against the notes rather than reciting from here:
Morgana covers both supports, Olaf is the Rammus ban, Poppy is the Hecarim ban.

Ask which champion he's planning to play if it isn't obvious — the ban depends
on the pick.

### "how do I play X into Y?" / "wie spiele ich X gegen Y"

Vault-first. Read the matchup table in the relevant champion note. Each row
carries a *read* — the actual instruction, not just a verdict. Quote that.

Only reach for `research-gateway` if the note has no row for that matchup, and
say plainly that you're going outside the notes.

### "refresh my `<champ>` build" / "baue mir den X build neu"

1. Read the note: `obsidian read path="wiki/gaming/wildrift/<champ>.md"`. Note
   its `patch:` frontmatter field.
2. Establish the current patch via `research-gateway`. If it matches the note,
   say so and stop — don't churn the vault for nothing.
3. If the patch moved, research what changed for that champion and what the
   current core build is.
4. Rewrite only the build/rune section. Update the `patch:` and `timestamp:`
   frontmatter. Don't blow away matchup tables — those are hand-written
   judgment and rarely move with a balance patch.
5. Lint (0 errors), then commit naming the vault.
6. Reply with the delta: what changed and why. If nothing material changed, say
   that instead of manufacturing a diff.

### "did the new patch change my builds?" / "hat das Update meine Builds beeinflusst"

Same as above but across all four notes. Read each note's `patch:` field, ask
`research-gateway` for the current patch and its champion changes, and report
which of the four are actually affected. Only write to notes that genuinely
moved — a balance patch usually touches one or two champions, not all four.

## Future — live stats via Argo

**Not deployed. Do not call these.** An Argo endpoint group
(`GET /wildrift/champions`, `/bans`, `/diff`, `POST /wildrift/sync`) is built
but not shipped; it would replace the dated snapshot in the notes with a daily
CN feed and make "what changed since date X" a real diff instead of a research
call. Until it is live, everything above is vault-and-research only. When it
ships, note that its win/pick/ban rates are **percents** (`50.75`), not
decimals.

## Notes

- State the rank tier whenever you quote a win, pick or ban rate.
- Matchup tables and the situational buy table are **hand-written judgment**.
  Don't overwrite them from a stats query or a single web source.
- This skill doesn't touch TickTick, KaraKeep or GitHub — a Wild Rift item
  that's really a task ("try the new Hecarim build tonight") routes through
  `capture`.
