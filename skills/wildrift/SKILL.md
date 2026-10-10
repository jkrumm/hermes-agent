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

## Data reality — core rules

Full detail, rank tiers, the missing-row rule and the research-gateway incident: `references/data-reality.md` — read it before quoting a number.

- **China-server only.** Riot publishes no Wild Rift API; never claim a "global" win rate.
- **Qualify every rate by rank tier** (notes quote Master+ by default). No low-elo data exists.
- **The snapshot is dated** — if it's older than the current patch, say so and offer a refresh.
- **Check the roster** before repeating a counter: League PC champions (Trundle, Sylas) leak into research and don't exist in Wild Rift. Not in the 141-champion roster → drop it.
- **Web only through the `research-gateway` skill.** Never curl a Tencent endpoint, a Riot page or a build site directly. If research contradicts something `Sourcing.md` states as tested, the note wins.

## Item and rune data — where to look it up

**Read `Sourcing.md`.** It carries the current source list, which one is
authoritative for what, and the gaps in each — that note is maintained, this
skill would go stale. Reach anything it names through `research-gateway`, never
a direct fetch.

## Writing to the vault

Rules, lint, pipe/table traps, icons, the four-places stats update and the commit helper (`~/.hermes/scripts/brain-commit.sh`): `references/vault-writing.md` — read it before any write. Follow the `obsidian` skill's access model (CLI first); pull before writing; lint must end at 0 errors; commit through the helper.

## When a refresh is too big for you

A patch that moves most of the pool (or changes the item system the way 7.2 did) wants Johannes's own Claude Code session in `brain`, where the `wildrift-refresh` skill carries the procedure. Say so and say what it needs ("7.3 landed, eleven notes are stale, this needs a session") — that's a useful answer, not a failure. Vault writes are direct via `obsidian` (SOUL.md); don't offer to dispatch one.

## Workflows

Detail for each in `references/workflows.md`. All vault-first, in this order:

- **"what should I ban?" / "was soll ich bannen"** — `Draft Guide.md` ban table; ask which champion he's planning to play if not obvious.
- **"what do I pick into X?" / "was picke ich gegen AP"** — `Draft Guide.md` decision chain per role; give the pick and a one-line reason.
- **"how do I play X into Y?" / "wie spiele ich X gegen Y"** — the matchup table row in the champion note; quote its *read*. `research-gateway` only if no row exists, and say so.
- **"refresh my `<champ>` build" / "baue mir den X build neu"** — read note, check the patch via `research-gateway`, rewrite only the build/rune section if it moved, lint, commit, reply with the delta.
- **"did the new patch change my builds?" / "hat das Update meine Builds beeinflusst"** — same across the pool; write only to notes that moved.

Argo `/wildrift/*` is built but not deployed; do not call it.

## Notes

- State the rank tier whenever you quote a win, pick or ban rate.
- Matchup tables and the situational buy table are **hand-written judgment**.
  Don't overwrite them from a stats query or a single web source.
- Gragas is flagged low-confidence on purpose. If Johannes asks about him, lead
  with that rather than reading the build back as if it were settled.
- This skill doesn't touch TickTick, KaraKeep or GitHub — a Wild Rift item
  that's really a task ("try the new Hecarim build tonight") routes through
  `capture`.
