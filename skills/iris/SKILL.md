---
name: iris
description: Handle a turn from Iris, Johannes's voice-memo app. The message is a speech-to-text transcript; decide what it is (question, todo, GitHub issue, note, tab prompt, chat), act with the existing skills, and end the reply with exactly one iris block (JSON kind/headline). Preloaded on every turn whose system message says it comes from Iris; references/ holds the note-filing procedure and the artifact fences.
version: 1.1.0
metadata:
  hermes:
    tags: [iris, voice, memo, transcript, stt, voice-memo, decide, route, note, journal]
    related_skills: [fleet, capture, obsidian, herdr, agw-research, karakeep]
---

# Iris — a voice memo, decided and acted on

Iris (Johannes's voice-memo app, server on this mini) no longer classifies memos. **You decide** what the memo is and act with your existing skills. This skill is already in your context on an Iris turn (the system message says "This turn comes from Iris"): do not `skill_view('iris')` again. CLI, Desktop, cron and every other turn are untouched: no `iris` block there, ever.

## The turn

- The message is a **transcript** of a spoken memo, German or English, with speech-to-text errors. Repair the obvious ones silently (a misheard repo or product name, a dropped word); never mention the repair.
- **Answer in the memo's language** — reply, headline, issue or task title and Inbox note body; an English memo gets English everywhere, a German one German, even after loading `capture`, `obsidian` or `herdr` or seeing the other language in a tool result. A `wiki/` note is English either way. SOUL.md's German default does not apply on an Iris turn. Never translate the memo text.
- **Ask nothing.** He recorded a memo on a phone; nobody answers a question mid-turn. Pick the most likely reading, state the assumption in one clause in the reply, proceed.
- **A side effect only when the memo asks for one** (a todo, an issue, a note, a tab prompt, an agent hand-off) or the hint below says so. A question gets an answer, not an action. Act on the memo as spoken, even if it calls itself a test; only its own words ("nur testen, nichts anlegen") cancel the side effect.
- A follow-up turn in the same session carries the same system message — same rules.

## Decide — first match wins

| The memo is | Do |
|-|-|
| A question, "wie/was/warum/…", a lookup | Answer. Web or library facts, "recherchier…" → `skill_view('agw-research')`. Personal data (calendar, tasks, health, infra) → `argo-api`. |
| "How is X going", "what needs me", "what ran overnight", "any alerts", "what's running" | `skill_view('fleet')` — read. |
| Agent work on a repo to **start**: "let an agent fix X in <repo>", "start an agent on …", "lass einen Agenten … in <repo> …" | `skill_view('fleet')` — file one Issue. Its filing rules apply; the iris `via` is `iris voice memo`. |
| A todo, reminder, errand, "erinner mich…", or "open an issue / Issue für <repo>" | `skill_view('capture')` — it owns TickTick vs GitHub, the repo, the list. Its "ask if unclear" does **not** apply here: fall back to its default and say which. The memo text goes into the item **verbatim** (STT repairs only). |
| "tell / prompt / sag Tab X …", "schreib in den Tab …" (an **existing** terminal only) | `skill_view('herdr')` — find the tab, `hc send <target> "<text>"`. Text = what he wants said to the agent, in his words, not the addressing phrase. Obey the skill's rules (never `--force`, never a blocked agent, a draft in the input line is not yours). |
| A note, idea, observation, plan, logged measurement ("Espresso: Mahlgrad 9, 37 s …") or reflection with **no question and no request** ("ich denke gerade…", "Idee: …", "notier dir…", a journal-style thought) | A brain note. Load `skill_view('iris', 'references/note.md')` **and** `skill_view('obsidian')` in one step, then follow note.md. |
| Greeting, small talk, "test", a remark that wants a reply and nothing else | Chat: answer from yourself in a line or two — no tool calls, no status report, no side effect. |
| A link or YouTube video with a question or "fass zusammen / was steht da / worum geht's" | `skill_view('agw-web')` — `agw web read` / `agw web youtube`, then answer. "…und merk's dir" adds a `karakeep` save. |
| A link/article to keep for later (no question about its content) | `skill_view('karakeep')`. |
| Anything else, or two readings that both fit | The cheaper, reversible one; say the reading you took. |

Repo code work is **filed** (a GitHub issue via `capture`) when the memo says *file*, *note* or *open an issue*, and **handed to the factory** (`fleet`) only when it says *start* or *let an agent*. You never do repo work yourself — same as everywhere (SOUL.md). "Fix X in <repo>" with neither wording: file it and say so.

A table, chart or long keep-worthy result may ride along as an `iris-show` / `iris-doc` fence: only then load `skill_view('iris', 'references/artifacts.md')`. When in doubt, no artifact.

## The owner-picked hint (legacy app builds)

An old Iris build ends the system message with `The owner picked: <Mode>.` It **overrides the table**; no hint line = decide yourself.

- **Journal.** → write the memo as an `Inbox/` journal note (the script in note.md), whatever it says.
- **Tab.** → a herdr tab prompt. If the memo names no tab (or none matches), send nothing and say which tabs are live (purpose, not address — `hc ls`).
- **Chat.** → answer only. No writes, no sends, no tickets, no issues, no notes. Read-only lookups are fine; if he asked for a change, say what you would have done and that Chat mode cannot.

## The reply

It is what he reads on a phone: **verdict first**, short — usually 1–4 lines. Markdown renders (lists, code, tables, Mermaid); use it only when it carries content. No greeting, no name, no "Done!" filler, no process narration. Name what happened and where (the issue link, the task's list, the note's path, the tab by purpose). SOUL.md's one-line-per-item contract still shapes status-type replies. Never put secrets, tokens or hostnames in it. The reply is also read aloud, so it must stand without any artifact.

If the requested side effect failed, say that plainly with the cause in one clause — never report a substitute as the thing he asked for.

## The closing block — always, exactly one, last

End the reply with exactly one fenced block tagged `iris`, **nothing after the closing fence** (no sign-off, no second block, no trailing text):

````
```iris
{"kind": "answer", "headline": "Berlin ist 3 °C wärmer als München"}
```
````

- **One line of valid JSON**, double quotes, exactly the two string keys `kind` and `headline` — no `spoken`, no others, no trailing commas, no comments. Escape quotes inside values.
- `kind` — 1–3 words, lower-case, always English. Prefer `answer`, `task`, `github issue`, `note`, `tab prompt`, `agent work`, `chat`, `research`, `error`; a new label only when none fits.
- `headline` — **≤ 60 characters**, what happened or the gist of the answer, in the memo's language (an English memo: `{"kind": "task", "headline": "Passport photo reminder, due Sunday"}`). Plain text, no markdown. It becomes the push alert.
- The block is **always** present — also on failure (`error`), on a refusal, and when the reply is one line. Don't mention it in prose; don't wrap it in anything else.
