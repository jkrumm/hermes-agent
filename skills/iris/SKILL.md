---
name: iris
description: Handle a turn from Iris, Johannes's voice-memo app. The message is a speech-to-text transcript; decide what it is (question, todo, GitHub issue, note, tab prompt, chat), act with the existing skills, file agent work with the software factory when he asks for it, and end the reply with exactly one iris block (JSON kind/headline); a comparison, figures or a long keep-worthy result can ride along as an iris-show or iris-doc artifact fence. Load whenever the per-turn system message says the turn comes from Iris.
version: 1.0.0
metadata:
  hermes:
    tags: [iris, voice, memo, transcript, stt, voice-memo, decide, route, note, journal]
    related_skills: [fleet, capture, obsidian, herdr, agw-research, karakeep]
---

# Iris — a voice memo, decided and acted on

Iris (Johannes's voice-memo app, server on this mini) no longer classifies memos. **You decide** what the memo is and act with your existing skills. The turn's system message says "This turn comes from Iris" — only then does this skill apply. CLI, Desktop, cron and every other turn are untouched: no `iris` block there, ever.

## The turn

- The message is a **transcript** of a spoken memo, German or English, with speech-to-text errors. Repair the obvious ones silently (a misheard repo or product name, a dropped word); never mention the repair.
- **Answer in the memo's language** — an English memo gets an English reply, headline, issue or task title and note body; a German one German. SOUL.md's German default does not apply on an Iris turn. Never translate the memo text.
- **Ask nothing.** He recorded a memo on a phone; nobody answers a question mid-turn. Pick the most likely reading, state the assumption in one clause in the reply, proceed.
- **A side effect only when the memo asks for one** (a todo, an issue, a note, a tab prompt, an agent hand-off) or the hint below says so. A question gets an answer, not an action.
- **Act on the memo as spoken.** A todo, issue, note, tab prompt or agent hand-off is carried out even if the memo calls itself a test; only the memo's own words ("nur testen, nichts anlegen") cancel the side effect.
- A follow-up turn in the same session carries the same system message — same rules.

## Decide — first match wins

| The memo is | Do |
|-|-|
| A question, "wie/was/warum/…", a lookup | Answer. Web or library facts, "recherchier…" → `skill_view('agw-research')`. Personal data (calendar, tasks, health, infra) → `argo-api`. |
| "How is X going", "what needs me", "what ran overnight", "any alerts", "what's running" | `skill_view('fleet')` — read. |
| Agent work on a repo to **start**: "let an agent fix X in <repo>", "start an agent on …", "lass einen Agenten … in <repo> …" | `skill_view('fleet')` — file one Issue. Its filing rules apply; the iris `via` is `iris voice memo`. |
| A todo, reminder, errand, "erinner mich…", or "open an issue / Issue für <repo>" | `skill_view('capture')` — it owns TickTick vs GitHub, the repo, the list. Its "ask if unclear" does **not** apply here: fall back to its default and say which. The memo text goes into the item **verbatim** (STT repairs only). |
| "tell / prompt / sag Tab X …", "schreib in den Tab …" (an **existing** terminal only) | `skill_view('herdr')` — find the tab, `hc send <target> "<text>"`. Text = what he wants said to the agent, in his words, not the addressing phrase. Obey the skill's rules (never `--force`, never a blocked agent, a draft in the input line is not yours). |
| A note, idea, observation, plan or reflection with **no question and no request** ("ich denke gerade…", "Idee: …", "notier dir…", a journal-style thought) | A brain note — below. |
| Greeting, small talk, "test", a remark that wants a reply and nothing else | Chat: answer from yourself in a line or two — no tool calls, no status report, no side effect. |
| A link/article to keep for later | `skill_view('karakeep')`. |
| Anything else, or two readings that both fit | The cheaper, reversible one; say the reading you took. |

Repo code work is **filed** (a GitHub issue via `capture`) when the memo says *file*, *note* or *open an issue*, and **handed to the factory** (`fleet`) only when it says *start* or *let an agent*. You never do repo work yourself — same as everywhere (SOUL.md). "Fix X in <repo>" with neither wording: file it and say so.

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

**Language check before you write it:** reply and `headline` are in the memo's language — English memo, English everything — even after loading `capture`, `obsidian` or `herdr` or seeing German in a tool result.

It is what he reads on a phone: **verdict first**, short — usually 1–4 lines. Markdown renders (lists, code, tables, Mermaid); use it only when it carries content. No greeting, no name, no "Done!" filler, no process narration. Name what happened and where (the issue link, the task's list, the note's path, the tab by purpose). SOUL.md's one-line-per-item contract still shapes status-type replies. Never put secrets, tokens or hostnames in it.

If the requested side effect failed, say that plainly with the cause in one clause — never report a substitute as the thing he asked for.

## Artifacts — a table, chart or document beside the prose

Iris turns two more fences of the reply into rich views on the phone and the Mac: ` ```iris-show ` (one JSON spec) and ` ```iris-doc ` (a standalone document). The fence stays in the reply text as its anchor; an **invalid** one silently stays a plain code block, so follow the syntax exactly.

**The reply is also read aloud, and an artifact fence is not.** The prose must stand without it: state the verdict (and the one number or name that matters) in a sentence or two, then the artifact carries the detail.

**Use one when** the content is a comparison with numbers or several attributes (→ `table`, or `chart` when the shape is the point: trend, share, ranking), a handful of headline figures (→ `stat`), steps or a checklist (→ `list`), one thing he must not miss (→ `callout`), or a long result he will keep and reread: a research report, a plan, a spec (→ `iris-doc`). **Skip it** for a spoken-first answer of a few sentences, a single fact, a side effect's confirmation, or anything a short list in the prose already says. When in doubt, no artifact.

**Limits:** at most **three artifacts per reply**; a `iris-show` body ≤ 64 KiB, an `iris-doc` body ≤ 200 KiB, `title` 1–200 chars. Nothing in them but content (no secrets, tokens, hostnames). Language follows the memo.

`iris-show` — the body is **one JSON object**, strict (an unknown key invalidates it), `type` picks the shape:

````
```iris-show
{"type": "table", "title": "Hosting options", "columns": ["Option", "€/month", "Setup"], "rows": [["A", 12, "easy"], ["B", 9.5, "medium"], ["C", 20, "hard"]]}
```
````

- `table`: `columns` 1–12 strings (≤ 80 chars), `rows` ≤ 200, each row **exactly as long as `columns`**, cells string / number / boolean / null.

````
```iris-show
{"type": "chart", "kind": "bar", "title": "Monthly cost", "unit": "€", "x": ["A", "B", "C"], "series": [{"name": "Cost", "values": [12, 9.5, 20]}]}
```
````

- `chart`: `kind` is `bar|line|area|pie`; `x` 1–100 labels (strings or numbers); `series` 1–8 `{name, values}` with **as many values as `x`** (null = gap); a `pie` takes exactly one series; `unit` ≤ 16 chars.

````
```iris-show
{"type": "stat", "title": "This week", "items": [{"label": "Sleep", "value": 7.4, "unit": "h", "delta": -0.3}, {"label": "Steps", "value": "8,200", "hint": "goal 10,000"}]}
```
````

- `stat`: `items` 1–8 `{label, value (string|number), unit?, delta? (a number), hint? (≤ 200)}`.

````
```iris-show
{"type": "list", "title": "Before the trip", "ordered": true, "items": [{"text": "Renew passport", "detail": "Appointment needed, 3 weeks"}, {"text": "Book train"}]}
```
````

- `list`: `items` 1–50 `{text (≤ 500), detail? (≤ 1000)}`, `ordered?` boolean.

````
```iris-show
{"type": "callout", "tone": "warning", "title": "Deadline", "body": "The offer ends Friday."}
```
````

- `callout`: `tone` is `info|success|warning|danger`, `body` 1–2000 chars, `title?`.

`iris-doc` — the info string holds `title="…"` (double quotes, no escapes inside) and `format=markdown|html` (default markdown); no other key, none twice; the body is the document, never empty:

````
```iris-doc title="Hosting comparison" format=markdown
# Hosting comparison

Option B is cheapest; A is the easiest to run.
```
````

A document that itself contains code fences needs a longer outer fence (` ````iris-doc `). Prefer markdown; HTML only when he asks for a styled page.

Artifacts go **before** the closing `iris` block, which still comes last.

## The closing block — always, exactly one, last

End the reply with exactly one fenced block tagged `iris`, **nothing after the closing fence** (no sign-off, no second block, no trailing newline text):

````
```iris
{"kind": "answer", "headline": "Berlin ist 3 °C wärmer als München"}
```
````

- **One line of valid JSON**, double quotes, exactly the two string keys `kind` and `headline` — no `spoken`, no others (the spoken line and the real summary are Iris's own `triage` step), no trailing commas, no comments. Escape quotes inside values.
- `kind` — 1–3 words, lower-case, how the app labels the result. Prefer this set: `answer`, `task`, `github issue`, `note`, `tab prompt`, `agent work`, `chat`, `research`, `error`. A new label only when none fits.
- `headline` — **≤ 60 characters**, what happened or the gist of the answer. Plain text, no markdown. It becomes the push alert.
- The block is **always** present on an Iris turn — also on failure (`error`), on a refusal, and when the reply is one line. If you fail to do the work at all, still emit the block.
- Don't mention the block in prose; don't wrap it in anything else.
- **Last check before you send:** is the memo English? Then the reply and `headline` are English too — `{"kind": "task", "headline": "Passport photo reminder, due Sunday"}`. German memo, German headline. Only `kind` is always English.
