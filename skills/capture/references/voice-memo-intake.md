# Voice memo intake — audio file in, text out

_Use when an audio file or voice memo must become text._

He sends a voice memo as an attachment (an `.m4a`, arriving as
`~/.hermes/cache/documents/doc_<hash>_<original name>`). Every downstream lane
wants the words, not the container, and transcription is the one step of that
chain no other skill documents. STT lives on the same VPS audio-gateway as TTS,
OpenAI-compatible in both directions: `https://audio-gateway.jkrumm.com/v1`.

## Procedure

1. **Copy the attachment to a plain ASCII path first.**

   ```bash
   cp "/Users/jkrumm/.hermes/cache/documents/doc_<hash>_Some Name – 9–13.m4a" /tmp/memo.m4a
   ```

2. **POST it as multipart, answer written to a file.**

   ```bash
   curl -s -m 280 -w "\nHTTP=%{http_code}\n" \
     -X POST https://audio-gateway.jkrumm.com/v1/audio/transcriptions \
     -F "file=@/tmp/memo.m4a" -F "model=gpt-4o-transcribe" -F "language=de" \
     -o /tmp/transcript.json
   ```

   `language=de` is the right steer for his memos — without it German technical
   terms come back as English homophones. A few minutes of speech costs seconds of
   wall clock, so pass `-m 280` and don't babysit the call.

3. **Parse the JSON, never the raw body** — the response is `{"text": "…"}`.

   ```bash
   python3 -c "import json;print(json.load(open('/tmp/transcript.json'))['text'])"
   ```

4. **Hand the text on; do not reprint it to him.** A memo is source material: an
   agent lane gets it verbatim (below), a capture/vault destination gets it
   structured per `voice-memo-briefs`. Nobody wants the wall of half-sentences back.

## Handing it to an agent lane — verbatim

**When the destination is a herdr pane or a dispatch, the transcript goes in as it
stands.** Write it to `/tmp/hermes-prompt-<topic>.txt` with `write_file`, then
prompt with `"$(cat /tmp/hermes-prompt-<topic>.txt)"`. No numbered list, no
summary, no cleanup, no "improvements". Your digest is lossy: the agent has the
repo, the rules and the domain context you don't, and it extracts the real task
from his phrasing better than you extract it from his paraphrase. The
numbered-task-list reshaping in `voice-memo-briefs` is for destinations that
consume a *brief* (a todo, a vault note, work you do yourself), not for agent lanes.

## Pitfalls

- **A multipart `-F "file=@…"` path carrying spaces, an en-dash or umlauts can make
  curl abort with a bare `HTTP=000`, an empty body and no error line** — which reads
  like a dead gateway while `/health` still answers 200. That is what step 1's copy
  to `/tmp/memo.m4a` is for: retry on the plain path before diagnosing anything
  upstream.
- **Do not answer the memo's open questions in the same turn** you hand it to an
  agent. But split off the other half: a memo that also asks you to look something
  up ("schau mal, wie das lief") has given you your own task — do that one while the
  agent works, and report it as yours.
- **Never invent scope when routing.** A memo that asks for a check does not
  authorise a fix; put anything beyond it in your reply as a suggestion, not in the
  agent's brief.
