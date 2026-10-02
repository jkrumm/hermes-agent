---
name: verbatim-handoff
description: Use when a long text must be passed on verbatim.
version: 1.0.0
metadata:
  hermes:
    tags: [verbatim, transcript, as-is, unveraendert, fidelity, voice-memo, prompt, brief, handoff, state-db, herdr, dispatch]
    related_skills: [herdr, voice-memo-briefs, claude-dispatch, obsidian, podcast]
---

# Verbatim handoff — the text is data, not a draft

Trigger: "das ganze Transkript wie es ist", "unverändert", "1:1", "nimm das wörtlich",
"as-is", or any long block he attaches and points at a destination (an agent pane, a
dispatch brief, a vault note, a podcast source).

It arrives ragged on purpose — half-sentences, restarts, "genau" as punctuation, the ask
buried mid-paragraph. The raggedness is signal, not lint.

**The rule: reproduce nothing from your own context.** Retyping or re-summarising a long
text is where fidelity dies — an agent rewriting several thousand characters silently
paraphrases, drops clauses, renumbers and "fixes" what it finds odd, and he notices
because he knows what he said. Under *unverändert*, editing the punctuation, adding
paragraphs, or translating to English all break the ask.

## Procedure

**1. Find the exact bytes — never transcribe them.** The delivered turn is in the Hermes
session store, `~/.hermes/state.db` → table `messages` → column `content`. (`session_search`
recalls past turns; go to the store directly when the requirement is byte-exact.) A file he
pointed at is the other source — read it, do not retype it.

```python
# write_file this, then run: python3 /tmp/extract_message.py '<distinctive phrase>' /tmp/topic.txt
# (a `python3 - <<'PY'` heredoc loses its quoting in this harness — write the file instead)
import sqlite3, sys
c = sqlite3.connect("file:/Users/jkrumm/.hermes/state.db?mode=ro", uri=True)
raw = c.execute("select content from messages where content like ? order by id desc limit 1",
                (f"%{sys.argv[1]}%",)).fetchone()[0]
cut = raw.rindex("\n\n[")          # the routing line follows the payload
body = raw[1:cut]                  # drop the opening quote — a voice memo is wrapped in one pair
open(sys.argv[2], "w").write(body[:-1] if body.endswith('"') else body)
print(len(body), repr(body[:80]), repr(body[-80:]))
```

**2. Strip the wrapper, keep the text.** A memo arrives wrapped in one pair of `"`, and the
line after it is routing metadata — `[<name> | Slack user <@U…>] <his instruction>`. The
instruction is not part of the transcript; neither is the wrapper. Cut both or neither, and
be able to say which.

**3. Assert before delivering.** Character count, first 80 chars, last 80 chars, and the
provenance of every character you removed. Fidelity of a 16k transcription is not something
you eyeball, and a truncated tail is the failure nobody sees until later.

**4. Deliver through a file, never inline.** `write_file` the text to `/tmp/<topic>.txt`,
then hand over the path — `"$(cat …)"` into a prompt, stdin or `--brief-file` into a brief.
A long German block as a shell argument is mangled by quoting.

**5. Report that it went in unchanged, and where.** Destination ids — pane, tab, repo, file
path — plus one clause that you passed it as delivered and added nothing of your own. The
one thing he wants to know is whether the agent got *his* words.

Lanes: `herdr` (interactive pane), `claude-dispatch` (tracked episode), `obsidian` (vault),
`podcast` (audio source). Those skills own the delivery verbs; this one owns fidelity.

## Pitfalls

- **No framing of your own.** A preamble you invent ("here is the task, please …")
  pre-interprets the text for an agent that has the repo, the rules and the domain context
  you do not. Pass the text; where the lane wants a brief, the memo *is* the brief.
- **Do not answer the questions it raises.** Such a text usually names its open questions
  and hands the ball over. Let the destination answer, or wait for him to ask you.
- **A summary in your reply is not the handoff.** "I passed the gist to X" is the failure
  mode this skill exists to prevent.
- **Do not split it across turns or chunks** because it is long. One file, one handover.
- **Check the destination actually took it.** Read the pane or the job back and confirm the
  text landed whole — a prompt that was refused or truncated still exits 0.
