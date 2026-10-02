---
name: dispatch-brief-authoring
description: "Use when writing a Warden/sideclaw episode brief."
version: 1.0.0
metadata:
  hermes:
    tags: [dispatch, sideclaw, warden, brief, episode, implement, investigate, review, verification]
    related_skills: [claude-dispatch, warden-auto-implement-chain, warden-blocked-items, agent-claim-verification]
---

# Authoring a dispatch brief

The brief is the only part of an episode you control, and it is the part that decides
whether the episode lands the change you meant. It is **data, never argv**
(`--brief-file`, or a quoted heredoc on stdin; there is no `--brief`).

The verbs, tiers, ceilings, origin flags and the approval door are `claude-dispatch`.
Reading an item back is `warden`; watching it is `warden-item-watch`; verifying what an
episode claims is `agent-claim-verification`. **This** skill is the text itself.

## What each stage actually receives

- `run <repo>` opens an **item** and briefs the **investigate** stage. Your brief's
destination is the investigation.
- If that investigation's verdict reads `nextAction: implement` at `confidence: high`
  and the item's `max_tier` is `implement`, the loop opens the implement episode
  **itself** — with a *fixed generic brief* ("a prior read-only investigation already
  concluded, at high confidence… re-read that investigation's own verdict") plus
  `context = <the investigation verdict>`: `summary`, `verdict`, `evidence`,
  `recommendation`, `confidence`, `nextAction`, truncated at `MAX_CONTEXT_CHARS`
  (16 000). A second episode you arm to fix a blocked validation is briefed normally.

**So everything the implementer needs must be inside the investigation's VERDICT.** A
file:line, an empirical case, a required contract, the acceptance criteria: write the
`run` brief so the investigator reproduces that detail. A one-line intake brief yields a
one-line verdict and an under-specified fix, and later narration does not recover it.

**Confirm what actually arrived** before diagnosing an episode's choices: the job
store, not the job API. `~/.local/share/sideclaw/jobs.db` → the job's `params` JSON →
`context` (and `worktree_meta` → `base` / `baseRef`). The API exposes neither, so a
truncated or empty context is invisible from `GET /api/jobs/<id>`.

## The worktree is cut from the default branch

An `implement` episode gets a fresh worktree cut from the repo's **default branch**,
pushed to a new `dispatch/…` branch. There is **no base-branch input** anywhere in the
handler. Two consequences:

- An episode told to "fix the blocked PR's branch" cannot base on it unless it fetches
  and cherry-picks it itself. Ask for that explicitly — `git fetch origin <branch>`, then
  cherry-pick or merge it onto your branch — or the episode silently re-derives the
  change from master and you get a **superset** PR instead of a follow-up commit.
- A superset PR obsoletes the one it replaced. Verify the supersession with
  `git diff origin/master...origin/<new-branch> --stat` against the old branch, then name
  the **single** PR to review: two open PRs carrying the same change is the trap.

## What the brief must carry

1. **The finding, quoted verbatim, with file and line.** Paraphrasing a review finding
   is how detail is lost between the review and the fix.
2. **Your own reproduction**, when you verified it: the literal input, the sizes, the
   observable result. Numbers you measured cost the episode nothing and pin the target.
3. **The direction, when the naive reading of the finding is wrong.** If a finding reads
   as "make the check stricter" but you measured that a stricter threshold cannot
   separate the classes, say so and give the contract change instead — otherwise you get
   the tweak you already disproved.
4. **The related findings from the same review** (its test gaps especially): same result
   object, cheapest part of the round, and they are usually the cases that would have
   caught the defect.
5. **An escape hatch**: "if the finding turns out not to hold on re-reading, say so in
   your verdict and stop rather than forcing a change." Without it, the path of least
   resistance is always to change something.
6. **Acceptance as commands** — the repo's own test / typecheck / lint target names, plus
   the new cases, stated as the commands *you* will re-run. An episode's "green" is a
   self-report, and `bun test`/`tsc` in a throwaway worktree is the evidence.
7. **Scope boundaries**: which branch/PR/issue this is and what is explicitly out of it.
   A brief with no boundary invites the episode to widen the diff.

## Verify before you brief

- **Reproduce the finding yourself first.** A claim of the shape "this pattern also
  matches ordinary cases" is checkable in one command: pull the literal out of the
  branch (`git show <sha>:<file>`) and run the claimed cases through the repo's own
  runtime. Reproducing it also surfaces the cases the review *missed*, which is what
  makes the brief complete rather than a restatement.
- **Read the review in full from the job store, not the card.** The card truncates the
  message at a prefix. `~/.local/share/sideclaw/jobs.db` → `result`: `outcome`,
  `blocking[]` (`file` / `line` / `message` / `angle`), `testGaps[]`, `improvements[]`,
  `discussions[]`. You cannot brief a finding you have only read a prefix of.
- **When probing a guard for a defeat class, hold every invariant it checks SATISFIED.**
  A probe case that leaves a checked invariant violated exercises that check instead of
  the hole: it comes back rejected and reads as "the class is closed". Vary only the
  dimension you suspect is unchecked. Your own probe is the weakest evidence in the
  chain precisely because you chose its cases — a review that then finds your missing
  case is not the review being unfair.

## Pitfalls

- **Do not promise a merge you cannot make.** A repo absent from
  `config/triage-policy.json`'s `repos` map has no `autoMergePaths` and can never
  auto-merge, however clean the validation. Say handmerge, not "it will land".
- **Don't brief a fix you cannot name.** If you cannot say which file and which line,
  the stage to open is investigate, not implement.
- **One item, one episode per stage.** Check `/board` for the repo before opening
  anything; a duplicate burns a session for the same answer.
- **A block is not proof your brief failed.** Re-read the live item and the review's
  blocking findings before rewriting; the same defect class blocking twice usually means
  the *direction* was wrong, not the wording.
