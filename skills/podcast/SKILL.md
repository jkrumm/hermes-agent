---
name: podcast
description: Turn source notes (a brain note, a saved article, pasted text) into a long-form, two-host German podcast episode via `agw podcast` (agent-workflows), and publish it into Audiobookshelf. Use when Johannes asks for "mach mir einen Podcast", "Podcast über …", "als Podcast", "Hörbuch/Audio-Briefing zu …", "mach daraus was zum Anhören", or wants a plan/article/research turned into something to listen to (e.g. on a drive). Submit-and-wait (async); the run takes minutes (a writers' room of several models, then per-turn synthesis), and the finished episode is announced here in Slack with its Audiobookshelf link.
version: 2.0.0
metadata:
  hermes:
    tags: [podcast, podcasts, hörbuch, audio-briefing, two-host, audiobookshelf, abs, "zum-anhören", hörfassung, long-form-audio]
    related_skills: [obsidian, karakeep, reading, briefing-tts, argo-api]
---

# Podcast — long-form two-host episodes via `agw podcast`

`agw podcast` (the agent-workflows CLI, on `PATH` in the terminal tool) researches the
source (brain search, past episodes, a research pass), has an editorial pass decide
format/roles/tone/humor/length for THIS episode, writes a scripted two-host
conversation, synthesizes it, masters it into one MP3 with chapters and cover art,
writes the transcript back into the brain, and — on request — uploads the finished
episode into Audiobookshelf so it shows up as a real podcast episode in Plappa. This is
a **workflow run, not TTS** — it is not the `text_to_speech` tool and not
`briefing-tts`'s single-shot `/v1/audio/speech`; it runs a multi-stage pipeline
(research → editorial → script → synthesis → mastering → cover → publish → brain note)
that takes minutes, so it is submit-then-wait like `research-gateway`.

Use the terminal (`agw`). Don't say you lack tooling — turning source material into a
produced episode is this skill.

**No credential to resolve:** `agw` reads its own config. Always pass `--format json`
and read the JSON from stdout. Never put the source on argv — pipe it on stdin or name
vault paths.

---

## When to use this — and when NOT to

**Use this skill:**
- "Mach mir einen Podcast über …", "Podcast zu diesem Plan/Artikel/dieser Recherche"
- "Als Podcast", "Hörbuch/Audio-Briefing zu …", "mach daraus was zum Anhören"
- Turning a brain note, a saved KaraKeep article, a research-gateway report, or
  pasted text into a long-form (3–60 min) two-host conversation Johannes can
  listen to later (e.g. on a drive), not just have read aloud.

**Do NOT use this skill for:**
- **A short spoken reply, a voice memo, or a briefing narration** — that's the
  `text_to_speech` tool (single voice, one request, seconds not minutes). This
  pipeline is for a produced, two-host, chaptered *episode*, not a quick reply.
  **Never** curl `/v1/audio/speech` from here — that's `briefing-tts`'s endpoint.
- **Re-gathering what the run can read itself** — a brain note is passed by path in
  `--source-paths` (the run reads it, and searches the vault on its own); only
  material that is NOT in the brain (a `karakeep`/`reading` article, a URL,
  Johannes's pasted text) goes through the source text.
- **A quick fact or a single question** — `research-gateway` answers those with a
  cited report; a podcast is for material worth 3+ minutes of narration.

---

## Flow

### 1. Name the source

The run has its own research loop (brain search + read, past episodes), so don't gather
what it can read itself:
- A brain note → its vault-relative path in `--source-paths` (use `obsidian search`
  to find the path; do NOT paste the body).
- A saved article → `karakeep`/`reading`, written to a file → stdin.
- Johannes's pasted text → a file → stdin.

```bash
write_file /tmp/podcast-source.md   # only the non-brain material; may be empty or skipped
```

Compose a one-sentence `--brief` naming the listener and what he wants — this is what
lets the two hosts actually address Johannes rather than narrate generically:

> "Johannes plant genau diese Reise mit dem Camper; sprich ihn direkt an, gib Rat."

### 2. Submit

`--publish` unless Johannes says otherwise — the point is a finished episode in
Audiobookshelf, not a file sitting on the mini. `--minutes` is a target (3–60,
default 20) — pick it from how much source material there is and what Johannes asked for
("kurz" → 5–10, "ausführlich" → 30–45).

```bash
# AGW_CALLER=hermes books the run to Hermes in Argo (the CLI cannot tell Hermes from any other shell).
# source text on stdin, plus a brain note by path
AGW_CALLER=hermes agw podcast --format json --publish \
  --source-paths '["Areas/Travel/Northern Spain 2026/Northern Spain 2026.md"]' \
  --brief "Johannes plant genau diese Reise mit dem Camper; sprich ihn direkt an, gib Rat." \
  --language de --minutes 20 --series "Brain Sonderausgabe" \
  < /tmp/podcast-source.md

# brain note only: close stdin explicitly, or the command waits on it
AGW_CALLER=hermes agw podcast --format json --publish --source-paths '[…]' --brief "…" \
  --series "Brain Sonderausgabe" </dev/null
```

Other flags: `--title` (a hint; the final title is decided in the run), `--no-cover`,
`--no-research`, `--pin-minutes` (stop the editor deviating from `--minutes`),
`--no-brain-note` (skip the transcript note in the vault). At least one of stdin text or
`--source-paths` must carry content.

The command waits up to ~110 s, then **exits 10 and prints the run state — including
`runId`**. Exit 10 means "still running", never failure. **Capture the `runId` from that
JSON.** A finished run (very short episodes) exits 0 with the result directly.

**Reply immediately** with the run id and an honest estimate: **15–25 minutes** for the
default 20-minute episode (the script alone is a multi-model writers' room — plan,
write, review, revise; the model roster lives in agent-workflows' route table, never
restate it here — then synthesis, mastering, cover, publish); a 3–5 minute episode is
well under that. Don't make Johannes wait in silence.

### 3. Wait — one call at a time

The `terminal` tool is capped at **180 seconds per command**; `agw run wait` stays
under it (~110 s per call), so never wrap it in a loop for the whole run:

```bash
agw run wait <runId> --format json
```

- **Exit 10** → still running: call it again. It prints the state, with the run's
  `status`; never treat it as failure.
- **Exit 0** → `status: done`: present it (below).
- **Exit 1** → `status: failed` or `cancelled`: see *On failure*.

Call it **at most 5 times in a row** (≈ 9 minutes of your own run time). If the run is
still going, stop and tell Johannes: the episode will be announced in this channel with
the Audiobookshelf link when it is done (the run posts that notice itself — do not post
a second one), and he can ask you "wie steht's um den Podcast" any time — then answer
with ONE `agw run status <runId> --format json` (a one-shot, no waiting) and report.
Never sit in a wait loop for the whole run.

If you lost the id: it is in your own earlier tool output; there is no list command, so
say so rather than guessing or starting a second episode.

### 4. Present the result

The result is the run's JSON when `status` is `done` — `{runId, workflowId, status, cost, unpricedCalls, output}`; every field below lives under `output.`:

| Report | Field |
|-|-|
| Title | `output.title` |
| Duration | `output.produce.durationSeconds` (÷ 60, rounded to minutes) |
| Chapters, one per line | `output.produce.chapters[].title` |
| Audiobookshelf link | `output.produce.abs.url` |
| Cost | `output.cost.totalUsd` |
| Transcript note | `output.produce.brainNote.path` |
| Publish outcome | `output.produce.publish` — `{requested, ok, error}` |

**Transcript**, if Johannes wants to read along or check a fact before listening: read
the note at `output.produce.brainNote.path` (an absolute path into the vault,
`Areas/Podcasts/…`; the `obsidian` skill or a plain file read).

**Cost:** `output.cost.totalUsd` is the whole pipeline — writers' room tokens AND synthesis AND
cover. Nothing comes "on top"; report it as the episode's price. `output.cost.complete: false`
means a lower bound — say "mindestens". The top-level `cost` is a bare number: only the
parent run's own steps, NOT the episode price — never report it.

---

## Presenting the answer (Slack, German by default)

When `status: done`, report:
- **Title** and **duration** in minutes.
- **Chapter list**, one per line.
- The **Audiobookshelf link** from `output.produce.abs.url` — say the episode is in the
  Podcasts library, playable in Plappa.
- **Cost** (`output.cost.totalUsd`).

**`output.produce.publish.ok === false`** means produced but NOT published — the upload failed,
the episode is not in Audiobookshelf (`output.produce.abs` is null). Say exactly that, quote
`output.produce.publish.error` verbatim, and offer the re-publish, which repeats only the upload:

```bash
AGW_CALLER=hermes agw podcast-publish <runId> --commit --format json
```

(`<runId>` is the podcast run's id; it prints the new `abs`, `publish` and `brainNote`.
It waits like the others: exit 10 → `agw run wait <that runId>`.) Never invent a link,
and never re-run `agw podcast` for a publish failure — that generates a whole new
episode.

**Do not attach the MP3 via `MEDIA:`** for anything over ~5 minutes of audio —
Slack's upload size/time makes that a bad experience for a long-form file. Link to
Audiobookshelf instead.

The mp3 carries chapters and cover art, so once published it's a real episode, not
a bare audio file — worth saying so the first time Johannes sees one.

### On failure

On `status: failed`, show `error.message` **verbatim** (top-level `error`, next to `status`) —
don't paraphrase it away. If it reads like a transport hiccup (socket closed, timed out,
502/503 from an upstream) retry **ONCE** by running the **same `agw podcast` command
again** with the same source and flags (no `--idempotency-key`: it must be a new run) —
there is no retry endpoint. Tell Johannes it is a second attempt, and wait on the NEW
`runId`. A
second failure with the same error is not a hiccup — report it, don't loop.

---

## Errors & limits

- **Exit 2 / usage error on submit** (`"kind":"usage"`, also a 400/422 from the host) → a
  bad flag or value (`--language` not `de|en`, `--source-paths` not a JSON array), or an
  `invalid_input` source: empty, over 200k characters, or a vault path that doesn't
  resolve to a note. Read the message, fix the command, don't guess and retry blindly.
- **`not_found`** from `agw run wait/status` → wrong or expired run id. Re-check the id
  you captured at submit time.
- **`network` error on submit** → the run may have started; the error's hint names the
  `--idempotency-key` to repeat the same submit safely. Use exactly that key; without
  it you could start a second episode.
- **`agw` unreachable / service down** → surface "agw podcast nicht erreichbar" with
  the error text rather than falling back to `text_to_speech` (that tool cannot
  produce a two-host chaptered episode — it's a different product, not a fallback).
- **Still running past the wait cap** → don't hang forever. Keep the run id, tell
  Johannes it's still working, and offer to check back or run `agw run status` again
  shortly.
