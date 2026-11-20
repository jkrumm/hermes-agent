# Iris — artifacts beside the prose

Loaded by the iris skill when a memo's answer wants a table, chart or document. The closing `iris` block still comes last (SKILL.md).

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

