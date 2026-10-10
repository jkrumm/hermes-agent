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
  `Areas/Reading/Reading Profile.md`.

**The recommendation brain is this skill, not Argo.** Argo is only the taste
read-model (`GET /api/reading`) — never ask it to recommend. Discovery,
similar-books, and ranking happen *here*, using web research. Argo aggregates
data; the skill does the thinking.

Use the terminal (`curl`, the `obsidian` CLI, web search). Don't say you lack
tooling — recommending and remembering books is this skill.

---

## Taste in one breath

- **Escape reading** — immersive fantasy / adventure, thrillers, travel / surf / survival narrative. Educational nonfiction (AI / engineering / markets) only if he asks; his tech interests are noise.
- **German edition always** — recommend books that exist in German and present the German edition unless he says otherwise.
- **Hard dislikes** — romance-forward / "romantasy", dense slow literary prose. Not a gamer, not a heavy reader (page count and series-commitment matter).

Full taste profile, award palette, communities and German publisher catalogs: `references/taste-and-sources.md` — read it before step 3.

---

## Flow (do these in order)

### Step 1 — Pull taste from Argo + read the Profile

```bash
# Hardcover shelf via Argo (Bearer already in env — do NOT run `op`)
curl -s -H "Authorization: Bearer $HOMELAB_API_KEY" \
  https://argo.jkrumm.com/api/reading | python3 -m json.tool
```

Response shape (`summary`, `shelf[]` fields, `statusId` codes), the stale-shelf resync and the want-to-read
write: `references/argo-reading-api.md`. Resync only when freshness matters (Johannes just rated or
shelved something and it's missing), then re-`GET /api/reading`.

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
obsidian read path="Areas/Reading/Reading Profile.md"
obsidian read path="Areas/Reading/Reading List.md"   # prior picks = memory
```
The **Reading List** is the skill's memory: skip anything already captured;
treat captured-then-read as accepted taste, untouched picks as a softer signal,
and anything marked "passed" as a learned dislike.

> **`stats` (reading telemetry)** — when present, it's a strong tell ratings
> hide: a fast finish on a 3★ book still says "couldn't put it down"; a stalled
> high-rated book is weaker than its rating. But **`status=Currently Reading`
> alone is a weak, ambiguous signal** — finishing something *fine* ≠ loving it.
> Don't infer strong taste from "currently reading"; ask if it matters.

### Step 2 — Calibrate (act, don't ask)

The shelf is still small, so a clarifier can beat guessing — but ask **at most one question**, only
if the request leaves the answer genuinely open, and proceed on the defaults below if it doesn't
(act, don't ask — SOUL.md). Pick the one that changes the picks most:
- **Mood** — chill/cozy escape, or dive-deep into a big world?
- **Language** — German (default) or English this time?
- **Length / density** — quick & light, or ready for a doorstopper?
- **Series appetite** — standalone (no commitment / no cliffhanger), or happy to
  start a series? (He dislikes being stuck waiting on *unfinished* series.)
- **Romance tolerance** — default: keep it low / not romance-forward.

Skip anything the request already answers. Don't interrogate — one good clarifier is better than five.

### Step 3 — Discover (research-driven — the real work)

Generate candidates at the intersection of **shelf taste** + **Profile** +
**this session's calibration**. Use the **`research-gateway` skill** for substantive web
research (cited, cross-verified) as the discovery engine:

- **Adjacents to what he liked** — search "books similar to <liked title>", "if
  you liked <author>", "readers who enjoyed <title>". (This is the "similar
  books" Hardcover has no API for — so it lives here.)
- **By genre, well-filtered** — "best <subgenre> fantasy", curated "if you only
  read one" lists, award shortlists matched to the genre.

Source palette (awards by lane, community quality filters, genre communities, German publisher
catalogs): `references/taste-and-sources.md`.

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

- **Remember the picks** — append to `Areas/Reading/Reading List.md`
  (create it if missing) so the next run learns. One line each:
  `- [ ] German title (English) — Author · why · (suggested YYYY-MM-DD)`.
  Mark passed-over candidates `~~…~~ passed: <reason>` so the memory learns the
  dislikes too.
  ```bash
  obsidian append path="Areas/Reading/Reading List.md" \
    content="\n- [ ] Weit über der smaragdgrünen See (Tress of the Emerald Sea) — Brandon Sanderson · standalone, light, no romance · (suggested $(date +%F))"
  ```
- **Update the Profile** when he reveals a durable new like/dislike (not a
  one-off mood) — append to `Areas/Reading/Reading Profile.md`.
- **Mark Want to Read on Hardcover** — `POST /api/reading/want-to-read` is live. Offer, don't
  auto-add — confirm the pick first, then queue it. Body is `{title, author?}` with the **English**
  title + author, even when you presented the German edition. Body example, `unmatched` behavior:
  `references/argo-reading-api.md`.

---

## Constraints & notes

- **Auth** — `Authorization: Bearer $HOMELAB_API_KEY` (same `op://common/api/SECRET`
  value, already in the environment — resolved at gateway startup). Never run `op` at
  runtime; never print the bearer.
- **Acquisition is out of scope** — recommend and remember; Johannes acquires the
  book himself. Don't describe or name his acquisition pipeline.
- **The skill doesn't rewrite itself.** It improves through DATA: every Hardcover
  rating sharpens `GET /api/reading`; the Profile + Reading List are its memory.
  If the *method* should change, edit this SKILL.md deliberately.
- **Errors** — Argo `401` = stale/missing bearer (report it; don't try to fix it); `5xx`
  = Argo may be redeploying, retry shortly. Don't recommend blind without the
  taste pull.
