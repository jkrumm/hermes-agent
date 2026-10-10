# Writing to the vault

Loaded from `SKILL.md` — read before editing any note under `Areas/Gaming/Wild Rift/`.

## Writing to the vault

Follow the **`obsidian`** skill's access model exactly: **CLI first**
(`obsidian version` is the liveness gate), filesystem fallback only when
Obsidian.app is down. Load `skills/obsidian/SKILL.md` before writing.

**Pull before writing** — `git -C ~/SourceRoot/brain pull`. The MacBook writes
to this vault too.

**These are curated pages, so lint is light** — dead links only, no forced
`type`/`description`. **One exception applies here:** every champion note
declares `type: champion`, and the lint enforces that any note declaring it
keeps `patch`, `statDate` and `heroId`. Those are the keys you read; dropping
one on a refresh is an error, not a warning. Preserve the whole frontmatter
block when rewriting a section.

**Two opposite pipe rules — both bite silently.** A `|` inside a table cell is a
column separator, so:

| Construct | In a table cell | Why |
|-|-|-|
| Aliased wikilink | **Don't use it.** `[[note\|Alias]]` | Even escaped, it fails the vault linter's wikilink parser. Use a plain bold name and link outside the table |
| Sized image | **Must escape:** `![\|28](url)` | Unescaped `![\|28]` splits the cell — the image vanishes and the table silently gains a phantom column |

Both failures are invisible in the diff and only show up when the note renders.
Check a table by rendering it, not by reading it.

**Stats live in four places — update all of them.** Each champion note carries
its numbers in frontmatter (`winRate`, `pickRate`, `banRate`, `statDate`) *and*
in its per-rank table; the summary row is in `Wild Rift.md`; the pool table is
in `Draft Guide.md`. Miss one and the pages disagree with each other. (A
Dataview block would remove this quadruple-write, but it was deliberately not
used — it doesn't render outside Obsidian, which matters for phone read-access.)

**Keep one snapshot date across the whole pool.** The comparison tables in
`Wild Rift.md` and `Draft Guide.md` are only honest if every row was pulled the
same day. If you refresh one champion's numbers, either refresh all of them or
leave the comparison tables alone and say the note is now ahead of them.

**Validate — 0 errors required:**
```bash
node ~/SourceRoot/brain/.scripts/vault-lint.mjs
```

**Icons are remote, never local.** Item, rune, spell and champion art live at
`https://img.jkrumm.com/blog/wildrift/{items,runes,spells,champions}/<slug>.webp`
(champion art is `.png`). The slug is the name lowercased with all non-letters
stripped — `Dead Man's Plate` → `deadmansplate`. Use the full name:
`tearofthegoddess`, not `tear`.

Request **one rendition per icon** and size in Obsidian, rather than minting a
CDN variant per display size:

```
![\|28](https://img.jkrumm.com/rs:fit:96/f:png/blog/wildrift/items/thornmail.webp)
```

`rs:fit:96` for icons, `rs:fit:144` for champion art. **`f:png` is required** —
the CDN defaults to JPEG, which turns icon transparency into a black box.
**Never download an image into the vault.** If a build gains an item with no
mirrored icon, write the item name as plain text and say so in the reply — do
not invent a URL, it will 404 silently. Adding a new icon to the CDN is a
Claude Code job, not yours.

**Commit after writing, through the helper.** It takes brain-sync's lock (so the
commit never races the 5-minute sync for `.git/index.lock`), commits naming the
vault (so the commit is unambiguous among the repos on this box) — and pushes,
fail-soft:
```bash
~/.hermes/scripts/brain-commit.sh "wildrift: refresh Hecarim build (patch 7.2b)" "Areas/Gaming/Wild Rift"
```
Exit 3 = the lock was busy, nothing committed — retry in a minute. Don't compose
your own `git push`; the helper (and the sync LaunchAgent) own that.
