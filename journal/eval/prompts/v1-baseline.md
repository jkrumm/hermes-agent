# Prompt v1 — baseline

**Variant ID:** `v1-baseline`
**Purpose:** establish the floor. JOURNAL.md is loaded as system context; this prompt asks for the structured output and nothing more. Anti-sycophancy and CBT framing rely entirely on JOURNAL.md.

**Substitution slots** (filled by `journal/eval/run.py` and `journal/scripts/ingest.py`):
- `{TRANSCRIPT}` — full transcript text, no timestamps in eval mode, with `> [HH:MM]` segment markers in live mode.
- `{KNOWN_PEOPLE}` — comma-separated list of existing person entities. Empty string if none.
- `{KNOWN_PLACES}` — comma-separated list of existing place entities.
- `{KNOWN_EMOTIONS}` — comma-separated list of existing emotion entities.
- `{PRIOR_ENTRY_CONTEXT}` — optional. Last 2 entries' frontmatter (mood, top emotion, themes), max ~200 tokens. Empty string if none or if backfill.

---

## SYSTEM

(loaded from `~/SourceRoot/brain/01_Journal/JOURNAL.md` — see that file)

## USER

Du analysierst einen Journal-Eintrag von Johannes. Halte dich strikt an JOURNAL.md.

### Transkript

```
{TRANSCRIPT}
```

### Bekannte Entitäten

Verwende exakt diese Namen, wenn sie im Eintrag vorkommen. Alles, was nicht in diesen Listen ist, gehört in `new_entities`.

- Personen: {KNOWN_PEOPLE}
- Orte: {KNOWN_PLACES}
- Emotionen: {KNOWN_EMOTIONS}

### Vorheriger Kontext

{PRIOR_ENTRY_CONTEXT}

### Output

Liefere genau einen YAML-Block, gefolgt von den vier Markdown-Sektionen, in der in JOURNAL.md §6 definierten Reihenfolge. Keine Einleitung, kein Abschluss, kein Meta-Kommentar.
