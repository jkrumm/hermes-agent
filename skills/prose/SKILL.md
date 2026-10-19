---
name: prose
description: Run a longer written artifact through agent-gateway's prose pass before it is delivered — vault pages, reports, articles, docs, briefings Johannes reads as text. Use after drafting anything longer than a short chat reply. Not for chat replies, not for TTS scripts.
version: 1.0.0
metadata:
  hermes:
    tags: [prose, writing, voice, rewrite, vault-page, report, article, docs, briefing, draft, polish]
    related_skills: [obsidian, briefing-tts, podcast]
---

# Prose — the writing pass for longer artifacts

You write on Haiku; the `prose` job rewrites on a stronger writer against `~/SourceRoot/brain/voice.md`, with a different lab reviewing and a lint gate that discards a rewrite that loses a code block, a URL or a fact. One script wraps it: `~/.hermes/scripts/prose.py`.

## When to use

- **Yes:** vault pages, reports, summaries, articles, docs, written briefings — anything Johannes reads as text and that is longer than a short chat reply.
- **No:** chat replies (Slack answers follow SOUL.md directly), TTS scripts (`briefing-tts`, `podcast` have their own voice rules — rewritten prose reads wrong aloud), status lines, one-liners.

## How

1. **Draft** the artifact first, following `voice.md` (verdict first, terse, no filler). Facts, numbers, names and links must all be in the draft — the pass adds nothing of its own.
2. **Run the pass.** Draft to a temp file (or pipe it), then:

   ```bash
   python3 ~/.hermes/scripts/prose.py /tmp/draft.md --medium vault --language de --timeout 540 --out /tmp/final.md
   ```

   Always `--out`, never a `> final.md` redirect: the script writes the file atomically and only on success, so a failed run leaves no empty or truncated file behind.

   | Flag | Use |
   |-|-|
   | `--medium` | `vault` (default), `article`, `docs`, `briefing`, `landing`, `ui`, `chat` — where it will be read |
   | `--language` | `en` or `de`; omit to auto-detect |
   | `--context <file>` | outline or TLDR of the surrounding document, for consistency only |
   | `--no-verdict-first` | the draft deliberately builds criteria → candidates → verdict |
   | `--out <file>` | write the text to this file (atomic) instead of stdout |
   | `--timeout <s>` | give up polling after this many seconds (script default 900) |

   It takes 20–90 s, sometimes longer. The terminal tool's per-command timeout is 180 s (`config.yaml` `terminal.timeout`; a caller can override it per call), so pass the terminal call `timeout: 600` and keep the script's `--timeout 540` below it — the script then fails with the job id instead of the tool killing it silently. stderr is one summary line (`prose: kept=rewrite cost=$0.04`).
3. **Read `--out`'s file** and use it as the artifact — write it to the vault page or paste it into the reply. Do not edit it afterwards.

## Reading the result

- `kept=rewrite` — the pass improved it; use it.
- `kept=original (<reason>)` — the gate judged the rewrite worse (lost a URL or code block, added content, more lint findings, writer starved). The out file then holds your original draft; **use it as-is and do not retry in a loop.** One run per artifact.
- Non-zero exit — the job failed, timed out, the gateway is down or the out file could not be written (the `prose:` line names the job id). No new out file is written. Deliver the original draft and say in one clause that the pass did not run. Do not retry more than once.

## Notes

- Fenced code and URLs are kept verbatim; the pass rewrites the words around them.
- Cost is about $0.04 per run; never run it on short text.
