# Personal finance questions

_Use when a personal money question needs a number._

Johannes's own contracts, credits and payment plans — "wie lange muss ich noch zahlen", "wann ist X abbezahlt", "was steht in Finance dazu", a Raten-/Darlehensvertrag he drops into chat. The deliverable is a number he can act on **plus** a reminder that fires before the money moves — not a research report.

## Procedure

1. **Vault first** (skill `obsidian`): the finance surface today is thin — `Areas/Finance/Finance.md` plus one page per deal (e.g. a property) and `wiki/finance/`. Search with several keys at once, never one:
   `grep -rin "<counterparty>\|<amount>\|<object>" --include="*.md" ~/SourceRoot/brain`
   One narrow grep is **not** evidence of "not recorded". `git pull --rebase` first if a write may follow.
2. **Read the attachment he sent.** `read_file` extracts a PDF text layer directly — no OCR detour. Then check whether the document actually carries data: `pdfinfo` (`Pages`, `Form: AcroForm`) and `pdfimages -list` (0 images = nothing handwritten scanned in). A downloaded blank form (e.g. an ADAC-Kaufvertrag template) yields only printed boilerplate — say plainly that the PDF holds no figures instead of inferring them from the template.
3. **Cross-check mail via argo** (`references/schedule.md` of the `argo-api` skill): `/gmail/emails?query=…&scope=all`. The filter is loose — operator syntax like `from:` is not reliably honored, so an empty result is **inconclusive**: re-query with a broad bare keyword before reporting "nothing found". Mail that lives on another account never appears at all.
4. **Anchor on the counterparty's own count** when nothing is recorded (a parent's mail quoting "N paid, M remaining"). Verify that count against the schedule instead of trusting it: for a payment on day D of each month, `n = full months between first payment and the mail date` (`+ 1` if the mail is after day D). Match ⇒ the anchor is sound; mismatch ⇒ say so and use the schedule.
5. **Do the arithmetic in Python, never mentally.** `dateutil.relativedelta`: payment `#k = first_payment + (k-1) months`; `total = (n + remaining) * amount`; print the weekday of every candidate last payment. Real tool output is the evidence behind every number you report.
6. **Report both candidate ends when the source gave a range, and lead with the earlier one** — standing instruction: "lieber einen Monat früher als einen Monat später".
7. **Add the bank-mechanics clause:** a debit landing on a weekend/holiday usually moves to the next business day, so recommend setting an **end date** on the Dauerauftrag rather than deleting it — an end date cannot let an extra debit slip through.
8. **Leave an artifact:** create a TickTick task in 🏠Personal (`69a32ea26de7515d72e6c664`), priority 3, due a few days before the final payment, with every number in `content` (payments made, sum so far, the remaining dates, the total). Then re-read `/ticktick/projects/69a32ea26de7515d72e6c664/data` to verify it exists, and name the task and its date in the reply.

## Rules

- **Do not write the deal into the vault unprompted.** Curated `Areas/` pages are human-owned (voice and publish decision are his), and tasks live in TickTick, never in the vault. Report what is missing; leave the note to him.
- **State the assumption behind the number** in the reply (which total, which payment was the first, that a count is the counterparty's rough figure) — he re-checks the arithmetic.
- **Answer in German, verdict first, dense** (3–6 lines, one bullet per finding); values and dates bold; no recap of which sources you tried unless a source came back empty.
- **Report empty sources explicitly** (e.g. "kein Eintrag zum Deal im Brain, dort nur die Wohnung") — the lookup was part of the ask, so a miss belongs in the answer.
- Never present a counterparty's "ungefähr" as exact, and never present a derived total as a contract figure.

## Tool pitfalls (argo JSON shapes)

The `argo-api` skill's "response envelope" section is not uniform in practice — parse by shape, never by assumption:

- `/gmail/emails` → **bare array** of message objects (`from` is a `{name, email}` object, not a string); no `data`/`total`.
- `/ticktick/projects` → `{data: [...]}`; `/ticktick/projects/{id}/data` → `{data: {tasks: [...]}}` — nested, so index `["data"]["tasks"]`, never `["data"]`.
- A parse error like `TypeError: unhashable type: 'slice'` or an `AttributeError` on `str`/`list` means the shape was different, not that the call failed: dump `type(d)` and `json.dumps(d)[:500]`, then adapt.
- There is **no TickTick task-search endpoint**: to find a task by keyword, loop `/ticktick/projects` → `/ticktick/projects/{id}/data` across all projects and grep the JSON.
