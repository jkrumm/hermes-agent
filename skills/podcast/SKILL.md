---
name: podcast
description: Turn source notes (a brain note, a saved article, pasted text) into a long-form, two-host German podcast episode via the audio-gateway's podcast pipeline, and publish it into Audiobookshelf. Use when Johannes asks for "mach mir einen Podcast", "Podcast über …", "als Podcast", "Hörbuch/Audio-Briefing zu …", "mach daraus was zum Anhören", or wants a plan/article/research turned into something to listen to (e.g. on a drive). Submit-and-poll (async); the job runs server-side for 15–25 minutes (a writers' room of several models, then per-turn synthesis), and the finished episode is announced here in Slack with its Audiobookshelf link.
version: 1.0.0
metadata:
  hermes:
    tags: [podcast, podcasts, hörbuch, audio-briefing, two-host, audiobookshelf, abs, "zum-anhören", hörfassung, long-form-audio]
    related_skills: [obsidian, karakeep, reading, briefing-tts, argo-api]
---

# Podcast — long-form two-host episodes via the audio-gateway

The audio-gateway's podcast pipeline (`audio-gateway.jkrumm.com`, VPS, reached over
the tailnet) turns a block of source text into a scripted two-host conversation,
synthesizes it, masters it into one MP3 with chapters and cover art, and — on
request — uploads the finished episode into Audiobookshelf so it shows up as a real
podcast episode in Plappa. This is a **job API, not TTS** — it is not the
`text_to_speech` tool and not `briefing-tts`'s single-shot `/v1/audio/speech`; it
runs a multi-stage pipeline (script → synthesis → mastering → cover → publish) that
takes minutes, so it is submit-then-poll like `research-gateway`.

Use the terminal (`curl`). Don't say you lack tooling — turning source material into
a produced episode is this skill.

**Base URL:** `https://audio-gateway.jkrumm.com`
**Auth:** the gateway is tailnet-gated (no public listener) and identifies the
caller by a bearer label, not a credential — send both on every request:
```
-H "Authorization: Bearer hermes" -H "x-audio-source: hermes"
```
No secret to resolve — `hermes` is a literal caller label, the same one
`config.yaml`'s `tts.openai.api_key` / `stt.openai.api_key` already use for the
native voice tools.

---

## When to use this — and when NOT to

**Use this skill:**
- "Mach mir einen Podcast über …", "Podcast zu diesem Plan/Artikel/dieser Recherche"
- "Als Podcast", "Hörbuch/Audio-Briefing zu …", "mach daraus was zum Anhören"
- Turning a brain note, a saved KaraKeep article, a research-gateway report, or
  pasted text into a long-form (5–60 min) two-host conversation Johannes can
  listen to later (e.g. on a drive), not just have read aloud.

**Do NOT use this skill for:**
- **A short spoken reply, a voice memo, or a briefing narration** — that's the
  `text_to_speech` tool (single voice, one request, seconds not minutes). This
  pipeline is for a produced, two-host, chaptered *episode*, not a quick reply.
  **Never** curl `/v1/audio/speech` from here — that's `briefing-tts`'s endpoint.
- **Fetching or saving the source material itself** — use `obsidian` for a vault
  note, `karakeep`/`reading` for a saved article, or just take Johannes's pasted
  text. This skill only takes the *already-gathered* text as `source`.
- **A quick fact or a single question** — `research-gateway` answers those with a
  cited report; a podcast is for material worth 5+ minutes of narration.

---

## Flow

### 1. Gather the source

Reuse existing skills rather than re-deriving the text:
- A brain note → `obsidian` (read the note's full body).
- A saved article → `karakeep`/`reading`.
- Otherwise, Johannes's own pasted text.

Write the source to a file — long text through `jq --rawfile` avoids every quoting
problem a heredoc or an inline `-d` string would hit (source can run up to 200k
chars):

```bash
write_file /tmp/podcast-source.md   # the full note/article/pasted text
```

Compose a one-sentence `brief` naming the listener and what he wants — this is what
lets the two hosts actually address Johannes rather than narrate generically:

> "Johannes plant genau diese Reise mit dem Camper; sprich ihn direkt an, gib Rat."

### 2. Submit

`publish: true` unless Johannes says otherwise — the point is a finished episode in
Audiobookshelf, not a file sitting on the gateway.

```bash
BODY=$(jq -n \
  --rawfile source /tmp/podcast-source.md \
  --arg brief "Johannes plant genau diese Reise mit dem Camper; sprich ihn direkt an, gib Rat." \
  --arg title "" \
  '{source: $source, brief: $brief, title: $title, language: "de", minutes: 20,
    series: "Brain Sonderausgabe", publish: true, cover: true}
   | if .title == "" then del(.title) else . end')

JOB=$(curl -s -X POST "https://audio-gateway.jkrumm.com/v1/podcasts" \
  -H "Authorization: Bearer hermes" -H "x-audio-source: hermes" \
  -H "Content-Type: application/json" -d "$BODY" | jq -r '.id')
```

`minutes` is a target (5–60, default 20) — pick it from how much source material
there is and what Johannes asked for ("kurz" → 5-10, "ausführlich" → 30-45).

**Reply immediately** with the job id and the honest estimate: **15–25 minutes**
(the script alone is a writers' room — Opus 5 plans, Opus 4.6 writes, Gemini and
GPT review, Opus 4.6 revises — then ~120 turns of synthesis, mastering, cover,
publish). Don't make Johannes wait in silence.

### 3. Poll — in short chunks

The `terminal` tool is capped at **180 seconds per command**, so never loop for
the whole job in one call. One chunk = up to 6 polls, 20 s apart (~2 minutes):

```bash
for i in $(seq 1 6); do
  R=$(curl -s "https://audio-gateway.jkrumm.com/v1/podcasts/$JOB" \
      -H "Authorization: Bearer hermes" -H "x-audio-source: hermes")
  ST=$(echo "$R" | jq -r '.status')
  echo "$(date +%H:%M:%S) $ST $(echo "$R" | jq -r '.progress | select(. != null) | "\(.stage) \(.done)/\(.total)"')"
  [ "$ST" = "done" ] || [ "$ST" = "failed" ] && break
  sleep 20
done
echo "$R" | jq '{status, error, title, duration_seconds, cost_usd, abs}'
```

Run **at most 4 chunks** (≈ 8–10 minutes of your own run time). If the job is
still running after that, stop polling and tell Johannes: the episode will be
announced in this channel with the Audiobookshelf link when it is done (the
gateway posts it), and he can ask you "wie steht's um den Podcast" any time —
then run ONE chunk against the job id and report. Never sit in a poll loop for
the whole 20 minutes.

`status` moves through `queued → scripting → synthesizing → mastering → cover →
publishing → done` (or `failed` at any stage). `progress.stage` inside
`scripting` is `outline → segment → review → revise → metadata`.

### 4. Present the result

```bash
echo "$R" | jq '{title, duration_seconds, chapters, cost_usd, abs}'
```

---

## Response shapes

**`POST /v1/podcasts`** → `202`:
```jsonc
{ "id": "<uuid>", "status": "queued" }
```

**`GET /v1/podcasts/{id}`**:
```jsonc
{
  "id": "...", "status": "queued" | "scripting" | "synthesizing" | "mastering"
              | "cover" | "publishing" | "done" | "failed",
  "progress": { "stage": "...", "done": 3, "total": 8 },
  "title": "...", "description": "...",
  "duration_seconds": 1260, "turns": 42,
  "chapters": [ { "title": "...", "start_ms": 0 }, ... ],
  "cost_usd": 2.26,                               // ElevenLabs characters only; writer tokens come on top
  "error": null,                                  // set only on status=failed
  "abs": { "url": "...", "library_item_id": "...", "episode_id": "..." } | null,
  "created_at": "...", "updated_at": "..."
}
```

Other calls: `GET /v1/podcasts/{id}/audio` → MP3 bytes, `/cover` → PNG, `/script`
→ JSON script (`?format=md` for a readable transcript), `GET /v1/podcasts` → latest
50, `POST /v1/podcasts/{id}/publish` → re-run the Audiobookshelf publish for an
already-finished job (e.g. it was submitted with `publish: false`). The show in
Audiobookshelf is "Brain Sonderausgabe" (library "Podcasts"); every episode carries
chapters and cover art.

Transcript, if Johannes wants to read along or check a fact before listening:
```bash
curl -s "https://audio-gateway.jkrumm.com/v1/podcasts/$JOB/script?format=md" \
  -H "Authorization: Bearer hermes" -H "x-audio-source: hermes"
```

---

## Presenting the answer (Slack, German by default)

When `status: done`, report:
- **Title** and **duration** in minutes (`duration_seconds / 60`, rounded).
- **Chapter list** — `chapters[].title`, one per line.
- The **Audiobookshelf link** from `abs.url` — say the episode is in the Podcasts
  library, playable in Plappa.
- **Cost** (`cost_usd`, the ElevenLabs share; the writers' room adds roughly 3–4 USD on top).

**Do not attach the MP3 via `MEDIA:`** for anything over ~5 minutes of audio —
Slack's upload size/time makes that a bad experience for a long-form file. Link to
Audiobookshelf instead; only attach directly for a short (<5 min) episode.

On `status: failed`, show the `error` field **verbatim** — don't paraphrase it away
— and don't retry blindly. A failed run burned real synthesis cost; resubmitting
without understanding why repeats that.

The mp3 carries chapters and cover art, so once published it's a real episode, not
a bare audio file — worth saying so the first time Johannes sees one.

---

## Errors & limits

- Errors are `{ "error": { "message": "...", "type": "..." } }` on `400`/`404`/`502`.
- **`400`** on submit → usually a bad `source`/`minutes`/`language` value — read
  `error.message`, don't guess and retry.
- **`404`** on poll → wrong or expired job id. Re-check the id you captured at
  submit time; there's no way to recover a lost one except `GET /v1/podcasts`
  (latest 50).
- **`502`** → the pipeline's upstream (script/synthesis/mastering) failed. Show the
  error, don't resubmit automatically — ask whether Johannes wants a retry.
- **Non-2xx on submit / gateway unreachable** → it's tailnet-only; surface
  "audio-gateway nicht erreichbar" rather than falling back to `text_to_speech`
  (that tool cannot produce a two-host chaptered episode — it's a different
  product, not a fallback for this one).
- **Still running past the poll cap** → don't hang forever. Keep the job id, tell
  Johannes it's still working, and offer to check back or poll again shortly.
