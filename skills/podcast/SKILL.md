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

The audio-gateway's podcast pipeline (`http://localhost:7719` — the mini's
second audio-gateway instance, dedicated to podcasts because it alone has the
brain vault on disk; STT/TTS stays on the VPS container) researches the source
(brain search, past episodes, the research gateway), has an editorial pass
decide format/roles/tone/humor/length for THIS episode, writes a scripted
two-host conversation, synthesizes it, masters it into one MP3 with chapters
and cover art, writes the transcript back into the brain, and — on request —
uploads the finished episode into Audiobookshelf so it shows up as a real
podcast episode in Plappa. This is a **job API, not TTS** — it is not the
`text_to_speech` tool and not `briefing-tts`'s single-shot `/v1/audio/speech`; it
runs a multi-stage pipeline (research → editorial → script → synthesis →
mastering → cover → publish → brain note) that takes minutes, so it is
submit-then-poll like `research-gateway`.

Use the terminal (`curl`). Don't say you lack tooling — turning source material into
a produced episode is this skill.

**Base URL:** `http://localhost:7719` (Hermes runs on the mini, same machine).
**Auth:** the gateway is loopback/tailnet-gated (no public listener) and
identifies the caller by a bearer label, not a credential — send both on every
request:
```
-H "Authorization: Bearer hermes" -H "x-audio-source: hermes"
```
No secret to resolve — `hermes` is a literal caller label, the same one
`config.yaml`'s `tts.openai.api_key` / `stt.openai.api_key` already use for the
native voice tools.

**New request fields** (all optional): `sourcePaths: string[]` — brain-relative
note paths the gateway reads itself, making `source` optional when given;
`research: boolean` (default `true`) — skip the research stage with `false`;
`pinMinutes: boolean` (default `false`) — stop the editor deviating from
`minutes`; `brainNote: boolean` (default `true`) — skip writing the transcript
note back into the brain with `false`.

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
- **Re-gathering what the gateway can read itself** — a brain note is passed by
  path in `sourcePaths` (the gateway searches and reads the vault on its own);
  only material that is NOT in the brain (a `karakeep`/`reading` article, a URL,
  Johannes's pasted text) goes through `source`.
- **A quick fact or a single question** — `research-gateway` answers those with a
  cited report; a podcast is for material worth 5+ minutes of narration.

---

## Flow

### 1. Name the source

The gateway has its own research loop (brain search + read, past episodes, the
research gateway), so don't gather what it can read itself:
- A brain note → its vault-relative path in `sourcePaths` (use `obsidian search`
  to find the path; do NOT paste the body).
- A saved article → `karakeep`/`reading`, written to a file → `source`.
- Johannes's pasted text → `source`.

For `source`, write the text to a file — long text through `jq --rawfile` avoids
every quoting problem a heredoc or an inline `-d` string would hit (source can
run up to 200k chars):

```bash
write_file /tmp/podcast-source.md   # only the non-brain material, may be empty
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
  --argjson paths '["Areas/Travel/Northern Spain 2026/Northern Spain 2026.md"]' \
  --arg brief "Johannes plant genau diese Reise mit dem Camper; sprich ihn direkt an, gib Rat." \
  --arg title "" \
  '{source: $source, sourcePaths: $paths, brief: $brief, title: $title, language: "de", minutes: 20,
    series: "Brain Sonderausgabe", publish: true, cover: true}
   | if .title == "" then del(.title) else . end')
# `sourcePaths` may be [] and `source` may be empty — but not both.

JOB=$(curl -s -X POST "http://localhost:7719/v1/podcasts" \
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
  R=$(curl -s "http://localhost:7719/v1/podcasts/$JOB" \
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
`scripting` is `research → editorial → outline → segment → review → revise →
metadata`.

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
  "cost_usd": 2.26,                               // the WHOLE pipeline — writers' room tokens + ElevenLabs
  "error": null,                                  // set only on status=failed (a generation failure)
  "publish": { "requested": true, "ok": true | false | null, "error": null },  // ok null = not attempted yet
  "abs": { "url": "...", "library_item_id": "...", "episode_id": "..." } | null,  // null on done = not (yet) in Audiobookshelf
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
curl -s "http://localhost:7719/v1/podcasts/$JOB/script?format=md" \
  -H "Authorization: Bearer hermes" -H "x-audio-source: hermes"
```

---

## Presenting the answer (Slack, German by default)

When `status: done`, report:
- **Title** and **duration** in minutes (`duration_seconds / 60`, rounded).
- **Chapter list** — `chapters[].title`, one per line.
- The **Audiobookshelf link** from `abs.url` — say the episode is in the Podcasts
  library, playable in Plappa.
- **Cost** (`cost_usd` — the whole pipeline: the writers' room tokens AND the ElevenLabs
  synthesis, counted by the gateway. Nothing comes "on top"; report it as the episode's price).

**`status: done` with `abs: null` and `publish.ok === false`** means produced but
NOT published — the upload failed, the episode is not in Audiobookshelf. Say exactly
that, quote `publish.error` verbatim, and offer `POST /v1/podcasts/{id}/publish`
(same auth headers), which repeats only the upload. Never invent a link, and never
offer `/retry` here — that is for `failed` jobs and would generate a new episode.

**Do not attach the MP3 via `MEDIA:`** for anything over ~5 minutes of audio —
Slack's upload size/time makes that a bad experience for a long-form file. Link to
Audiobookshelf instead; only attach directly for a short (<5 min) episode.

On `status: failed`, show the `error` field **verbatim** — don't paraphrase it away.
If the error reads like a transport hiccup (socket closed, timed out, 502/503 from
an upstream) retry ONCE without re-uploading anything:

```bash
curl -s -X POST "http://localhost:7719/v1/podcasts/$JOB/retry" \
  -H "Authorization: Bearer hermes" -H "x-audio-source: hermes" | jq .
# → { "id": "<new job id>", "status": "queued", "retry_of": "<old id>" } — poll the NEW id
```

The gateway keeps the source, so the retry is a new job with the identical request.
A second failure with the same error is not a hiccup — report it, don't loop.

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
- **Non-2xx on submit / gateway unreachable** → the mini instance may be down
  (`launchctl print gui/501/com.jkrumm.audio-gateway`); surface "audio-gateway
  nicht erreichbar" rather than falling back to `text_to_speech` (that tool
  cannot produce a two-host chaptered episode — it's a different product, not a
  fallback for this one).
- **Still running past the poll cap** → don't hang forever. Keep the job id, tell
  Johannes it's still working, and offer to check back or poll again shortly.
