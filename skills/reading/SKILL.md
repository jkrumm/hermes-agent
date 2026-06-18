---
name: reading
description: Recommend what Johannes should read next — personal book recommender grounded in his actual taste. Use when he asks "what should I read", wants book recommendations, wants to find his next novel, wants fiction, fantasy, sci-fi, thriller, or travel/adventure picks, or wants to turn his reading history into picks. Pulls taste from the Argo Reading API (Hardcover shelf — ratings, genres, read / want-to-read) + a durable taste profile in Obsidian, researches real matching books on the web, ranks them, and captures picks back to Obsidian.
version: 1.1.0
metadata:
  hermes:
    tags: [reading, read, book, books, novel, fiction, fantasy, scifi, sci-fi, thriller, travel, surf, adventure, memoir, recommend, recommendation, what-to-read, next-read, hardcover, taste, library, shelf]
    related_skills: [obsidian, argo-api, karakeep, capture]
---

# Reading — personal book recommender

Answers **"what should I read next?"** grounded in what Johannes has actually
rated and what he's into right now. This is the **DISCOVER** end of his reading
life: taste in → real, matched books out.

Two signals, joined here:
- **Taste** — the Hardcover shelf (ratings, genres, statuses, finished dates),
  read through **Argo** (`GET /api/reading`). Hardcover is the "Letterboxd for books."
- **Profile** — durable, qualitative preferences ratings can't capture (genre
  likes/dislikes, reading language, density tolerance), kept in Obsidian at
  `05_Resources/Books/Reading Profile.md`.

**The recommendation brain is this skill, not Argo.** Argo is only the taste
read-model (`GET /api/reading`) — never ask it to recommend. Discovery,
similar-books, and ranking happen *here*, using web research. Argo aggregates
data; the skill does the thinking.

Use the terminal (`curl`, the `obsidian` CLI, web search). Don't say you lack
tooling — recommending and remembering books is this skill.

---

## Read this first — what Johannes actually wants

- **He reads to escape, and that spans more than fantasy.** Leisure reading =
  immersive **fantasy / adventure** fiction, **thrillers**, and **true-adventure
  narrative — travel, surf, survival** (e.g. *Bad Karma*, a surf-trip survival
  memoir). **Educational** nonfiction (AI / engineering / markets / science) is
  his self-education — do NOT recommend it for pleasure unless he asks;
  *narrative* / adventure nonfiction is fair game.
- **This is escape reading.** When he wants to "switch off from coding," his
  *tech interests are noise* — do not mine work/daily notes for themes and do
  not pick books because they're about AI/engineering/markets. Lean on the
  shelf + the Reading Profile, not the second brain's tech threads.
- **He reads in German for comfort** (his English is fine, but German is lower
  friction = more relaxing). Default to recommending books that exist in German
  and **always present the German edition** unless he says otherwise.
- **Taste shape** (see the Profile for the live version): immersive,
  character-driven fantasy/adventure with a great world; fast propulsive
  thrillers; travel / surf / survival adventure. *Not* romance-forward /
  "romantasy" / "for-women" (a hard dislike), *not* dense/slow literary prose.
  He's a software engineer (likes clean, rule-based magic systems) but **not a
  gamer** — don't pitch books as "for gamers". Accessible and propulsive wins;
  he is not a heavy reader, so page count and series-commitment matter.

---

## Flow (do these in order)

### Step 1 — Pull taste from Argo + read the Profile

```bash
# Hardcover shelf via Argo (Bearer already in env — do NOT run `op`)
curl -s -H "Authorization: Bearer $HOMELAB_API_KEY" \
  https://argo.jkrumm.com/api/reading | python3 -m json.tool
```

Response shape:
```jsonc
{
  "summary": { "total","wantToRead","currentlyReading","read","paused",
               "dnf","ratedCount","avgRating" },
  "shelf": [ {
      "hardcoverBookId",          // stable Hardcover id — use for dedup / linking
      "title","subtitle","slug",  // slug → hardcover.app/books/<slug>
      "authors":[],"genres":[],
      "pages","releaseYear","coverUrl",
      "communityRating","ratingsCount",
      "statusId",   // 1=Want to Read 2=Currently Reading 3=Read 4=Paused 5=DNF
      "status","rating","hasReview",
      "startedDate","readDate","lastReadDate","dateAdded",
      "stats": null // reading time/pace telemetry, populated only once matched
  } ]
}
```

> **Stale shelf?** The shelf is cached from Hardcover. If Johannes just rated or
> shelved something and it's missing, trigger a one-shot resync before reading:
> `curl -s -X POST -H "Authorization: Bearer $HOMELAB_API_KEY" https://argo.jkrumm.com/api/reading/sync`,
> then re-`GET /api/reading`. Don't do this on every run — only when freshness matters.

Extract:
- **Liked** — `status=Read` with high `rating` (4–5) → strongest signal.
- **Disliked** — low ratings (≤3) tell you what to *avoid*; read *why* against
  the Profile (e.g. a 3★ romantasy = "romance-forward isn't for me", not "more
  of this").
- **Genre lean** — tally `genres[]` across rated books.
- **Exclusion set** — every title on the shelf (any status). Never recommend a
  book already there.

Then read the durable profile (qualitative taste ratings miss):
```bash
obsidian read path="05_Resources/Books/Reading Profile.md"
obsidian read path="05_Resources/Books/Reading List.md"   # prior picks = memory
```
The **Reading List** is the skill's memory: skip anything already captured;
treat captured-then-read as accepted taste, untouched picks as a softer signal,
and anything marked "passed" as a learned dislike.

> **`stats` (reading telemetry)** — when present, it's a strong tell ratings
> hide: a fast finish on a 3★ book still says "couldn't put it down"; a stalled
> high-rated book is weaker than its rating. But **`status=Currently Reading`
> alone is a weak, ambiguous signal** — finishing something *fine* ≠ loving it.
> Don't infer strong taste from "currently reading"; ask if it matters.

### Step 2 — Calibrate (ask, don't assume)

The shelf is still small, so a question or two beats guessing. If the request
doesn't already pin these down, ask 1–3 of:
- **Mood** — chill/cozy escape, or dive-deep into a big world?
- **Language** — German (default) or English this time?
- **Length / density** — quick & light, or ready for a doorstopper?
- **Series appetite** — standalone (no commitment / no cliffhanger), or happy to
  start a series? (He dislikes being stuck waiting on *unfinished* series.)
- **Romance tolerance** — default: keep it low / not romance-forward.

Skip questions the request already answers. Don't interrogate — one good
clarifier is better than five.

### Step 3 — Discover (research-driven — the real work)

Generate candidates at the intersection of **shelf taste** + **Profile** +
**this session's calibration**. Use the web as a first-class discovery engine:

- **Adjacents to what he liked** — search "books similar to <liked title>", "if
  you liked <author>", "readers who enjoyed <title>". (This is the "similar
  books" Hardcover has no API for — so it lives here.)
- **By genre, well-filtered** — "best <subgenre> fantasy", curated "if you only
  read one" lists, award shortlists matched to the genre.

**Source palette — fiction-weighted (this reader skews SF/F + adventure +
thriller + travel/surf):**
- **Awards, by lane** — SF/F: Hugo, Nebula, Locus; thrillers: Edgar, CWA Dagger;
  travel/adventure: Banff & adventure-writing shortlists; plus the Goodreads
  Choice genre categories for crossover. Match the award to the genre.
- **Community quality filter** — Goodreads, StoryGraph, and the `communityRating`
  + `ratingsCount` already in `GET /api/reading`. Prefer well-rated titles with
  enough ratings; use this to deflate hype.
- **Genre communities** — r/Fantasy and r/printSF recommendation threads,
  curated "books like X" lists. Treat BookTok lists with skepticism (they skew
  hard to romantasy — his dislike).
- **German availability** — publisher catalogs are the ground truth for the
  German edition: **Heyne / Piper** (Sanderson, much SF/F), **dtv** (Maas,
  Sapkowski/Witcher, Baldree), **Knaur** (Bardugo), **FISCHER Tor**, **cbj**
  (YA / dragon-rider), **Klett-Cotta** (Hobbit Presse).

**Hard rule — verify the German edition before it reaches the list.** For every
pick, confirm the German title + publisher + that it's actually in print (web
search the publisher page / a retailer). Misquoting a German title or
recommending an untranslated book is worse than one fewer pick.

- **Cross-check the exclusion set** — drop anything already on the shelf.
- **Never invent.** Every title/author/year/German-title must be real and
  correctly attributed. Verify anything uncertain before listing it.

### Step 4 — Rank and present

A tight ranked list (5–8), grouped by lane (e.g. "closest to your taste",
"dive into a world", "pure chill"). For each:

> **German title** (English title) — Author · Verlag, ~NNN S. · *one line on why
> it fits*, tied to a **specific** rated book / a **named** profile preference.

Mix **safe bets** (close to demonstrated taste) with **1–2 stretch picks**.
Flag honest caveats (unfinished series, doorstopper length, tonal mismatch).
Keep reasoning concrete and personal — no generic blurbs. Give a clear steer,
not just a menu (he's not a heavy reader; choice overload loses him).

### Step 5 — Capture (offer, don't auto-run)

- **Remember the picks** — append to `05_Resources/Books/Reading List.md`
  (create it if missing) so the next run learns. One line each:
  `- [ ] German title (English) — Author · why · (suggested YYYY-MM-DD)`.
  Mark passed-over candidates `~~…~~ passed: <reason>` so the memory learns the
  dislikes too.
  ```bash
  obsidian append path="05_Resources/Books/Reading List.md" \
    content="\n- [ ] Weit über der smaragdgrünen See (Tress of the Emerald Sea) — Brandon Sanderson · standalone, light, no romance · (suggested $(date +%F))"
  ```
- **Update the Profile** when he reveals a durable new like/dislike (not a
  one-off mood) — append to `05_Resources/Books/Reading Profile.md`.
- **Mark Want to Read on Hardcover** — `POST /api/reading/want-to-read` is live.
  Offer to queue an accepted pick straight onto the Hardcover shelf so it shows up
  and feeds the next run. Body is `{title, author?}` — pass the **English** title +
  author (Hardcover matches its own catalog), even when you presented the German edition.
  ```bash
  curl -s -X POST -H "Authorization: Bearer $HOMELAB_API_KEY" -H "Content-Type: application/json" \
    -d '{"title":"Tress of the Emerald Sea","author":"Brandon Sanderson"}' \
    "https://argo.jkrumm.com/api/reading/want-to-read"
  ```
  Offer, don't auto-add — confirm the pick first, then queue it. The new entry may
  land unmatched briefly (`GET /api/reading/unmatched` lists pending matches; Argo's
  reconcile confirms them) — that's why a just-added book's `stats` start null.

---

## Constraints & notes

- **Auth** — `Authorization: Bearer $HOMELAB_API_KEY` (same `op://common/api/SECRET`
  value, already in `~/.hermes/.env`). Never run `op` at runtime; never print the
  bearer.
- **Argo is the read-model only.** All recommending happens here via web research
  — Hardcover has no recommendations API to proxy.
- **Acquisition is out of scope** — recommend and remember; Johannes acquires the
  book himself. Don't describe or name his acquisition pipeline.
- **The skill doesn't rewrite itself.** It improves through DATA: every Hardcover
  rating sharpens `GET /api/reading`; the Profile + Reading List are its memory.
  If the *method* should change, edit this SKILL.md deliberately.
- **Errors** — Argo `401` = stale/missing bearer (check `~/.hermes/.env`); `5xx`
  = Argo may be redeploying, retry shortly. Don't recommend blind without the
  taste pull.
