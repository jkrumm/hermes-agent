# Workflows

Loaded from `SKILL.md` — the five question types and how to answer each.


## "what should I ban?" / "was soll ich bannen"

Read-only, answer from the vault. **`Draft Guide.md` has the ban table** — read
that first; it maps pick → ban with the reason. The per-champion notes carry the
same ban in their own ban note.

The short version, which you should still verify against the guide rather than
reciting from here: Morgana covers three of the four supports, Olaf covers both
Rammus and Nunu, Poppy is the Hecarim ban, Lee Sin the Shyvana/Gragas ban, Yasuo
the mid ban for both Ahri and Galio.

Ask which champion he's planning to play if it isn't obvious — the ban depends
on the pick.

## "what do I pick into X?" / "was picke ich gegen AP"

**`Draft Guide.md`** is built for this. It has a decision chain per role and a
"when they're banned" table. Read the chain, give the pick and the one-line
reason, and don't recite the whole guide.

## "how do I play X into Y?" / "wie spiele ich X gegen Y"

Vault-first. Read the matchup table in the relevant champion note. Each row
carries a *read* — the actual instruction, not just a verdict. Quote that.

Only reach for `research-gateway` if the note has no row for that matchup, and
say plainly that you're going outside the notes.

## "refresh my `<champ>` build" / "baue mir den X build neu"

1. Read the note: `obsidian read path="Areas/Gaming/Wild Rift/<Champ>.md"`. Note
   its `patch:` frontmatter field.
2. Establish the current patch via `research-gateway`. If it matches the note,
   say so and stop — don't churn the vault for nothing.
3. If the patch moved, research what changed for that champion and what the
   current core build is.
4. Rewrite only the build/rune section. Update the `patch:` and `timestamp:`
   frontmatter. Don't blow away matchup tables — those are hand-written
   judgment and rarely move with a balance patch.
5. Lint (0 errors), then commit naming the vault.
6. Reply with the delta: what changed and why. If nothing material changed, say
   that instead of manufacturing a diff.

## "did the new patch change my builds?" / "hat das Update meine Builds beeinflusst"

Same as above but across the pool. Read each note's `patch:` field, ask
`research-gateway` for the current patch and its champion changes, and report
which champions are actually affected. Only write to notes that genuinely moved
— a balance patch usually touches one or two, not eleven.

**Eleven notes is past the size of a comfortable in-conversation refresh.** If
the patch moved most of the pool, or changed the item system the way 7.2 did,
say so and tell Johannes it wants a Claude Code session in `brain` rather than
grinding it out yourself. Doing two or three notes and reporting honestly beats
half-updating eleven.
