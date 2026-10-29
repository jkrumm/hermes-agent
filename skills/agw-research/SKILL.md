---
name: agw-research
description: Deep, cited web research via `agw research` (agent-workflows) — agentic web search + page fetch + library docs, cross-verified, returns a cited markdown report. Use when Johannes wants facts looked up and *verified now* — "research X", "recherchier mal", "compare A vs B", "what's the latest on Y", "is it true that Z", "best practices for…", or any library / version / API / migration question. Preferred over raw web search for anything substantive. Submit-and-wait (async).
version: 2.0.0
metadata:
  hermes:
    tags: [research, recherche, recherchieren, sources, source, cite, citation, citations, verify, fact-check, factcheck, compare, comparison, latest, "deep-research", "look-up", lookup, investigate, evidence, library, version, api, docs, "how-does"]
    related_skills: [capture, karakeep, obsidian, reading, argo-api]
---

# Research — cited, cross-verified answers

`agw research` (the agent-workflows CLI, on `PATH` in the terminal tool) runs one research
workflow: a multi-step tool loop (web search + page fetch + library docs) that
**cross-verifies claims** and returns a **cited markdown report**. Models are the platform's
choice, never restated here.

Use the terminal (`agw`). Don't say you lack tooling — answering substantive
questions with verified sources is this skill.

**No credential to resolve:** `agw` reads its own config. Always pass `--format json`
and read the JSON from stdout. Always prefix `AGW_CALLER=hermes` (books the run to Hermes —
the CLI cannot tell Hermes from any other shell).

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

## Flow — submit, then wait

```bash
# The question goes in through a quoted heredoc — never interpolate Slack text into the command line.
Q=$(cat <<'QUESTION'
Did Bun change its test runner API in the latest version?
QUESTION
)
AGW_CALLER=hermes agw research "$Q" --depth standard --format json
```

Flags: `--depth quick|standard|deep` (default `standard`), `--context "<background>"`
(what Johannes already knows — treated as established, never re-searched, never cited;
max 20000 chars), `--follow-up <runId>` (continue a finished report: the query is then a
new question about it, researched on top of the old report).

**Depth choice:**
- `quick` — one focused, factual question (a version, a single "does X do Y").
- `standard` — the default; most questions, light comparisons.
- `deep` — broad / multi-faceted topics, real A-vs-B comparisons, "thorough", "dig in".
  Match Johannes's phrasing — "kurz" → quick, "gründlich / tief" → deep.

The command waits up to ~110 s, then **exits 10 and prints the run state, including
`runId`**. Exit 10 means "still running", never failure. A `quick` run usually finishes in
that first call (exit 0, the result on stdout); `standard`/`deep` often don't. The
`terminal` tool is capped at **180 s per command**, so the default wait already fits —
no larger timeout needed, and never wrap the wait in a loop. **Capture the `runId`**, then:

```bash
AGW_CALLER=hermes agw run wait <runId> --format json
```

- **Exit 10** → still running: call it again (never failure).
- **Exit 0** → `status: done`: present it (below).
- **Exit 1** → `status: failed` or `cancelled`: see *Errors*.

Call it **at most 5 times in a row** (≈ 9 minutes). If the run is still going, tell
Johannes it's taking long, keep the `runId`, and offer to check back with ONE
`agw run status <runId> --format json` (a one-shot, no waiting). Runs persist in the
platform's journal — there is no 30-minute expiry; if you lost the id, it is in your own
earlier tool output (there is no list command — say so rather than re-submitting).

**Response shape (verified against a real run):**
```jsonc
{
  "runId": "…", "workflowId": "research",
  "status": "pending" | "running" | "done" | "failed" | "cancelled",
  "error":  { "kind": "…", "message": "…" },   // present when failed
  "cost": 0.0053,                              // USD, bare number; null = nothing priced
  "unpricedCalls": 0,                          // > 0 → cost is a lower bound
  "output": {                                  // present only when status=done
    "status":    "ok" | "partial",             // partial = evidence was LOST this run (citations
                                               // dropped, or nothing retrieved) — prose is
                                               // unconfirmed unless a citation backs it
    "warnings":  [ "…" ],                      // human-readable notes on degraded evidence
    "report":    "…markdown narrative…",
    "citations": [ { "claim": "…", "url": "…", "confidence": "high" | "medium" | "low" } ],
    "sources":   [ "https://…", … ],           // deduplicated source URLs
    "unverified": [ { "topic": "…", "url": "…" | null, "reason": "…" } ],  // could NOT verify
    "grounding": { "citations", "grounded", "pagesRetrieved", "pagesFailed" },  // counted in code
    "tools":     { "web_search": 1, "web_fetch": 1, … }   // calls per tool
  }
}
```

`output.status`, `grounding` and `unverified` are computed in code from what the fetch tools
actually returned — the model cannot assert that its own output was verified. That is why they
exist, and why you must relay them. The report itself carries no inline links: the claim→URL
mapping is `citations[]`.

---

## Presenting the answer (Slack, German by default)

- **Lead with the answer, in German** (SOUL rule — narrate substance in German even when
  the report is English; keep proper nouns / product names / APIs / versions as-is).
- **Keep it tight.** If the report is long, give the conclusion + the 2–3 load-bearing
  points, then offer detail ("willst du die Details?"). Don't paste the full raw report
  unless he asks.
- **Always cite.** End with a short `Quellen:` list (`output.sources[]`, or the most
  relevant `output.citations[]`). The whole point of this path over a guess is that it's
  sourced — never strip the citations.
- **Say in Slack when the evidence is weak — every time.** `output.status: "partial"` means
  citations were dropped or nothing could be retrieved: open with that ("Teilweise belegt —
  …") and treat unbacked prose as unconfirmed. Name the low-confidence citations as such,
  and list `output.unverified[]` topics as "nicht belegt". A `partial` report presented as a
  confident answer is the one failure this path exists to prevent.
- If the report itself flags uncertainty or conflicting sources, **say so** — don't
  flatten it into false confidence.

---

## Errors & limits

- **Exit 2 / `"kind":"usage"`** → bad flag or value (query under 3 chars, `--depth` not one
  of the three, `--context` over 20000 chars). Read the message, fix the command.
- **`status: failed`** → show top-level `error.message` **verbatim**. If it reads like a
  transport hiccup (socket closed, timed out, 502/503) retry **ONCE** with the same command
  (no `--idempotency-key`: it must be a new run) and say it is a second attempt; the same
  error twice is not a hiccup — report it, don't loop.
- **`not_found`** from `agw run wait/status` → wrong run id. Re-check the id from submit time.
- **`network` error on submit** → the run may have started; the error's hint names the
  `--idempotency-key` to repeat the same submit safely. Use exactly that key, or you start a
  second run.
- **`agw` unreachable** → surface "agw research nicht erreichbar" with the error text rather
  than falling back to a guess.
- **Never answer a substantive/library/version question from memory when this fails** —
  say you couldn't verify rather than guessing (`research-first`).
