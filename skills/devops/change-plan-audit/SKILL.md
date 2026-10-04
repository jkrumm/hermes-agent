---
name: change-plan-audit
description: Use when auditing a machine-written change plan.
version: 1.0.0
metadata:
  hermes:
    tags: [audit, plan, issue, brief, coverage, lockfile, manifests, warden, dispatch]
    related_skills: [defect-report-verification, github-issues, warden, claude-dispatch]
---

# Change-plan audit — is the plan's inventory complete, not just its claims right

A machine-written change plan (a generated GitHub issue, a Warden brief, an
author-tier artifact) arrives as prose plus a **list of edits**: a table of
`specifier → exact version`, a set of files to touch, a list of call sites. It
was written by something that read the repo once, and it is about to be handed
to an episode that will implement exactly what it lists — no more.

`defect-report-verification` owns *is the defect real and does the fix work*.
This skill owns the other half: **does the plan's inventory actually cover the
live tree?** A plan can be right about every row it lists and still leave the
job half done, and the omission is invisible in the plan itself.

## Procedure

1. **Read the plan whole, then extract its inventory mechanically.** Do not
   eyeball the table — parse it, because the interesting finding is a row the
   table does *not* have. Split the body per file/section first (a heading like
   `### <path>` then that section's table), so two sections listing the same
   package under different current versions stay separate:

   ```python
   sections = re.split(r'^### ', body, flags=re.M)
   rows = re.findall(r'^\|\s*`([^`]+)`[^|]*\|\s*`([^`]+)`\s*\|\s*`?\**([^|`*]+?)\**`?\s*\|\s*$', section, re.M)
   ```

   Keep the plan's own columns (`current`, `target`) — both get checked below.
2. **Diff the plan against the live tree, in three directions.** Every listed
   item is only one of the findings:
   - **offenders the plan omits** — walk the live manifests/config and collect
     every item that violates the stated rule but has no row. This is the
     finding worth reporting.
   - **rows for things that no longer exist** — a package removed from the
     manifest since the plan was written.
   - **rows whose `current` column is stale** — the live specifier has moved.
     Report the drift; do not "fix" the plan's wording silently.
3. **Validate every target against ground truth, not against the plan.** The
   lockfile's resolved map is the authority for what a version specifier
   actually resolves to; parse it rather than trusting either column:

   ```python
   resolved = set(re.findall(r'"%s": \["%s@([^"]+)"' % (pkg, pkg), lock_text))
   ```

   A target that appears nowhere in the resolved map is either a version that
   changes the resolved tree (flag it as the one row that is not a no-op) or a
   version the plan invented. Say which.
4. **Separate the no-op rows from the behavioural ones.** When the change is
   "pin to the currently resolved version", almost every row is text-only and a
   frozen-lockfile CI makes it a no-op at install time — but the rows that
   *change* the resolved version are the only ones that can break a build, and
   they deserve their own line in the report.
5. **Check the plan's own verification section against what you can run.** If it
   says "run install once and confirm the lockfile is unchanged", that is the
   acceptance test — name it, and note whether the plan's author ran it.
6. **Report: verdict first, then the omission, then the rest.** Lead with
   whether the plan is complete enough to implement as written. The omission is
   the actionable line; the stale row is a footnote.

## Pitfalls

- **A plan's inventory is the weakest part of it, and it never announces the
  gap.** Generated plans are built from what the author happened to read, so a
  whole file or a whole class of offender can be missing while every listed row
  is correct. Always re-derive the offender set from the live tree; never treat
  the plan's row count as the scope.
- **Commenting on an ingested issue does not reach the episode.** Warden stores
  the issue body as the item's `brief` at ingest; the episode reads that stored
  text, not the issue as it stands when the job starts. A correction posted as a
  comment is invisible to the implementer — say so, and route the correction to
  a human or a fresh item instead of assuming the comment landed.
- **Do not open a second dispatch for an item that already has one.** Check the
  item's state and its job before proposing work; a duplicate episode burns a
  session for an answer you already have. Reading the item is `warden`; the
  queue and the job's real status are `dispatch-liveness-verification`.
- **The plan's target and the plan's `current` column can disagree with each
  other and with the tree.** Three sources, three answers — resolve them against
  the lockfile and the manifests and report the disagreement rather than picking
  the one that reads best.
- **A listed item that is already correct is not a finding.** A plan that lists
  a row for something already pinned, or a package no longer depended on, has
  drifted from the tree; that is a plan-quality note, not work.
