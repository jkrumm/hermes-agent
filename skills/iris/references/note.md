# Iris — filing a brain note

Loaded by the iris skill for a note memo (with `skill_view('obsidian')`). The turn rules, the reply and the closing `iris` block are in SKILL.md.

A note, idea, observation, measurement or plan goes **straight to its home in the vault**, not to the Inbox. The procedure (search, pick the home, write, lint, commit) is the obsidian skill's **Filing a note** — `skill_view('obsidian')` and follow it; this section adds the Iris specifics.

| The memo is | Home |
|-|-|
| A shot or measurement for an existing log (a coffee dial-in) | `wiki/coffee/dial-in-log.md`: a new entry in the log's own format, newest on top |
| An idea or fact for something that already has a page (a project, an Area, a `wiki/` concept) | that page, rewritten in the relevant section — never appended |
| A durable concept with no page | a new `wiki/<domain>/…` note, full frontmatter, the level's `index.md` updated |
| A gift idea, or a fact about a person (size, prescription, what they like) | `Areas/Shopping/Gifts.md`: a row in the person's table (a new `## <Name>` section if missing), a size or prescription on the person's **Sizes** line; never the Inbox |
| A journal-style reflection, or no clear home | `Inbox/`, via the script below |

Search the vault before you choose (`obsidian search`, `agw brain`); the memo's own title is never the home. Prose follows `~/SourceRoot/brain/voice.md`; a page longer than a few paragraphs goes through `agw prose` first. A `wiki/` note or log entry is English (the vault rule, numbers verbatim); an Inbox note keeps the memo's language. After every write: `node .scripts/vault-lint.mjs` in the vault (0 errors), then `~/.hermes/scripts/brain-commit.sh "<what and why>" <paths>`. A memo that names two homes is two writes.

**The Inbox — script only.** For a journal-style reflection or a memo with no clear home, use the script; it does the lock, the commit and the push:

```bash
python3 ~/.hermes/skills/iris/scripts/iris-note.py <<'MEMO'
<the memo text, STT repaired, otherwise verbatim — German stays German>
MEMO
```

It prints `{"ref": "Inbox/2026-11-04-….md", "committed": true, "title": "…"}`.

- Exit **0** = written, committed (push fail-soft, brain-sync pushes later). Exit **3** = brain-sync's lock was busy: the note exists but is **not committed** — say so in the reply, `kind` `error`; retry at most once in the same turn (`~/.hermes/scripts/brain-commit.sh "journal: <title>" <ref>`). The same exit 3 from `brain-commit.sh` on a direct write means the same: written, not committed.
- Never `git commit` in the vault by hand; commits go through `brain-commit.sh`. Never write a note to the vault root.
- The script's rules, for the record: file `Inbox/YYYY-MM-DD-<slug>.md` (local date; `-<first 8 of the session id>` appended on a name clash); title = first sentence, ≤ 60 chars clipped on a word boundary, trailing `.,;:` stripped, `Voice memo` if empty; slug = lower-case ASCII, `ä→ae ö→oe ü→ue ß→ss`, other accents folded, ≤ 50 chars, `memo` if empty; frontmatter `title` (JSON-quoted), `date`, `tags: [journal, iris]`, `source: iris`, `memo: <session id>` (a retry reuses the note); commit message `journal: <title>`; brain-sync's mkdir lock `~/Library/Caches/brain-sync.lock` taken by `brain-commit.sh`.
- Journal entries stay the one exception to the obsidian skill's "no journal entries" guardrail: an Iris reflection is an Inbox note tagged `journal` (the script does it), nothing more. Any other journal request stays refused.

**The reply names the path written** (`wiki/coffee/dial-in-log.md`, `Inbox/…`), `kind` `note`; a judgement call about the home is one clause.

