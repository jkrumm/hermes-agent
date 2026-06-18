---
name: research-gateway
description: Deep, cited web research via the research-gateway — agentic Tavily + Context7 + page-fetch, cross-verified, returns a cited markdown report. Use when Johannes wants facts looked up and *verified now* — "research X", "recherchier mal", "compare A vs B", "what's the latest on Y", "is it true that Z", "best practices for…", or any library / version / API / migration question. Preferred over raw web search for anything substantive. Submit-and-poll (async); runs on EU/IU models, off Max.
version: 1.0.0
metadata:
  hermes:
    tags: [research, recherche, recherchieren, sources, source, cite, citation, citations, verify, fact-check, factcheck, compare, comparison, latest, "deep-research", "look-up", lookup, investigate, evidence, library, version, api, docs, "how-does"]
    related_skills: [capture, karakeep, obsidian, reading, argo-api]
---

# Research — cited, cross-verified answers

A standalone agentic research service (`research.jkrumm.com`, on the VPS,
**tailnet-only** — the Mac Mini reaches it). One research brain runs a multi-step
tool loop (Tavily web search + page fetch + Context7 library docs), **cross-verifies
claims**, and returns a **cited markdown report**. Runs on EU/IU models — off Max,
cost-aware.

Use the terminal (`curl`). Don't say you lack tooling — answering substantive
questions with verified sources is this skill.

**Base URL:** `https://research.jkrumm.com`
**Auth:** `Authorization: Bearer $RESEARCH_API_KEY` (in env — never run `op`, never print it)

---

## When to use this — and when NOT to

**Use this skill (the preferred default for anything substantive):**
- "Research X" / "recherchier mal …" / "find out about …" / "investigate …"
- "Compare A vs B", "what's the latest on Y", "is it true that Z", "best practices for …"
- **Any library / framework / API / version question** — "current stable Bun version",
  "did Elysia change its lifecycle hooks", "how does X work in v6". (The model's own
  knowledge is stale — verify here. This is exactly the `research-first` discipline.)
- Anything where Johannes will act on the answer and **sources matter**.

**Do NOT use this skill for:**
- **"Remind me to research X / look into Y later"** → that's a *task to track*, not a
  question to answer now → route via **`capture`** to TickTick (human exploration).
  This skill does the research *now* and reports back.
- **A single trivial fact** you'd google in five seconds (a timezone, today's FX rate,
  a one-word definition) → the built-in web search (Tavily) is lighter; no need to spin
  up the full agentic loop. When in doubt and the answer is load-bearing, use this skill.
- **Book / novel discovery** → the **`reading`** skill (taste-grounded recommendations
  with its own web research).
- **Saving an article to read later** → **`karakeep`**.

---

## Flow — submit, then poll (async)

The service is **asynchronous**: you submit a query and get a `jobId`, then poll until
it's done. Even a `quick` job can take **1–3 minutes** (deep ones longer) — the brain is
searching, fetching and cross-checking. **Be patient; don't bail after one poll.** If
it's clearly a slow one, tell Johannes you're researching and will report back.

```bash
RK="Authorization: Bearer $RESEARCH_API_KEY"
B="https://research.jkrumm.com"

# 1) Submit — depth ∈ quick | standard | deep (omit → standard)
JOB=$(curl -s -X POST -H "$RK" -H "Content-Type: application/json" \
  -d '{"query":"Did Bun change its test runner API in the latest version?","depth":"standard"}' \
  "$B/research/" | jq -r '.jobId')

# 2) Poll every ~12s until status=done (or failed). Cap the wait so a stuck job
#    surfaces instead of hanging — ~10 min here (50 × 12s).
for i in $(seq 1 50); do
  R=$(curl -s -H "$RK" "$B/research/$JOB")
  ST=$(echo "$R" | jq -r '.status')
  [ "$ST" = "done" ] && break
  [ "$ST" = "failed" ] || [ "$ST" = "error" ] && { echo "research failed"; break; }
  sleep 12
done

# 3) Read the cited report + sources
echo "$R" | jq -r '.result.report'
echo "$R" | jq -r '.result.sources[]'
```

**Depth choice:**
- `quick` — one focused, factual question (a version, a single "does X do Y").
- `standard` — the default; most questions, light comparisons.
- `deep` — broad / multi-faceted topics, real A-vs-B comparisons, "thorough", "dig in".
  Match Johannes's phrasing — "kurz" → quick, "gründlich / tief" → deep.

**Response shape (`GET /research/{jobId}`):**
```jsonc
{
  "status": "queued" | "running" | "done" | "failed",
  "result": {                              // present only when status=done
    "report":    "…markdown narrative, cited…",
    "citations": [ { "claim": "…", "url": "…" } ],  // each key claim → a source
    "sources":   [ "https://…", … ]                 // deduplicated source URLs
  }
}
```

---

## Presenting the answer (Slack, German by default)

- **Lead with the answer, in German** (SOUL rule — narrate substance in German even when
  the report is English; keep proper nouns / product names / APIs / versions as-is).
- **Keep it tight.** If the report is long, give the conclusion + the 2–3 load-bearing
  points, then offer detail ("willst du die Details?"). Don't paste the full raw report
  unless he asks.
- **Always cite.** End with a short `Quellen:` list (the `sources[]` URLs, or the most
  relevant `citations[]`). The whole point of this path over a guess is that it's sourced
  — never strip the citations.
- If the report itself flags uncertainty or conflicting sources, **say so** — don't
  flatten it into false confidence.

---

## Errors & limits

- **`429`** on submit → rate-limited (a job is already running, or the global cap hit).
  Wait ~30s and retry once; if it persists, tell Johannes it's busy.
- **`404`** on poll → bad or expired `jobId` (jobs aren't kept forever). Re-submit.
- **Non-2xx on submit** / `health` down → the service is unreachable. It's tailnet-only on
  the VPS; surface "research service unreachable" rather than falling back to a guess.
- **Still `running` past the cap** → don't hang. Tell Johannes it's taking long and offer
  to check back, or to keep the `jobId` and poll again shortly.
- **Never answer a substantive/library/version question from memory when this fails** —
  say you couldn't verify rather than guessing (`research-first`).
