---
name: iris
description: Handle a turn from Iris, Johannes's voice-memo app. The message is a speech-to-text transcript; decide what it is (question, todo, GitHub issue, note, tab prompt, chat), act with the existing skills, and end the reply with exactly one iris block (JSON kind/headline/spoken). Load whenever the per-turn system message says the turn comes from Iris.
version: 1.0.0
metadata:
  hermes:
    tags: [iris, voice, memo, transcript, stt, voice-memo, decide, route, note, journal]
    related_skills: [capture, obsidian, herdr, agw-research, karakeep]
---

# Iris — a voice memo, decided and acted on

Iris (Johannes's voice-memo app, server on this mini) no longer classifies memos. **You decide** what the memo is and act with your existing skills. The turn's system message says "This turn comes from Iris" — only then does this skill apply. Slack, CLI, cron and every other turn are untouched: no `iris` block there, ever.

## The turn

- The message is a **transcript** of a spoken memo, German or English, with speech-to-text errors. Repair the obvious ones silently (a misheard repo or product name, a dropped word); never mention the repair.
- **Answer in the memo's language** — an English memo gets an English reply, headline, `spoken`, issue or task title and note body; a German one German. SOUL.md's German default does not apply on an Iris turn. Never translate the memo text.
- **Ask nothing.** He recorded a memo on a phone; nobody answers a question mid-turn. Pick the most likely reading, state the assumption in one clause in the reply, proceed.
- **A side effect only when the memo asks for one** (a todo, an issue, a note, a tab prompt) or the hint below says so. A question gets an answer, not an action.
- **Act on the memo as spoken.** A todo, issue, note or tab prompt is carried out even if the memo calls itself a test; only the memo's own words ("nur testen, nichts anlegen") cancel the side effect.
- A follow-up turn in the same session carries the same system message — same rules.

## Decide — first match wins

| The memo is | Do |
|-|-|
| A question, "wie/was/warum/…", a lookup | Answer. Web or library facts, "recherchier…" → `skill_view('agw-research')`. Personal data (calendar, tasks, health, infra) → `argo-api`. |
| A todo, reminder, errand, "erinner mich…", or "open an issue / Issue für <repo>" | `skill_view('capture')` — it owns TickTick vs GitHub, the repo, the list. Its "ask if unclear" does **not** apply here: fall back to its default and say which. The memo text goes into the item **verbatim** (STT repairs only). |
| "tell / prompt / sag Tab X …", "schreib in den Tab …" | `skill_view('herdr')` — find the tab, `hc send <target> "<text>"`. Text = what he wants said to the agent, in his words, not the addressing phrase. Obey the skill's rules (never `--force`, never a blocked agent, a draft in the input line is not yours). |
| A note, idea, observation, plan or reflection with **no question and no request** ("ich denke gerade…", "Idee: …", "notier dir…", a journal-style thought) | A brain note — below. |
| Greeting, small talk, "test", a remark that wants a reply and nothing else | Chat: answer from yourself in a line or two — no tool calls, no status report, no side effect. |
| A link/article to keep for later | `skill_view('karakeep')`. |
| Anything else, or two readings that both fit | The cheaper, reversible one; say the reading you took. |

Repo code work is **filed** (a GitHub issue via `capture`), never done — same as everywhere (SOUL.md).

## The owner-picked hint (legacy app builds)

An old Iris build still sends the mode. The system message then ends with one more line, `The owner picked: <Mode>.` It **overrides the table**:

- **Journal.** → write the memo as a brain note, whatever it says.
- **Tab.** → a herdr tab prompt. Ask nothing. If the memo names no tab (or none matches), send nothing and say which tabs are live (purpose, not address — `hc ls`).
- **Chat.** → answer only. No writes, no sends, no tickets, no issues, no notes. Read-only lookups are fine; if he asked for a change, say what you would have done and that Chat mode cannot.

No hint line = decide yourself.

## A brain note (Inbox)

Replaces Iris's former journal destination — same folder, title rule, frontmatter. **Use the script**; it does the lock, the commit and the push:

```bash
python3 ~/.hermes/skills/iris/scripts/iris-note.py <<'MEMO'
<the memo text, STT repaired, otherwise verbatim — German stays German>
MEMO
```

It prints `{"ref": "Inbox/2026-11-04-….md", "committed": true, "title": "…"}`.

- Exit **0** = written, committed (push fail-soft, brain-sync pushes later). Exit **3** = brain-sync's lock was busy: the note exists but is **not committed** — say so in the reply, `kind` `error`; retry at most once in the same turn (`~/.hermes/scripts/brain-commit.sh "journal: <title>" <ref>`).
- Never hand-write the file or `git commit` in the vault; never write Iris notes anywhere but `Inbox/`.
- The script's rules, for the record: file `Inbox/YYYY-MM-DD-<slug>.md` (local date; `-<first 8 of the session id>` appended on a name clash); title = first sentence, ≤ 60 chars clipped on a word boundary, trailing `.,;:` stripped, `Voice memo` if empty; slug = lower-case ASCII, `ä→ae ö→oe ü→ue ß→ss`, other accents folded, ≤ 50 chars, `memo` if empty; frontmatter `title` (JSON-quoted), `date`, `tags: [journal, iris]`, `source: iris`, `memo: <session id>` (a retry reuses the note); commit message `journal: <title>`; brain-sync's mkdir lock `~/Library/Caches/brain-sync.lock` taken by `brain-commit.sh`.
- This is the **one** place the obsidian skill's "no journal entries" guardrail is lifted — Iris notes only. Any other journal request stays refused.

## The reply

It is what he reads on a phone: **verdict first**, short — usually 1–4 lines. Markdown renders (lists, code, tables, Mermaid); use it only when it carries content. No greeting, no name, no "Done!" filler, no process narration. Name what happened and where (the issue link, the task's list, the note's path, the tab by purpose). SOUL.md's one-line-per-item contract still shapes status-type replies. Never put secrets, tokens or hostnames in it.

If the requested side effect failed, say that plainly with the cause in one clause — never report a substitute as the thing he asked for.

## The closing block — always, exactly one, last

End the reply with exactly one fenced block tagged `iris`, **nothing after the closing fence** (no sign-off, no second block, no trailing newline text):

````
```iris
{"kind": "answer", "headline": "Berlin ist 3 °C wärmer als München", "spoken": "Berlin ist heute drei Grad wärmer als München."}
```
````

- **One line of valid JSON**, double quotes, exactly the three string keys `kind`, `headline`, `spoken` — no others, no trailing commas, no comments. Escape quotes inside values.
- `kind` — 1–3 words, lower-case, how the app labels the result. Prefer this set: `answer`, `task`, `github issue`, `note`, `tab prompt`, `chat`, `research`, `error`. A new label only when none fits.
- `headline` — **≤ 60 characters**, what happened or the gist of the answer. Plain text, no markdown. It becomes the push alert.
- `spoken` — **one sentence** for TTS in the memo's language: no markdown, no URLs, no ids, numbers as you would say them.
- The block is **always** present on an Iris turn — also on failure (`error`), on a refusal, and when the reply is one line. If you fail to do the work at all, still emit the block.
- Don't mention the block in prose; don't wrap it in anything else.
