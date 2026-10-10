# Data reality and reaching the open web

Loaded from `SKILL.md` — read before quoting a number or going to the web.

## Data reality — read this before quoting a number

- **China-server only.** Riot publishes **no** Wild Rift API — not for stats,
  not for matches, not for anything. CN Diamond+ aggregate data is the only
  objective source that exists, and every third-party site resells it. Never
  claim a "global" win rate; there isn't one.
- **Know which layer a claim comes from.** Win/pick/ban rates are **measured**;
  item stats and costs are **factual**; build order, situational buys and
  matchup reads are **editorial** — somebody's judgement. Say so if asked where
  a build comes from. `Sourcing.md` has the full table and the exceptions.
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

Only through the **`research-gateway`** skill. **Never curl a Tencent endpoint,
a Riot page, or a build site directly** — those hosts aren't cross-verified or
cited, and results from them have been wrong before (see below). Route the
question through `research-gateway` and let it fetch.

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
