---
name: wildrift
description: Answer and maintain Johannes's Wild Rift (mobile MOBA) champion pool — eleven champions across jungle, support, mid and baron — from the curated build/rune/matchup notes in the Obsidian vault, refreshing them from the web via research-gateway when a patch moves. Use for "refresh my <champ> build", "baue mir den Rammus build neu", "did the patch change my builds", "hat das neue Update meine Builds beeinflusst", "what should I ban", "was soll ich bannen", "what do I pick against an AP comp", "was picke ich gegen AP", "how do I play X into Y", "wie spiele ich X gegen Y", "welchen build für Thresh". Read the vault with the `obsidian` CLI.
version: 2.0.0
metadata:
  hermes:
    tags: [wildrift, wild rift, wr, moba, league, lol, build, builds, champion, ban, bans, counter, counters, matchup, draft, patch, meta, jungle, support, mid, baron, thresh, pyke, rakan, galio, rammus, hecarim, nunu, shyvana, gragas, mundo, ahri, ap, comp]
    related_skills: [obsidian, research-gateway]
---

# Wild Rift

Johannes's Wild Rift champion pool — **eleven champions**, two of which he
actually wants to play and nine that answer a specific draft.

**The vault is the source of truth.** Builds, runes, matchup tables, ban notes,
a draft decision guide and a stats snapshot all live in `~/SourceRoot/brain`.
Answer from the notes first, every time. The web (via `research-gateway`) is for
*refreshing* a note when a patch has moved — not for answering a question you
could have read.

Read the vault with the `obsidian` CLI. Don't say you lack tooling — checking
builds, bans and matchups is this skill's job.

## Where everything lives

Everything lives in **`Areas/Gaming/Wild Rift/`** — the curated human surface,
not `wiki/`. These are pages Johannes reads directly.

| Note | Holds |
|-|-|
| `Wild Rift.md` | Folder note — the pool by role, the summary stats table, draft rules |
| `Draft Guide.md` | **Start here for any pick/ban question.** Decision chains per role, the AP-comp argument, the ban table, per-champion confidence tiers |
| `Rammus.md` `Nunu.md` `Shyvana.md` `Hecarim.md` `Gragas.md` | Junglers |
| `Thresh.md` `Rakan.md` `Pyke.md` `Galio.md` | Supports (Galio is also mid) |
| `Ahri.md` `Dr Mundo.md` | Mid · baron lane |
| `Items.md` | 7.2 item system — boot tiers, component-first buying, healing reduction |
| `Sourcing.md` | Where every claim comes from, which sources are current vs stale, the rank buckets, the traps |

Each champion note has a **Why these items** table giving the mechanism behind
every core buy. Prefer quoting that over the win rate — mechanism survives a
patch, a tier list doesn't.

The filename is `Dr Mundo.md` with no period; the title is `Dr. Mundo`.

All paths are relative to `~/SourceRoot/brain/`.

## Champion pool

CN Master+, snapshot 2026-08-05.

| Champion | Hero ID | Role | Note |
|-|-|-|-|
| Rammus | `10064` | Jungle | Best win rate in the pool (54.96%). Dead against AP |
| Nunu & Willump | `10008` | Jungle | **The AP answer.** 52.9% flat at every rank |
| Shyvana | `10049` | Jungle | Farms to two items then shreds tanks. Gets *worse* as rank rises |
| Hecarim | `10019` | Jungle | Rewards mastery — 48% Diamond+, 51% Rift Summit |
| Gragas | `10089` | Jungle | **Low confidence.** S-tier on build sites, 47% where data exists |
| Thresh | `10130` | Support | The safe main, flat ~51% at every rank |
| Rakan | `10052` | Support | Multi-target engage. 0.27% ban — always available |
| Pyke | `10124` | Support | Rewards mechanics; rarely banned |
| Galio | `10099` | Support / Mid | **The dedicated anti-mage.** Support is the stronger build |
| Ahri | `10038` | Mid | 52.6% on a 0.16% ban rate — the safest blind pick he has |
| Dr. Mundo | `10062` | **Baron** | Answer to a mage comp. **Not a jungler** — that build is D-tier |

Position codes, if a number ever carries one: `1=mid, 2=baron, 3=dragon,
4=support, 5=jungle`.

### The one question that comes up most

*"They have too much AP, what do I pick?"* — the answer is **Nunu** in the
jungle or **Galio** mid/support. It is **not Hecarim**, and if Johannes says
Hecarim, correct him: Rammus fails against AP because his W turns armor into
damage, so an AP draft kills his offence and defence together; Hecarim is an AD
champion with no resistances who merely isn't punished the same way. The full
argument is in `Draft Guide.md` — read it rather than reciting this paragraph.

## Data reality — read this before quoting a number

- **China-server only.** Riot publishes **no** Wild Rift API — not for stats,
  not for matches, not for anything. CN Diamond+ aggregate data is the only
  objective source that exists, and every third-party site resells it. Never
  claim a "global" win rate; there isn't one.
- **Know which layer a claim comes from.** `Sourcing.md` has the table; the
  short version:

  | Layer | Status |
  |-|-|
  | Win / pick / ban rates | **Measured** — the Tencent CN feed |
  | Item stats, costs, passives | **Factual** — Riot patch notes |
  | Build order, situational buys, matchups | **Editorial** — somebody's judgement |

  Say so if asked where a build comes from. The single exception is
  **wrchina.gg**, which reads item and rune sets off the CN top-player
  leaderboard — when a note quotes a per-build win rate, that is the source.
- **Rank tiers, from Tencent's own page:** `钻石以上` Diamond+, `大师以上`
  Master+, `王者` Sovereign, `峡谷之巅` Rift Summit. The notes quote **Master+**
  by default. A fifth bucket exists in the API and is discarded by Riot's own
  frontend — never quote it.
- **There is no low-elo data at all.** The floor is Diamond. If asked how a
  champion does below that, say plainly that nobody measures it.
- **Rank still changes the answer.** Hecarim runs ~48% at Diamond+ and ~51% at
  Rift Summit, with ban rate 8.4% → 35.7%. Shyvana runs the other way, 51.9%
  down to 49.9%. Qualify advice by tier.
- **A missing row is a publication threshold, not a zero.** Gragas jungle
  appears only at Rift Summit; Dr. Mundo jungle stops at Master+. Neither is
  unplayed — both are below the cut. Say "not enough games to publish", never
  "no games".
- **The top two tiers are noisy day to day.** Sovereign and Rift Summit moved
  1.8–2.6 points between two consecutive daily snapshots with no patch in
  between, while Diamond+ and Master+ barely twitched. Quote those tiers as a
  direction, not a number.
- **`strengthLevel` is Tencent's grade, lower is better**, and it blends win
  rate with play rate. Rammus at grade 4 on a 55% win rate is the proof — it's
  punishing his low pick rate, not his strength. Don't quote it as power.
- **The snapshot in the notes is dated.** Each champion note carries the date
  its stats were taken. If Johannes asks for current numbers and the snapshot
  is older than the current patch, say so and offer a refresh.

> [!warning] Check the roster before repeating a counter
> Research about "League" leaks **League PC** champions into Wild Rift answers,
> and they look plausible. **Trundle** and **Sylas** have both arrived this way
> and neither exists in Wild Rift. If a research result names a champion that is
> not in the 141-champion roster, drop it — do not write it into a note.

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

> [!danger] A research run's negative claim about a source is not evidence
> On 2026-08-06 a `depth=deep` run returned, at high confidence, that the
> Tencent `lrlib` CDN "serves a card/hero collection game, not Wild Rift" and
> that `mlol.qt.qq.com` is "geo-restricted to mainland China". **Both are
> false** — those endpoints are where the champion roster, the stats and every
> champion portrait come from. The run had reasoned from failed fetches.
>
> `Sourcing.md` records the working URLs. If a research result contradicts
> something `Sourcing.md` states as tested, the note wins.

## Item and rune data — where to look it up

For "what does item X actually do" or "what does it cost", in order:

1. **`Sourcing.md`** first — it names the current sources and their gaps.
2. **`items_7_2b.yml`** in `changchiyou/wildrift-gold-efficiency` on GitHub —
   patch-versioned item table with typed stats, gold cost, passive names and
   gold efficiency. Its per-item `image` URLs are **not** trustworthy.
3. **`wiki.leagueoflegends.com`**, `Module:WRItemData/data` — full mechanics
   prose. It has **not** done the 7.2 enchant→item migration, so every tier-3
   boot and ex-enchant is missing from it. Note the host: the
   `leagueoflegends.fandom.com` mirror has the same page name and is ten months
   stale.

Reach all three through `research-gateway`, not a direct fetch.

## Writing to the vault

Follow the **`obsidian`** skill's access model exactly: **CLI first**
(`obsidian version` is the liveness gate), filesystem fallback only when
Obsidian.app is down. Load `skills/obsidian/SKILL.md` before writing.

**Pull before writing** — `git -C ~/SourceRoot/brain pull`. The MacBook writes
to this vault too.

**These are curated pages, so lint is light** — dead links only, no forced
`type`/`description`. **One exception applies here:** every champion note
declares `type: champion`, and the lint enforces that any note declaring it
keeps `patch`, `statDate` and `heroId`. Those are the keys you read; dropping
one on a refresh is an error, not a warning. Preserve the whole frontmatter
block when rewriting a section.

**Two opposite pipe rules — both bite silently.** A `|` inside a table cell is a
column separator, so:

| Construct | In a table cell | Why |
|-|-|-|
| Aliased wikilink | **Don't use it.** `[[note\|Alias]]` | Even escaped, it fails the vault linter's wikilink parser. Use a plain bold name and link outside the table |
| Sized image | **Must escape:** `![\|28](url)` | Unescaped `![\|28]` splits the cell — the image vanishes and the table silently gains a phantom column |

Both failures are invisible in the diff and only show up when the note renders.
Check a table by rendering it, not by reading it.

**Stats live in four places — update all of them.** Each champion note carries
its numbers in frontmatter (`winRate`, `pickRate`, `banRate`, `statDate`) *and*
in its per-rank table; the summary row is in `Wild Rift.md`; the pool table is
in `Draft Guide.md`. Miss one and the pages disagree with each other. (A
Dataview block would remove this quadruple-write, but it was deliberately not
used — it doesn't render outside Obsidian, which matters for phone read-access.)

**Keep one snapshot date across the whole pool.** The comparison tables in
`Wild Rift.md` and `Draft Guide.md` are only honest if every row was pulled the
same day. If you refresh one champion's numbers, either refresh all of them or
leave the comparison tables alone and say the note is now ahead of them.

**Validate — 0 errors required:**
```bash
node ~/SourceRoot/brain/.scripts/vault-lint.mjs
```

**Icons are remote, never local.** Item, rune, spell and champion art live at
`https://img.jkrumm.com/blog/wildrift/{items,runes,spells,champions}/<slug>.webp`
(champion art is `.png`). The slug is the name lowercased with all non-letters
stripped — `Dead Man's Plate` → `deadmansplate`. Use the full name:
`tearofthegoddess`, not `tear`.

Request **one rendition per icon** and size in Obsidian, rather than minting a
CDN variant per display size:

```
![\|28](https://img.jkrumm.com/rs:fit:96/f:png/blog/wildrift/items/thornmail.webp)
```

`rs:fit:96` for icons, `rs:fit:144` for champion art. **`f:png` is required** —
the CDN defaults to JPEG, which turns icon transparency into a black box.
**Never download an image into the vault.** If a build gains an item with no
mirrored icon, write the item name as plain text and say so in the reply — do
not invent a URL, it will 404 silently. Adding a new icon to the CDN is a
Claude Code job, not yours.

**Commit after writing, and name the vault.** The repo-write guard refuses a
bare `git commit`; the vault is the one exemption and only when named:
```bash
git -C ~/SourceRoot/brain add -A
git -C ~/SourceRoot/brain commit -m "wildrift: refresh Hecarim build (patch 7.2b)"
```
**Never `git push`** — a LaunchAgent syncs every 5 minutes.

## You cannot dispatch a Claude Code episode at the vault

`brain` is on the **deny** list in `config/dispatch-repos.json`, alongside
`dotfiles-private` and `homelab-private`. `claude-dispatch` will refuse it at
every tier and that refusal is deliberate — do not offer to "add it".

Two reasons worth knowing, so you can explain rather than just refuse:

- The vault is the store you read your own answers back out of. An episode
  driven by a brief assembled from Slack text could rewrite it, and you would
  then quote the result as fact.
- `implement` ends in a **draft PR**, and the vault is direct-to-master with a
  five-minute sync LaunchAgent. The artifact would be the wrong shape even if
  the tier were allowed.

So a big patch migration — new champions, a rebuilt guide, new CDN icons — is
**Johannes's own Claude Code session working inside `brain`**, not something you
hand off. The repo carries a `wildrift-refresh` skill for exactly that. Your
lane is answering from the notes and doing bounded refreshes yourself.

## Workflows

### "what should I ban?" / "was soll ich bannen"

Read-only, answer from the vault. **`Draft Guide.md` has the ban table** — read
that first; it maps pick → ban with the reason. The per-champion notes carry the
same ban in their own ban note.

The short version, which you should still verify against the guide rather than
reciting from here: Morgana covers three of the four supports, Olaf covers both
Rammus and Nunu, Poppy is the Hecarim ban, Lee Sin the Shyvana/Gragas ban, Yasuo
the mid ban for both Ahri and Galio.

Ask which champion he's planning to play if it isn't obvious — the ban depends
on the pick.

### "what do I pick into X?" / "was picke ich gegen AP"

**`Draft Guide.md`** is built for this. It has a decision chain per role and a
"when they're banned" table. Read the chain, give the pick and the one-line
reason, and don't recite the whole guide.

### "how do I play X into Y?" / "wie spiele ich X gegen Y"

Vault-first. Read the matchup table in the relevant champion note. Each row
carries a *read* — the actual instruction, not just a verdict. Quote that.

Only reach for `research-gateway` if the note has no row for that matchup, and
say plainly that you're going outside the notes.

### "refresh my `<champ>` build" / "baue mir den X build neu"

1. Read the note: `obsidian read path="Areas/Gaming/Wild Rift/<Champ>.md"`. Note
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

Same as above but across the pool. Read each note's `patch:` field, ask
`research-gateway` for the current patch and its champion changes, and report
which champions are actually affected. Only write to notes that genuinely moved
— a balance patch usually touches one or two, not eleven.

**Eleven notes is past the size of a comfortable in-conversation refresh.** If
the patch moved most of the pool, or changed the item system the way 7.2 did,
say so and tell Johannes it wants a Claude Code session in `brain` rather than
grinding it out yourself. Doing two or three notes and reporting honestly beats
half-updating eleven.

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
- Gragas is flagged low-confidence on purpose. If Johannes asks about him, lead
  with that rather than reading the build back as if it were settled.
- This skill doesn't touch TickTick, KaraKeep or GitHub — a Wild Rift item
  that's really a task ("try the new Hecarim build tonight") routes through
  `capture`.
