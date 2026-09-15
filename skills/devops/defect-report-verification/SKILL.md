---
name: defect-report-verification
description: "Use when verifying a defect report before relaying it."
version: 1.0.0
metadata:
  hermes:
    tags: [verification, defect, verdict, reproduction, warden, triage, claims]
    related_skills: [hermes-log-alert-forensics, warden-digest-triage, warden, claude-dispatch, systematic-debugging]
---

# Defect report verification

A defect report — a Warden verdict, a `human:*` brief, a log-derived alert, a
colleague's bug write-up — is a **claim**, not a finding. It arrives with a
mechanism and a proposed fix, both written by something that did not have to be
right. Relaying either without checking is how a plausible-but-wrong fix reaches
a patch file, a PR, or the user's plan for the day.

The triage skills own *discharging* an item (`hermes-log-alert-forensics`,
`warden-digest-triage`). This skill owns *verifying* the claim inside it, and it
applies to any defect report, not just Warden's.

## Procedure

1. **Read the claim whole before touching anything.** The brief carries the
   mechanism and the fix; the verdict summary often carries the real finding.
   Note the two separately — they fail independently.
2. **Establish the live state of the artifact the claim names.** Does the store,
   ledger, index, database or directory still show the condition? Three answers,
   and they are not interchangeable: **live** (reproduces now), **latent**
   (condition gone, defect still in the code), **cleared** (the affected data was
   repaired). Say which one you found.
3. **Reproduce in a throwaway directory, never in the live tree.** `mktemp -d` +
   `execute_code`, or a scratch clone. The reproduction must show the claimed
   failure mode, not a lookalike — same error text, same exit code, same step.
4. **Reproduce the FIX too, not just the bug.** Apply the proposed remedy in the
   same scratch reproduction and confirm recovery (the operation succeeds, the
   artifact is correct afterwards). A reproduced bug does **not** validate a
   proposed fix; most briefs get the bug right and the fix subtly wrong.
5. **Attack the fix's predicates against edge cases.** The discriminating probe
   is where a brief is most often wrong, and a wrong probe is worse than no fix:
   it mutates state, then still fails. Test the probe against a control instance
   of *each* class it must separate — the broken one and the valid-but-unusual
   one — before trusting it.
6. **Check whether any tier can land the fix before offering a dispatch.** Read
   the per-repo ceiling in both copies (Warden's `config/dispatch-repos.json` and
   sideclaw's `GET /api/dispatch-policy`). A repo capped at `investigate` produces
   another verdict, never the change — say that plainly instead of offering a
   `run` that cannot land.
7. **Report: verdict first, then what you verified, then what you did not do.**
   Separate "condition cleared" from "defect fixed" in the wording. Name the
   ceiling when it blocks the fix.

## Pitfalls

- **A diagnostic run inside the same hijacked environment as the failure is not a
  diagnostic.** When a tool shells out with a redirected environment (git under
  `GIT_DIR`/`GIT_WORK_TREE`/`GIT_INDEX_FILE`, a CLI under a pinned config path),
  every probe you run with that same environment resolves to the redirected
  target — so all instances look identical and the probe discriminates nothing.
  Strip exactly those variables for the probe (`env -u GIT_DIR -u GIT_WORK_TREE
  -u GIT_INDEX_FILE …`) and keep the redirected env only for the operation under
  test. The module usually already has the list — reuse it rather than
  hand-writing one.
- **Pick the probe that tests the property you need, and prove it on both
  classes.** "Is this a repository" and "does this repository resolve" are
  different questions with different exit codes: a valid-but-commitless nested
  repo answers 128 to `rev-parse --verify HEAD` and 0 to `rev-parse --git-dir`.
  A probe that cannot separate the broken case from the unusual-but-valid case
  will classify healthy data as garbage and destroy it. Always verify the probe
  against a known-good instance and a known-broken one before wiring it into a
  fix.
- **A cleared condition is not a fixed defect.** A defect that stops firing
  because an external actor finished its work — a cleaner sweep, a temp file
  finally deleted, a directory removed — is still latent in the code and re-fires
  on the next identical condition. Recoveries that happen by accident are the
  hardest to notice: compare the timestamp of the last *successful* operation
  against the last error before concluding anything self-heals. Report "condition
  cleared, defect latent".
- **The same defect can arrive as two items at once.** A log-derived row and a
  hand-filed brief describing one defect are two rows with two dispatches. Read
  the board before triaging a card as new work, and name the duplicate.
- **Verify against the live checkout, and know which checkout that is.** For
  `hermes-agent`: `~/.hermes/hermes-agent/` is the upstream git checkout the
  patches apply to; `~/SourceRoot/hermes-agent/` is the local config/skills repo
  with **no** upstream remote and a different git history. Reading a file from one
  and running git in the other produces nonsense — including a `git status` that
  silently reports a scratch directory because a leaked `GIT_DIR` was still
  exported in the shell.
- **A fix that keys on git's stderr text must not key on its English text.** Git
  localizes its diagnostics, and the checkpoint store runs under the host's locale:
  the wedge that fired on this machine reads `Schwerwiegend: 'x/.git' nicht als
  Git-Repository erkannt`, not `fatal: 'x/.git' not recognized as a git repository`.
  A brief that specifies matching the English sentence produces a recovery that
  silently never fires here — the failure mode is indistinguishable from the bug.
  Test for the *token* the message must contain (a `.git` in stderr) rather than the
  sentence around it, and confirm the guard is narrow by checking an unrelated
  failure of the same command does not trip it.
- **A fix to a capped repo is a patch file, not a dispatch.** Where the repo is
  capped at `investigate` (and the ceiling is deliberate — it is live-symlinked
  into `~/.hermes/`), the deliverable is a `patches/*.patch` entry plus its row in
  the repo's own patch documentation, handed over as work the owner can apply.
  Offer it; do not route around the ceiling on your own initiative.

## Report shape

Verdict first in one line: is the defect real, and did the proposed fix survive
verification. Then one line per finding — the mechanism, the correction to the
claim (if any), the live state of the affected artifact. Then the ceiling line:
what can and cannot land it. Close with what you did **not** do and why.
