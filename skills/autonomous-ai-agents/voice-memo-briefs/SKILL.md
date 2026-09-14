---
name: voice-memo-briefs
description: Use when a voice memo must become a brief or prompt.
version: 1.0.0
metadata:
  hermes:
    tags: [voice-memo, sprachmemo, transcript, brief, prompt, stt, german, herdr, dispatch, intake, dictation]
    related_skills: [herdr, claude-dispatch, capture, obsidian, podcast]
---

# Voice memos — source material, never the prompt

Johannes dictates. A memo arrives as an unstructured speech-to-text dump:
half-sentences, restarts, "genau" as punctuation, no paragraphs, no list, and
the actual ask buried in the middle. When he says **"mit prompt aus Sprachmemo"**
(or "aus dem Voice Memo", "nimm das Memo als Prompt"), he means the memo is the
**source** — you write the prompt.

Forwarding the raw transcript is the failure mode. An agent given a wall of
unpunctuated German spends its budget deciding what was asked, and the parts he
cared about are the parts it guesses wrong.

## Procedure

1. **Read the whole memo before writing anything.** His memos carry the real
   constraints late — the deadline, the "geht nicht", the thing that is wrong —
   after several paragraphs of context. Skim-then-summarize loses them.
2. **Rewrite in German.** The memo was German; the work is German. Do not
   translate to English, even when the destination is code or an English-language
   repo. Keep proper nouns, product names and technical terms as-is.
3. **Structure it as a numbered task list** with a closing line naming the
   concrete question you want answered. Group by *what he wants done*, not by the
   order he said it. A memo that wanders through five concerns becomes five
   numbered items, each one sentence of fact plus the constraint attached to it.
4. **Preserve his open questions as open questions.** "Wir müssen schauen, wie X
   sich verhält" is a question, not an instruction to decide X. Do not resolve
   ambiguity for him in the brief.
5. **Route it** — see the destination table below — then report where it landed.

## Never invent scope

**Add nothing he did not say.** This is the rule that costs the most when broken:
a memo that says "look at the error codes" does not authorise a refactor, and an
episode given invented scope returns work he has to throw away. If you think the
memo implies a step, put it in your *reply* as a suggestion — not in the brief.

The same goes the other way: do not silently drop a concern because it looks
minor or already solved. If he raised it, it goes in.

## Destinations

| The memo asks for | Where it goes |
|-|-|
| An interactive agent in a visible pane ("neuer tab", "mit cf") | `herdr` — write the brief to a file, then `herdr agent prompt <pane> "$(cat file)"` |
| A tracked, unattended episode that reaches an outcome | `claude-dispatch` → `run <repo>` with the brief on stdin |
| A todo / reminder / issue | `capture` (TickTick or GitHub) — one line per item, his action, not his prose |
| A durable idea to develop | `obsidian` — his thinking, structured, in his vault |
| Something to listen to | `podcast` |

**Long briefs go through a file, never inline.** A multi-paragraph German brief
passed as a shell argument gets mangled by quoting. Write it with `write_file` to
`/tmp/hermes-prompt-<topic>.txt`, then `"$(cat …)"`. This also leaves the exact
brief on disk to re-read when he replies to it later.

## Reporting

Say which parts you **restructured** — he dictated it, so he knows what he said,
and the useful information is what you changed. One or two lines, in German, plus
where it landed (pane id, repo, ticket). If you reordered his concerns or split
one item into several, that is worth one clause.

## Pitfalls

- **Do not answer the memo's questions in the same turn** when you have just
  handed it to an agent. He wants the agent's finding, not your guess racing it.
- **Do not "clean up" his technical vocabulary.** If he says a system or field
  name, use his word — it is the term the repo uses.
- **A memo can contain more than one destination.** A single dictation often
  holds a task for an agent *and* a reminder for himself. Split it and route each
  part; do not force everything into one lane.
- **Do not treat the memo as a transcript to archive.** Nobody wants the raw text
  back. The value is the brief.
