# Hermes Journal — PRD

**Status:** v1.1 — Phase 1 complete, Phase 2 paused at pre-execution recon (postponed by Johannes)
**Owner:** Johannes
**Last updated:** 2026-05-13

---

## 1. Goal

Build a voice-first journaling system on top of the existing Hermes Agent + Obsidian setup. iPhone Voice Memo → Slack `#journal` → Hermes ingest → structured Obsidian entry with anti-sycophantic psychological reflection in German. Backfilled and validated against 95 existing Mindsera entries before going live.

**Success criterion:** the system produces analysis at least as deep and honest as Mindsera, in idiomatic German, without sycophancy. Measured via blind LLM-judge scoring on the 95-entry eval set.

---

## 2. Non-goals

- No new daemon, no new server. Runs on the existing Mac Mini Hermes Agent.
- No vector DB, no RAG. Plain markdown + Obsidian wikilinks (Karpathy pattern).
- No Obsidian plugin development. Ingestion is a Hermes skill + Python scripts.
- No public-facing image CDN. Attachments are vault-internal.
- No therapy. The system structures, reflects, and pushes back honestly. It does not diagnose, escalate, or replace a clinician.
- No daily/weekly cadence — Johannes journals every other day at most. Reflection is per-entry, with optional monthly roll-up.

---

## 3. User context

- **Johannes Krumm**, solo senior dev. Runs Hermes Agent on Mac Mini M2 Pro. Slack as primary interface. Obsidian for knowledge. Tailscale-connected homelab + VPS.
- Journals in **spoken German**, never typed. Has done this for years on Mindsera. Wants to own the pipeline now.
- Existing Mindsera corpus: **95 entries** at `~/Downloads/entries/<YYYY-MM-DD - <mindsera-id>>/{entry.md, analysis.md}`. The original voice memos are still on his iPhone — he will export them.
- **Pending memos**: ~15 iPhone Voice Memos recorded since leaving Mindsera, not yet processed.
- Tone preference: senior-to-senior, technical, no superlatives. Anti-sycophancy is a hard requirement — explicit in `~/.claude/CLAUDE.md`.

---

## 4. Existing infrastructure to leverage

| Component | Where | Status |
|-|-|-|
| Hermes Agent | `~/SourceRoot/hermes-agent` symlinked into `~/.hermes` | Running |
| Parakeet TDT v3 STT | `127.0.0.1:8000/v1` (mlx-audio) | Running, multilingual EU |
| Fish S2 Pro TTS | `127.0.0.1:8001/v1` (localai-helper) | Running, EN/DE voices |
| Slack platform | Hermes built-in | Wired, `#journal` channel exists |
| LiveSync (CouchDB) | Self-hosted via vrtmrz/obsidian-livesync | Running, syncs vault to iPhone + other Macs |
| Restic → Backblaze B2 | Existing cron | Running — confirm `~/Obsidian/Vault` is in includes |
| IU Anthropic endpoint | `${ANTHROPIC_BASE_URL}` (DPA covered, free for Johannes) | Wired in `.env` |
| Claude Sonnet 4.6 / Opus 4.7 | via IU | Available via `auxiliary` and `model` config |
| Gemini 2.5 Flash (vision) | direct API | Wired for vision only |
| `~/Obsidian/Vault/` | LiveSync target | The single shared Obsidian vault |
| Hermes cron | runs `morning-briefing`, `watchdog`, `evening-report` via pre-run scripts | Pattern to copy for monthly roll-up |

---

## 5. Locked decisions

Numbered for reference. Don't relitigate without flagging.

1. **Vault**: single existing `~/Obsidian/Vault/`. Journal is a `Journal/` subtree inside it. **No second vault.**
2. **Channel**: `#journal` (Slack channel exists). Top-level message = new entry. Thread reply = continuation of that entry.
3. **Language**: All German throughout — entries, analysis, reflections, Slack acks. Entity note titles in German (`entities/people/Anna.md`, `entities/places/München.md`, `entities/emotions/Angst.md`). Meta-rules in JOURNAL.md may be English where they're rules-about-the-rules.
4. **Tone**: honest + warm + contrarian. **Anti-sycophancy is a hard requirement** — see §9 for exact forbidden phrases and required behaviors. Hard floor: no diagnosis, no escalation, defer crisis to canned message.
5. **Privacy**: IU Anthropic endpoint is the only LLM path. No Gemini, no OpenAI for analysis. (gpt-image-2 is OK for cover art — that's not psychological content.)
6. **Models**:
   - **Analysis**: Claude Opus 4.7 via IU. Reasoning: Constitutional AI training is the only published anti-sycophancy intervention; best EN↔DE LQA evidence; DPA already covered. Sonnet 4.6 not used in v1 — start with Opus only, add routing later if cost matters.
   - **STT**: Parakeet TDT v3 always. Apple `tsrp` atom transcripts dropped entirely — Mindsera's old STT and Apple's on-device STT both inferior to Parakeet for German. One transcription path.
   - **Image gen**: gpt-image-2 (OpenAI), medium quality, ~$0.05/cover.
   - **Judge LLM** (eval only): Sonnet 4.6 via IU. Different model than analyzer, blind comparison.
7. **Storage**: in-vault `Journal/_assets/{audio,covers}/`. No external S3, no imgproxy.
8. **Audio codec**: Opus @ 24 kbps, mono, 16 kHz. ~180 KB/min. ffmpeg: `ffmpeg -i in.m4a -c:a libopus -b:a 24k -ac 1 -ar 16000 out.opus`.
9. **Image codec**: AVIF @ q=70. ~100 KB per 1024². Native Obsidian rendering since 2024.
10. **Sync**: LiveSync (CouchDB) for both `.md` and binaries. Volume (~80 MB/month) is well within LiveSync's working envelope. **No Syncthing**, **no Obsidian Sync**, **no iCloud**.
11. **Backup**: existing restic → Backblaze B2 covers the vault. Verify `~/Obsidian/Vault` is in restic includes. Additionally, extend `scripts/hermes-backup.sh` to rsync vault to `homelab:/mnt/hdd/Dokumente/Obsidian/`.
12. **Eval execution**: `claude -p` against the user's Claude subscription (independent fresh-context calls, fits subscription model). Direct Anthropic SDK against IU is the alternative if subscription limits bite — same code, swap auth.
13. **Mindsera backfill structure**: honor Mindsera's per-entry split. 4 entries on 2025-09-27 in their export → 4 of our entries. Don't merge same-day Mindsera entries.
14. **Live multi-memo per day**: top-level Slack message = new entry. Thread reply = continuation. Hermes concatenates all transcripts in a thread chronologically into one entry body.
15. **Reflection cadence**: per-entry (synchronous with ingest). Plus a monthly roll-up cron (first Sunday of month). **No weekly review.**
16. **Obsidian attachments setting**: leave global "Default location for new attachments" as-is. Hermes writes journal media to `Journal/_assets/` programmatically via direct paths. Manual drag-attach in non-journal notes follows existing config.

---

## 6. Architecture

```
                                 ┌──────────────────────┐
       iPhone Voice Memos        │   ~/Obsidian/Vault/  │
            │                    │   Journal/           │
            │ share              │   ├── entries/       │
            ▼                    │   ├── entities/      │
       Slack #journal            │   ├── _assets/       │
            │                    │   ├── analysis/      │
            │ file_shared event  │   ├── log.md         │
            ▼                    │   └── JOURNAL.md     │
       Hermes journal-ingest ────► (writes here)
            │                    └──────────┬───────────┘
            ├─► Parakeet (STT)              │
            ├─► ffmpeg (Opus encode)        │ LiveSync
            ├─► Opus 4.7 (analysis)         │ (CouchDB)
            ├─► gpt-image-2 (cover)         ▼
            └─► Slack ack reply        Other devices
                                       (iPhone, Macs)
```

Every component is already standing except the Hermes `journal-ingest` skill and the helper scripts.

---

## 7. Directory structure

### Vault (the data)

```
~/Obsidian/Vault/
└── Journal/
    ├── JOURNAL.md                    # tone/structure rules, read by Hermes on every ingest
    ├── log.md                        # append-only ingest log: ## [YYYY-MM-DD HH:MM] <slug> | <action>
    ├── index.md                      # auto-maintained catalog (counts, latest, top entities)
    ├── raw/
    │   └── audio/
    │       └── 2025-09-27-001.opus   # immutable, post-Opus-encode, never mutated
    ├── entries/
    │   └── 2025-09-27 — kurze-beschreibung.md
    ├── entities/
    │   ├── people/
    │   │   └── Anna.md
    │   ├── places/
    │   │   └── München.md
    │   └── emotions/
    │       └── Angst.md
    ├── analysis/
    │   └── monthly/
    │       └── 2026-04.md
    └── _assets/
        ├── audio/                    # symlinks or duplicates of raw/ for Obsidian embed
        └── covers/
            └── 2025-09-27.avif
```

`raw/audio/` exists for Karpathy-purity (immutable archive). `_assets/audio/` is what entries link to for Obsidian to embed. Implementation can either symlink or duplicate — symlink is simpler and LiveSync-safe (it follows symlinks within the vault root).

### Repo (the code)

```
~/SourceRoot/hermes-agent/
├── journal/                          # all journal-related code lives here
│   ├── PRD.md                        # this file
│   ├── eval/
│   │   ├── ground_truth/             # symlink → ~/Downloads/entries
│   │   ├── voice_memos/              # symlink → exported voice memo folder
│   │   ├── prompts/
│   │   │   ├── v1-baseline.md
│   │   │   ├── v2-anti-sycophancy.md
│   │   │   └── v3-with-cbt-frame.md
│   │   ├── judge.md                  # judge prompt
│   │   ├── runs/
│   │   │   └── <iso-timestamp>--<variant>/
│   │   │       ├── outputs/
│   │   │       │   └── <mindsera-id>.md
│   │   │       └── scorecard.json
│   │   ├── run.py                    # the eval harness
│   │   └── README.md                 # how to run
│   ├── scripts/
│   │   ├── match_voice_memos.py      # pair Mindsera dates ↔ exported audio files
│   │   ├── compress_audio.sh         # ffmpeg → Opus
│   │   ├── compress_image.sh         # → AVIF
│   │   └── ingest.py                 # the live ingest pipeline (called by Hermes skill)
│   └── tests/
│       └── test_schema.py            # frontmatter validation
└── skills/
    └── journal-ingest/
        └── SKILL.md                  # Hermes skill, symlinked via Makefile
```

Add `journal-ingest` to `HERMES_SKILLS` in the Makefile and run `make setup`.

---

## 8. Data schemas

### 8.1 Entry frontmatter

Every entry under `entries/` has this frontmatter:

```yaml
---
date: 2025-09-27                   # ISO date, primary key (combined with slug)
slug: kurze-beschreibung           # 3-6 word kebab-case German summary
mood: 4                            # 1-10 integer; 1=lowest, 10=highest
emotions:                          # wikilinks to entities/emotions/*.md
  - "[[Angst]]"
  - "[[Unsicherheit]]"
  - "[[Verwirrung]]"
people:                            # wikilinks to entities/people/*.md
  - "[[Anna]]"
places:
  - "[[München]]"
themes:                            # plain strings, not wikilinks (themes are softer than entities)
  - Selbstwert
  - Beziehungen
source: voice-memo                 # enum: voice-memo | slack | typed | mindsera-backfill
audio_paths:                       # relative to vault root
  - _assets/audio/2025-09-27-001.opus
  - _assets/audio/2025-09-27-002.opus
cover_image: _assets/covers/2025-09-27.avif
mindsera_id: cmg2460fh0000nfigtr1lxm2s   # only for backfill; null otherwise
ingest_meta:
  transcribed_with: parakeet-tdt-0.6b-v3
  analyzed_with: claude-opus-4-7
  prompt_variant: v3-with-cbt-frame
  ingested_at: 2026-05-04T14:32:00+02:00
---
```

JSON Schema lives in `journal/schema/entry.schema.json` (implementer creates). `tests/test_schema.py` validates every entry on a CI hook (or a manual `make journal-lint`).

### 8.2 Entry body sections

```markdown
## Transkript

> [00:00] First memo segment...
> [03:24] Second memo segment (if multiple in same entry)...

![[2025-09-27-001.opus]]
![[2025-09-27-002.opus]]

## Zusammenfassung

- Bullet 1
- Bullet 2
- ...

## Emotionen

- **Angst (40%)** — Beleg: "..." (Zitat aus dem Transkript)
- **Unsicherheit (30%)** — Beleg: "..."
- ...

## Reflexion

(CBT-style reframe — alternative reading of the situation, named cognitive distortions if any, no diagnosis. German.)

## Folgefrage

(One Socratic question to think about. German.)
```

### 8.3 Entity notes

Tiny. Frontmatter + a one-line description. Backlinks paragraph is automatic via Obsidian.

```markdown
---
type: person                       # enum: person | place | emotion
aliases: [Anna K., Anna]
first_seen: 2025-09-27
---

# Anna

(Optional: 1-2 sentences of context Hermes infers and Johannes can edit.)
```

Entity creation rule: if the analyzer mentions `[[Foo]]` and `entities/<type>/Foo.md` doesn't exist, the ingest script creates it with skeleton frontmatter. Never auto-creates body content beyond a placeholder line.

### 8.4 `JOURNAL.md` (the schema doc Hermes reads)

Implementer drafts this. It contains:
- The frontmatter schema (above) as a pasted reference
- The entry body section spec (above)
- The tone rules (§9 below) — copy-pasted verbatim into JOURNAL.md
- The harm-reduction floor (§9.3)
- The entity discipline rules (§8.3)
- The German-language rule

Hermes loads `JOURNAL.md` as part of the analysis prompt. It IS the analysis context.

### 8.5 `log.md`

Append-only. One line per ingest event. Format:

```
## [2025-09-27 14:32] kurze-beschreibung | ingest | parakeet+opus-4-7+v3
## [2025-09-28 09:15] morgenroutine | ingest | parakeet+opus-4-7+v3
## [2025-09-28 22:47] morgenroutine | revise | mood corrected 5→3 (manual)
```

### 8.6 `index.md`

Auto-maintained by the ingest script. Shape:

```markdown
# Journal Index

**Total entries:** 110
**Latest:** [[2026-05-03 — irgendwas]]
**Active streak:** 3 days

## Top entities (last 90 days)
- [[Anna]] (12 mentions)
- [[München]] (8 mentions)
- [[Angst]] (6 mentions, declining trend ↓)

## Recent themes
- Selbstwert
- Beziehungen
- Arbeit

## Bases
- [[Stimmung-über-Zeit]]
- [[Personen-Häufigkeit]]
- [[Themen-Drift]]
```

---

## 9. Tone & guardrails (the load-bearing prompt section)

This is the part that determines whether the system is good or bad. JOURNAL.md must contain these rules verbatim. The analysis prompt loads JOURNAL.md and applies them.

### 9.1 Forbidden phrases (German)

The analyzer must NEVER produce these or close paraphrases:

- "Du hast völlig recht" / "Du hast absolut recht"
- "Das ist absolut verständlich" / "Total nachvollziehbar"
- "Du bist so resilient" / "Du machst das großartig" / "Du bist stark"
- Any unprompted validation that doesn't cite specific evidence from the entry text

### 9.2 Required behaviors (German)

- **Disproportion check**: if a named emotion seems disproportionate to the evidence in the text, name it. Example: entry mentions a minor incident, analyzer infers 80% Angst → "Die Reaktion erscheint im Verhältnis zum geschilderten Auslöser groß. Frage: was triggerte das eigentlich — der Auslöser selbst oder etwas Älteres?"
- **Alternative readings**: when the entry's narrative has an obvious alternative reading, propose it. Don't assert; offer. "Eine andere Lesart wäre …"
- **Rationalization flag**: if the entry frames a decision as "I did X because Y" and Y looks thin, name the gap. "Du sagst, du seist gegangen weil X. Aber im Text steht auch Y und Z. Vielleicht spielt das mit rein?"
- **Specificity over vibes**: every emotion claim cites a quote from the transcript. No generic emotional summaries.
- **Match Mindsera's structural rigor**: emotion-with-% + per-emotion evidence + Socratic question. We're not deviating from a working format.

### 9.3 Hard floor (harm reduction)

Citing MindfulDiary (CHI 2024) and MindScape (PMC 2024) clinical-context guidelines:

- **Never diagnose.** No DSM labels. No "you have anxiety." Use observation language: "der Text wirkt …".
- **Never escalate.** Don't dramatize. Don't pile on concerns the user didn't raise.
- **Crisis triage**: if the transcript contains explicit suicidal ideation, self-harm intent, or comparable crisis signals, the analyzer outputs a single short German message pointing to **Telefonseelsorge 0800-1110111** (free, anonymous, 24/7) and skips structured analysis. Implementer hard-codes this string; analyzer must not paraphrase or warm it up.
- **No sycophancy.** "You're so resilient" inflates mood readings and corrupts longitudinal tracking. Never produce unprompted compliments. Reflection is about clarity, not validation.

### 9.4 Tone summary

> Honest, warm, contrarian when warranted. Treats the user as a capable adult with blind spots. Pushes back without piling on. Doesn't therapize. Doesn't validate without evidence. The voice is closer to a sharp older friend than a therapist or a coach.

This phrase goes in JOURNAL.md verbatim.

---

## 10. Capture pipeline (live)

### 10.1 Trigger

Hermes Slack platform fires `file_shared` event in `#journal`. Two cases:

- **Top-level message** (no `thread_ts` or `thread_ts == ts`): new entry.
- **Thread reply**: append to existing entry whose Slack message_ts matches the thread parent. Maintain a small SQLite-or-JSON state file `journal-state.json` mapping `slack_message_ts` → `entry_path`.

### 10.2 Steps (per entry, top-level)

1. Download the audio file from Slack to `~/Downloads/journal-tmp/<slack-ts>.m4a`.
2. Compress to Opus: `ffmpeg -i <in> -c:a libopus -b:a 24k -ac 1 -ar 16000 raw/audio/<YYYY-MM-DD>-NNN.opus`.
3. Transcribe via Parakeet (`POST 127.0.0.1:8000/v1/audio/transcriptions`).
4. Build initial entry with placeholder frontmatter; transcript only, no analysis yet.
5. Run analysis: load JOURNAL.md + active prompt variant + transcript → Opus 4.7 → structured German output.
6. Parse analyzer output, populate frontmatter (mood, emotions, people, places, themes, slug).
7. Auto-create missing entity notes (`entities/<type>/<Name>.md` with skeleton frontmatter).
8. Generate cover image: extract two-line style+mood description from analyzer output → gpt-image-2 with fixed style suffix (see §12). Save to `_assets/covers/<YYYY-MM-DD>.avif`.
9. Write entry to `entries/<YYYY-MM-DD> — <slug>.md`. Append to `log.md`. Update `index.md`.
10. Symlink `raw/audio/<file>.opus` to `_assets/audio/<file>.opus` (for Obsidian embed).
11. Slack ack reply in the same thread (German):
    > ✓ Notiert: 2:34 min, Stimmung 6, Hauptemotion *Angst 35%*. Neu: [[Lisa]]. Eine Folgefrage: *was hättest du Lisa gesagt, wenn du dich getraut hättest?*

12. Save `slack_message_ts` → `entry_path` in `journal-state.json` for thread continuation.

### 10.3 Steps (thread reply)

1. Look up parent entry in `journal-state.json`.
2. Download + compress + transcribe new audio (steps 1-3 above).
3. Append new audio file to entry's `audio_paths` frontmatter.
4. Append `> [HH:MM]` segment to `## Transkript` section.
5. **Re-run analysis on the full combined transcript** — emotions/themes/etc. update based on the complete picture, not just the new segment. This is intentional; later memos often clarify earlier ones.
6. Update entry frontmatter and body sections with re-analysis output.
7. Append to `log.md`: `revise | added segment NNN`.
8. Slack ack reply (shorter): `✓ Ergänzt zur Stimmung-Analyse — neu in der Reflexion: …`.

### 10.4 Idempotency

- Slack file IDs are unique. Maintain a `processed_files.json` of seen Slack file IDs. Skip if already processed.
- Entries are immutable as a principle, but re-analysis on thread reply is allowed (it's the "complete picture" view). Manual edits by Johannes to entry body are also allowed; Hermes only auto-mutates entries when triggered by a thread reply.

---

## 11. Analysis pipeline (the prompt)

### 11.1 Inputs

The analyzer prompt is composed at runtime from:

1. **System prompt**: `JOURNAL.md` (the rules)
2. **User prompt template**: `prompts/<active-variant>.md` with substitutions for `{TRANSCRIPT}`, `{KNOWN_ENTITIES}`, `{PRIOR_ENTRY_CONTEXT}`.

### 11.2 Active variant

`v3-with-cbt-frame.md` is the expected winner of the eval. Until eval runs, default to `v1-baseline.md`. The active variant is recorded in entry frontmatter (`ingest_meta.prompt_variant`) so we can A/B over time.

### 11.3 Prompt template (German, `v1-baseline.md` shape)

```
Du analysierst einen Journal-Eintrag von Johannes. Befolge JOURNAL.md strikt.

Transkript:
---
{TRANSCRIPT}
---

Bekannte Entitäten (verlinke nur diese, alles andere wird neu angelegt):
- Personen: {KNOWN_PEOPLE}
- Orte: {KNOWN_PLACES}
- Emotionen: {KNOWN_EMOTIONS}

Vorheriger Eintrag-Kontext (kurz, optional):
{PRIOR_ENTRY_CONTEXT}

Liefere genau diese Struktur als YAML+Markdown:

```yaml
mood: <1-10>
slug: <3-6 wörter, kebab-case, deutsch>
emotions: [<emotion-name> (<%>), ...]
people: [<name>, ...]
places: [<name>, ...]
themes: [<thema>, ...]
```

## Zusammenfassung
<bullet-liste>

## Emotionen
- **<Emotion> (<%>)** — Beleg: "<zitat>"
...

## Reflexion
<cbt-style reframe, alternative lesart wenn sinnvoll, rationalisierungs-flag wenn passt>

## Folgefrage
<eine sokratische frage, deutsch>
```

`v2-anti-sycophancy.md` adds the §9.1 forbidden-phrases list inline plus 3 negative examples.
`v3-with-cbt-frame.md` adds explicit cognitive-distortion taxonomy (Schwarz-Weiß-Denken, Katastrophisieren, Gedankenlesen, Personalisieren) the analyzer must check against.

### 11.4 Known entities injection

Before each analysis call, the ingest script reads `entities/people/`, `entities/places/`, `entities/emotions/` and lists the filenames. The prompt instructs the analyzer to use exactly these names where applicable; new entities are explicitly allowed but flagged so the script knows to create skeleton notes.

### 11.5 Prior context injection

Optional. Pull the last 2 entries' frontmatter (mood, top emotion, themes) — not body — to give the analyzer continuity awareness. Helps catch recurring patterns ("Angst wieder Hauptthema, dritte Mal in Folge"). Keep token budget tight (~200 tokens).

---

## 12. Cover image generation

### 12.1 Pipeline

1. After analysis, take the entry's themes + dominant emotion + 1-sentence mood summary.
2. Render through a **fixed prompt template** (German or English — gpt-image-2 handles both):

```
A {STYLE_SUFFIX} cover image evoking the mood of a personal journal entry.
Mood: {MOOD_PHRASE}.
Themes: {THEMES}.
Composition: abstract-symbolic, never literal, no human faces, no text.
```

3. **Style suffix is fixed across all entries** for visual continuity. Default: `"oil painting in muted earth tones, painterly brushwork, soft natural light, slight grain, abstract composition"` — derived from Mindsera's existing covers (Johannes likes them).
4. Call gpt-image-2 at medium quality (~$0.05/image).
5. Re-encode PNG output to AVIF q=70: `avifenc --min 30 --max 50 in.png out.avif` (or via `ffmpeg -i in.png -c:v libsvtav1 -crf 35 out.avif`). Target: ~100 KB.
6. Save to `_assets/covers/<YYYY-MM-DD>.avif`. Set entry frontmatter `cover_image`.

### 12.2 Style reference seeding (one-shot, before going live)

- Pick 3-5 Mindsera covers Johannes likes most.
- Either: (a) describe their style in 1-2 sentences and use that as the suffix, or (b) pass them as image-input to gpt-image-2 with the prompt "match this style."
- Lock the suffix string in `journal/scripts/cover.py`. Don't randomize per entry.

### 12.3 Failure mode

If gpt-image-2 fails (rate limit, content policy, network), skip cover and log to `log.md`. Entry is still complete without one. Cover is not blocking.

---

## 13. Eval harness

The deliverable that proves the system works *before* it goes live.

### 13.1 Inputs

- 95 Mindsera entries at `~/Downloads/entries/<YYYY-MM-DD - <id>>/{entry.md, analysis.md}` — symlinked into `eval/ground_truth/`.
- Exported voice memos for the 95 + 15 pending → user provides path → symlinked into `eval/voice_memos/`.
- A matcher script (`scripts/match_voice_memos.py`) that pairs Mindsera entries to voice memo files by date. Output: `eval/pairs.json` mapping `<mindsera-id>` → `<voice-memo-path>`.

### 13.2 Two-axis scoring

**Axis 1 — Transcript quality** (Parakeet vs Mindsera STT):
- Run Parakeet on each voice memo.
- Compute character-level edit distance + semantic similarity (small model embedding cosine) between Parakeet output and Mindsera's `entry.md`.
- Aggregate stats per entry: `parakeet_wer_vs_mindsera`, `parakeet_semantic_cos`.

**Axis 2 — Analysis quality** (Hermes Opus vs Mindsera analyzer):
Two sub-conditions to disentangle:
- **Held-input**: run Hermes analyzer on Mindsera's `entry.md` (their text). Compare to Mindsera's `analysis.md`. Isolates analysis-prompt quality.
- **Full-pipeline**: run Hermes analyzer on Parakeet's transcript. Compare to Mindsera's `analysis.md`. Measures joint pipeline win.

### 13.3 Judge LLM

`judge.md` prompt sends the judge (Sonnet 4.6, blind) two analyses (ours and Mindsera's) for the same entry and asks it to score on:

| Axis | Description | Scale |
|-|-|-|
| `emotion_accuracy` | Are emotion-with-% claims supported by transcript evidence? | 1-5 |
| `reframe_quality` | Does the reflection propose a non-obvious alternative reading? Or just paraphrase? | 1-5 |
| `anti_sycophancy` | Does it avoid forbidden phrases? Does it push back when the entry is rationalizing? | 1-5 |
| `depth` | Surface-level vs genuinely insightful? | 1-5 |
| `german_quality` | Idiomatic, natural German vs translated-feeling? | 1-5 |

Judge output: JSON `{ours: {...}, mindsera: {...}, notes: "..."}`. Aggregate to `scorecard.json` per run.

**Bias mitigation**: randomize order (ours/mindsera) per call, judge doesn't know which is which. Use Sonnet 4.6 (different model than the analyzer Opus 4.7) to reduce self-evaluation bias.

### 13.4 Run shape

```bash
cd ~/SourceRoot/hermes-agent/journal/eval
python run.py --variant v1-baseline --condition held-input
python run.py --variant v1-baseline --condition full-pipeline
python run.py --variant v2-anti-sycophancy --condition held-input
python run.py --variant v3-with-cbt-frame --condition held-input
# ...
python compare.py runs/  # cross-variant comparison
```

Each run writes:
- `runs/<iso>--<variant>--<condition>/outputs/<mindsera-id>.md` — our analysis
- `runs/<iso>--<variant>--<condition>/scorecard.json` — judge scores aggregated

### 13.5 Acceptance criteria for going live

- v3-with-cbt-frame on held-input condition matches or beats Mindsera on **all five judge axes**, average ≥ 4.0/5.
- `anti_sycophancy` axis specifically must average ≥ 4.5/5 (this is the critical one; Mindsera tends to over-validate, we must clearly outperform).
- Manual spot-check: Johannes reads 5 random eval outputs, signs off qualitatively.

If criteria miss: iterate prompts (v4, v5…) or escalate to longer system prompts before declaring failure.

### 13.6 Implementation

`run.py` ~250-400 lines Python. Uses `claude -p` subprocess for each call (subscription-backed, fresh-context per call). Concurrency: 4-8 parallel calls via `asyncio` + subprocess. Rate-limit: respects subscription's 5-hour rolling cap; resume from checkpoint if interrupted.

Use `claude -p --model claude-opus-4-7 < prompt.txt` for analysis; `claude -p --model claude-sonnet-4-6 < judge-prompt.txt` for judging. Pipe captured stdout to output files. State in `eval/state.json` so re-runs are resumable.

If subscription rate-limits, fallback: same code with `ANTHROPIC_BASE_URL=$IU_BASE_URL ANTHROPIC_API_KEY=$IU_KEY` swap to direct SDK against IU. Implementer should make this a one-flag switch.

---

## 14. Storage, sync, backup

### 14.1 Storage

- All journal data (text + binaries) under `~/Obsidian/Vault/Journal/`.
- Audio: Opus, ~180 KB/min, ~50 entries/year × 5 min = ~45 MB/year audio.
- Covers: AVIF, ~100 KB each, ~50/year = ~5 MB/year.
- Text: trivial.
- **Annual journal data ≤ 100 MB.** Vault bloat is not a concern.

### 14.2 Sync (LiveSync)

Existing CouchDB Self-hosted LiveSync handles all of `~/Obsidian/Vault/`. No config changes needed for journal data — it's already inside the vault.

**Recommended LiveSync settings to verify before launch:**
- Settings → Sync Settings → "Sync attachments" enabled
- Settings → Sync Settings → "Compress binary files" enabled (gzip on small AVIFs is harmless, marginal win)
- Settings → Sync Settings → "Batch database update" enabled
- Test: drop a 1 MB test file in `Journal/_assets/test.opus`, confirm appears on iPhone within seconds, then delete.

### 14.3 Backup

Two layers:

1. **Restic → Backblaze B2** (existing): verify `~/Obsidian/Vault` is in restic includes. Add it if not.
2. **rsync → homelab** (new): extend `~/SourceRoot/hermes-agent/scripts/hermes-backup.sh` with:
   ```bash
   rsync -avz --delete ~/Obsidian/Vault/ homelab:/mnt/hdd/Dokumente/Obsidian/
   ```
   Confirm the homelab destination path exists; create if not.

Both run daily at 03:00 via the existing macOS crontab pattern. Pings UptimeKuma on success per `$UPTIME_PUSH_BACKUP`.

---

## 15. Phase plan

Phases are sequential. Each ends with a hard checkpoint.

### Phase 0 — DONE

Decisions locked. See §5.

### Phase 1 — Vault skeleton + JOURNAL.md (no automation)

**Status:** DONE 2026-05-05 (artifacts only — vault skeleton deferred to Phase 3).

**Deliverables:**
- ~~Create `~/Obsidian/Vault/Journal/` with the §7 directory structure (empty `entries/`, `entities/`, etc.).~~ **Postponed to Phase 3** — no point creating the vault tree before the eval has picked a winning prompt variant. Path also changed: target is `~/Obsidian/Vault/01_Journal/` to fit existing PARA structure (empty `01_Journal/` already exists).
- ~~Write `JOURNAL.md`~~ — DONE at `journal/JOURNAL.md` (repo). Moves to `~/Obsidian/Vault/01_Journal/JOURNAL.md` on Phase 3 cutover.
- ~~Write `prompts/v1-baseline.md`, `v2-anti-sycophancy.md`, `v3-with-cbt-frame.md`~~ — DONE under `journal/eval/prompts/`.
- ~~Write `judge.md`~~ — DONE at `journal/eval/judge.md`.

**Deviations from PRD v1 (intentional, signed off):**
- §9.3 crisis-triage block (Telefonseelsorge) removed from JOURNAL.md. Johannes does not want therapy-style guardrails — system designed for an emotionally healthy adult journaler. `Keine Diagnose` and `Keine Eskalation` rules retained because they serve reflection quality.
- No mentions of the IU endpoint or Johannes's employer in any journal artifact (prompts, judge, code). PRD still references IU openly — this is internal-planning-only.
- YAML emotion shape changed from `Angst (40%)` strings to `{ name: Angst, pct: 40 }` structured for parse-robustness.
- Added explicit `new_entities` block to analyzer YAML so the ingest script doesn't have to diff against KNOWN_* lists.
- Reflexion section capped at one Socratic device per entry (alternative reading OR disproportion check OR rationalization flag OR named cognitive distortion) — prevents CBT-bot drift.

**Acceptance:** Johannes read JOURNAL.md + the three prompt variants + judge.md and signed off on tone. ✓

### Phase 2 — Eval harness + Mindsera backfill

**Status:** PAUSED at pre-execution recon 2026-05-13. Postponed by Johannes. Resume by re-reading §15a below + answering the four open questions.

**Deliverables (unchanged from v1):**
- `journal/scripts/match_voice_memos.py` — pair Mindsera entries to exported voice memos.
- `journal/scripts/compress_audio.sh` — Opus encoder.
- `journal/eval/run.py` — eval harness with two-axis scoring.
- Run all variants × both conditions on the 95 Mindsera entries.
- Generate `scorecard.json` per run + a cross-variant comparison report.

**Acceptance:** §13.5 criteria met. Winning variant identified. (See §15a-3 for proposed amendment to acceptance criteria based on recon findings.)

### Phase 3 — Live capture (Slack `#journal`)

**Deliverables:**
- `skills/journal-ingest/SKILL.md` — Hermes skill.
- `journal/scripts/ingest.py` — the live pipeline (§10).
- `journal-state.json` — Slack-message-ts → entry-path mapping.
- Process the 15 pending iPhone memos through the live pipeline as a test batch.

**Acceptance:** record a memo on iPhone → Slack `#journal` → entry appears in Obsidian within 60s with full analysis + cover. Thread reply correctly continues an entry. Repeat 3 times across 2 days without intervention.

### Phase 4 — Bases dashboards

**Deliverables:**
- Three Bases views in `Journal/`:
  - **Stimmung über Zeit** — line chart, mood vs date.
  - **Personen-Häufigkeit** — table, top entities by mention count, last-seen.
  - **Themen-Drift** — themes appearing this month vs prior 3 months.

**Acceptance:** all three render correctly on iPhone Obsidian (LiveSync delivered).

### Phase 5 — Monthly roll-up

**Deliverables:**
- Hermes cron job: first Sunday of month, 18:00 Europe/Berlin.
- Pre-run script `journal-month-context.py` aggregates last month's entries + frontmatter.
- Cron prompt produces `analysis/monthly/<YYYY-MM>.md` + Slack `#journal` post (audio via Fish S2 Pro DE narration optional).

**Acceptance:** runs cleanly on first Sunday after launch. Produces the file. Posts to Slack.

### Phase 6 — Backup gap

**Deliverables:**
- Verify vault in restic includes (one-line check).
- Extend `scripts/hermes-backup.sh` with rsync to homelab.
- Verify homelab destination exists or provision it.

**Acceptance:** next day's 03:00 backup pushes vault to homelab successfully. UptimeKuma pings.

---

## 15a. Phase 2 pre-execution recon (2026-05-13)

Done before any code was written. Captures what `~/Downloads/entries/` actually looks like and where PRD v1 assumptions broke. **Read this before resuming Phase 2.**

### 15a-1. Corpus shape

| Aspect | Reality |
|-|-|
| Total entries | 95 (confirmed) |
| Date range | 2025-09-27 → 2026-01-16 (~3.5 months) |
| Same-day entries | 4 on 2025-09-27, 2 on multiple other days — confirms PRD §5.13 decision to honor Mindsera's per-entry split |
| **First 4 entries (all 2025-09-27)** | **English Q&A**, Mindsera onboarding flow ("Hi Jo, Welcome to Mindsera…"). Not voice memos. Interleaved Mindsera prompts + Johannes's typed (?) replies. |
| **From 2025-09-28 onward** | German voice-memo monologues — clean single-paragraph STT transcripts |
| Mindsera analysis structure | `**Summary:**` bullets + `**Emotional State:**` (per-emotion paragraph with quote evidence). **No reflection section. No Socratic question. No mood number. No themes/people/places metadata.** |
| Mindsera analysis language | Mixed: `**Summary:**` matches entry language. Emotion labels always English (`Anxiety`, `Sadness`, `Hope`). Per-emotion evidence in English with German quotes embedded when source is German. |

### 15a-2. Open design questions (need Johannes call before resuming)

1. **Drop the 4 onboarding English entries from the eval pool?** They're not voice memos and the format is alien. Tendency: drop them, leave readable as historical context. 91 German entries is plenty for statistical power.

2. **Voice memo export path.** PRD §16.1 said Johannes will export. Still pending. Options: `~/Downloads/voice-memos/` dump, AirDrop-watched inbox, or pre-existing location. Format determines matcher logic — `Recording NNN.m4a` (mtime-keyed) vs `2025-09-28 14:32 Memo.m4a` (filename-keyed) differ.

3. **Asymmetric axis problem.** `reframe_quality`, `depth`, and `german_quality` favor Hermes-Opus on virtually every entry by *structural* definition — Mindsera doesn't do reflection, Socratic prompting, or German output. The real contest narrows to `anti_sycophancy` and `emotion_accuracy`. Tendency: keep all 5 axes, but **promote `anti_sycophancy ≥ 4.5/5` from "additional criterion" to the load-bearing acceptance gate** (replacing the "average ≥ 4.0/5 on all five axes" criterion in §13.5). The other three become bonus signal.

4. **judge.md needs a section-absent calibration line.** If Mindsera's analysis has no Reflexion / no Folgefrage, the judge must score `reframe_quality = 1` and `depth = 1` rather than "n/a" (which would inflate Mindsera's average). Add one explicit line to judge.md when resuming.

### 15a-3. Proposed Phase 2 sub-step order (signed off before pause, not yet executed)

| # | Step | Output |
|-|-|-|
| 1 | Voice memo recon (after path given) | format report, mtime sanity-check |
| 2 | `match_voice_memos.py` | `eval/pairs.json` (`<mindsera-id>` → `<voice-memo-path>`) + conflict report (orphan memos, orphan entries) |
| 3 | `compress_audio.sh` | one-liner Opus encoder, callable from matcher + ingest |
| 4 | Parakeet STT batch | `eval/transcripts/<mindsera-id>.txt` per paired entry |
| 5 | `run.py` skeleton | resumable harness with checkpoint state, `claude -p` subprocess pool |
| 6 | Tighten judge.md (section-absent calibration per §15a-2.4) | small edit |
| 7 | Execute eval matrix | `runs/<iso>--<variant>--<condition>/` per run |
| 8 | `compare.py` | cross-variant report |

### 15a-4. Resume protocol

When Phase 2 resumes:
1. Re-read §15a-1 through §15a-3.
2. Get answers to the four questions in §15a-2.
3. Start at step 1 of §15a-3.
4. Cross-reference `~/.claude/projects/-Users-jkrumm-SourceRoot-hermes-agent/memory/` for the two journal feedback memories (no crisis framing, no employer mentions).

---

## 16. Open questions / risks

1. **Voice memos on Mac sandboxed.** Johannes will export. Implementer should accept any export folder path as a CLI flag (`--memos-dir`) and not hard-code.
2. **Mindsera STT quality**: entries READ as clean prose. Confirm whether Mindsera transcribed his speech (probably yes, he confirmed) vs whether he ever typed corrections. Affects how much we trust Mindsera as transcript ground truth. If their STT is genuinely worse, our Parakeet transcript may diverge — that's expected and good.
3. **gpt-image-2 content policy**: emotional/dark journal entries may trigger refusals. Implementer should catch refusal responses and either retry with abstracted-mood-only prompt or skip cover entirely.
4. **Subscription rate limits**: 95 entries × 3 variants × 2 conditions × 2 calls (analyze + judge) = ~1140 calls. Plus retries. May hit 5-hour rolling window. Plan for resumable runs. IU SDK fallback as the escape hatch.
5. **Entity disambiguation**: multiple "Anna"s would collide. v1 uses last-name disambiguation only when analyzer flags ambiguity. Long-term concern, not v1 blocker.
6. **Slack message_ts persistence**: `journal-state.json` lives outside the vault (won't sync). Place it at `~/.hermes/journal-state.json` to align with existing Hermes state files.
7. **LiveSync mobile**: confirm binary sync actually works on iPhone with our specific volume before investing in covers/audio. Quick test in Phase 1.

---

## 17. References

- **Karpathy LLM Wiki pattern**: https://gist.github.com/karpathy/442a6bf555914893e9891c11519de94f
- **Anti-sycophancy research**: Anthropic ICLR 2024 https://www.anthropic.com/research/towards-understanding-sycophancy-in-language-models
- **SycEval**: https://arxiv.org/abs/2502.08177
- **CBT-Bench**: https://aclanthology.org/2025.naacl-long.196/
- **MindfulDiary** (CHI 2024): https://dl.acm.org/doi/10.1145/3613904.3642937
- **MindScape** (PMC 2024): https://pmc.ncbi.nlm.nih.gov/articles/PMC11275533/
- **clairefro/obsidian-chat-cbt-plugin** (reference only, NOT used as plugin): https://github.com/clairefro/obsidian-chat-cbt-plugin
- **silverstein/minutes** (entity-extraction pattern reference): https://github.com/silverstein/minutes
- **gmirabella/voice-to-obsidian-ai** (pipeline reference): https://github.com/gmirabella/voice-to-obsidian-ai
- **gpt-image-2 docs**: https://developers.openai.com/api/docs/models/gpt-image-2
- **Obsidian Bases**: https://help.obsidian.md/bases (core feature since Aug 2025)
- **Obsidian LiveSync**: https://github.com/vrtmrz/obsidian-livesync
- **Parakeet TDT v3**: https://huggingface.co/nvidia/parakeet-tdt-0.6b-v3
- **Hermes Agent docs**: this repo's README.md and `~/.hermes/` runtime
- **Mindsera export**: `~/Downloads/entries/`

---

## 18. For the implementing agent — quick start

1. Read this PRD completely.
2. Confirm voice memo export path with Johannes (he'll dump them in a folder you can read).
3. Start with **Phase 1** — write JOURNAL.md, the 3 prompt variants, judge.md. **No code yet.** Stop and ask Johannes to review.
4. Only after Phase 1 sign-off, move to Phase 2 (eval harness). Do NOT skip the eval — it's the credibility gate for the whole system.
5. Use `claude -p` for the eval harness (subscription-backed). If subscription rate-limits, swap to IU SDK with the existing pattern.
6. For implementation work *itself* (writing scripts, editing files), use the user's Claude Code session — that's already covered by their subscription.
7. Hermes coding conventions live in `~/SourceRoot/hermes-agent/CLAUDE.md`. Personal coding conventions in `~/.claude/CLAUDE.md`. Read both.
8. Commit per Hermes-Agent convention (direct-to-master, see §"Direct-to-master repos" in `~/SourceRoot/CLAUDE.md`).
9. When in doubt, ask Johannes. He prefers small steps + frequent checkpoints over autonomous big-bang work.

End of PRD.
