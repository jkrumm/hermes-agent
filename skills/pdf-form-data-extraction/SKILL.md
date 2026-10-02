---
name: pdf-form-data-extraction
description: Use when a form PDF must yield its data, not the template.
version: 1.0.0
metadata:
  hermes:
    tags: [pdf, form, acroform, contract, vertrag, extraction, pypdf, encrypted]
    related_skills: [ocr-and-documents, personal-finance]
---

# Form PDFs: extracting the data, not the template

The rule that costs sessions: **a signed contract, insurance or tax form is an
AcroForm PDF whose page text is the BLANK TEMPLATE.** The answers live in the
form field values and no text extraction prints them. `read_file`, `pdftotext`,
`pdfimages -list` and OCR all show an empty form, and concluding "the document
is blank" from them is wrong — the counterparty's figures are usually in there.

## Procedure

1. **Signal to look:** `pdfinfo <file>.pdf | grep -Ei "form|encrypted|pages"` →
   `Form: AcroForm`. (`Encrypted: yes (print:yes copy:no)` is normal on vendor
   forms — an owner password with an empty user password, still readable.)
2. **Dump the fields** (system python usually has neither `pypdf` nor PyPDF2):

```bash
python3 -m venv /tmp/pdfv && /tmp/pdfv/bin/pip install -q pypdf cryptography
/tmp/pdfv/bin/python - <<'EOF'
from pypdf import PdfReader
r = PdfReader("<file.pdf>")
f = r.get_fields() or {}
print("fields:", len(f))
for k, v in f.items():
    val = v.get("/V")
    if val not in (None, "", "/"):
        print(f"  {k} => {val!r}")
EOF
```

3. **Read the dump as the answer.** Field names carry the meaning
   (`Gesamtpreis`, `Sondervereinbarungen`, `Typ`, `Erstzulassung`, `Name VK` /
   `Name K`, `Beschäd 1`, …); checkboxes come back as `/Ja`/`/Off` — map them to
   the printed label, never guess. A 60-value dump is one command away.
4. **Sanity-check** the extracted values against the page text that IS printed
   (signature dates, a price in words next to the figure).

## Pitfalls

- **`pypdf` without `cryptography` dies with `DependencyError: cryptography>=3.1
  is required for AES algorithm`** on AES-encrypted PDFs. Install both in the
  same venv; a `pypdf`-not-found is the wrong interpreter, not a missing skill.
- **`mutool` is a misleading oracle**: `mutool clean -p "" -d` can report
  `format error: partial block in aes filter` and still emit 0 fields. Don't
  conclude "unfilled" from it.
- **A decrypt/format error does not mean a truncated download.** Check the tail
  for `startxref` + `%%EOF` before telling the user the file is incomplete.
- **0 images in `pdfimages -list` ≠ nothing filled in.** It only rules out a
  scan/handwriting layer.
- **Only when the fields are empty too** does the document truly carry no
  figures — then say so plainly and ask for the signed scan, rather than
  inferring values from the template.
- **Never quote personal identifiers** (passport numbers, phone numbers) back
  into chat or a committed note just because they came out of the dump; extract
  what the task needs (price, instalments, dates, vehicle/property identity).

## Where the numbers go next

A contract figure typically feeds arithmetic (instalment plans: total / rate →
last payment date, done in Python, never mentally), an artifact the user can act
on (a task whose body carries every number), and — once the figures are settled
— a durable record. For Johannes's own contracts the money-question workflow is
the `personal-finance` skill; this skill is only the extraction step.
