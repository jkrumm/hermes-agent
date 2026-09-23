---
name: fix-recommendation-verification
description: Use when a verdict or report recommends a local fix.
version: 1.0.0
metadata:
  hermes:
    tags: [verification, verdict, upstream, dependency, patches, disposition, triage]
    related_skills: [warden-verdict-disposition, defect-report-verification, claude-dispatch, hermes-log-alert-forensics, agent-claim-verification]
---

# Verifying a recommended fix before acting on it

A Warden verdict, a review round, an alert triage — each ends in a
*recommendation*: patch this file, add this guard, bump this dep. The
recommendation is written from the LOCAL symptom by a reader that never saw the
upstream tracker, the project's patch mechanism, or the delivery window. Verifying
the defect is not the same as verifying the fix: run the three checks below
before you build the artifact, or you will hand over a patch for a bug that was
released away weeks ago, in a shape the project cannot apply.

## Procedure

1. **Follow the recommendation back to its claim, then forward to upstream.**

   ```bash
   gh issue view <n> -R <owner>/<repo> --json state,stateReason,closedAt,title
   gh pr view <n> -R <owner>/<repo> --json state,mergedAt,title
   gh release list -R <owner>/<repo> --limit 5
   ```

   Read the installed version too (`importlib.metadata.version('<dist>')`, or the
   `dist-info` directory). **An upstream issue closed as completed plus a release
   newer than the installed one means the bug class is already fixed and the
   recommended local patch is superseded** — the fix is a version bump, not a
   patch file. Say that in the report; a superseded patch is worse than none,
   because it costs a review and rots on the next upgrade. Check the fix's own PR
   body against your symptom before believing it covers your case.

2. **Check the recommended artifact can reach the file it names.** Every project
   has one real mechanism; a recommendation written from a stack trace frequently
   proposes a file the mechanism cannot touch. For hermes-agent: `patches/*.patch`
   live in the overlay repo (`~/SourceRoot/hermes-agent`) and are `git apply`'d
   against upstream **repo** files in the install checkout (`~/.hermes/hermes-agent`),
   asserted by `make patch-check` — so anything under that venv's `site-packages`
   is unreachable, and a vendored third-party fix there is a dependency pin bump,
   a host action, not a patch entry. Read the project's patch/upgrade doc before
   manufacturing the artifact.

3. **Pick the least-powerful delivery that actually fixes it.**

   | Shape of the fix | Deliver as |
   |-|-|
   | Upstream released it | dependency pin bump + reinstall |
   | In-repo code the project already patches | one `patches/<name>.patch` + the project's table row |
   | Host state (venv, config, LaunchAgent) | a human-trackable task with the exact commands |
   | A repo the dispatch policy caps below `implement` | nothing automated exists — hand fix |

4. **Apply in the restart / update window, never under the running process.**
   A fix that only takes effect on restart buys *nothing* when applied early:
   swapping a package or rewriting a module of a live process leaves it
   mixed-version (already-imported modules from the old release, later imports
   from the new) — risk with zero effect. Resolve compatibility from installed
   metadata first (`importlib.metadata.requires('<dependent>')` for the constraint
   the dependent declares), then hand over one line: install the pin and restart
   in the same window.

5. **Route the durable action where it can survive, and close the item.** When
   the repo is tier-capped, no automated lane exists: a fresh issue or `run` there
   only re-investigates and hits the same cap. A capped repo (hermes-agent is
   `investigate` in **both** copies — warden's `config/dispatch-repos.json`
   `tiers.investigate` and sideclaw's `GET /api/dispatch-policy` `ceiling`) makes
   the remaining fix a human action: `capture` it with the exact commands, then
   discharge the verdict-only item with the reason in `--why` (see
   `warden-verdict-disposition`).

## Pitfalls

- **A denied repo's fix is a hand fix, not a dispatch.** `homelab-private` (and
  `dotfiles-private`) have no `implement` lane at all, so land the change
  yourself: edit the local checkout, push, `ssh homelab "cd ~/homelab-private &&
  git pull"`, verify on the host, then close the item naming the commit hash. Do
  not re-file it on the neighbouring repo (`homelab`) instead — that repo can
  only be dispatched at `investigate` for the part it owns, and an episode there
  cannot reach `homelab-private`'s files.
- **Do not file the issue a verdict asks for when the root cause is already
  tracked upstream and the repo is capped.** `nextAction: issue` is an opinion,
  not a filed issue; on a capped repo it costs an episode that can only re-derive
  the same verdict. Check the tracker, then say the issue already exists.
- **A self-heal that is mapped is not a self-heal that fires.** Before implying
  the loop will clear something, read the gate: warden's `maybe_auto_remediate()`
  needs the folded verdict's `nextAction` to be `human` or `implement` at or above
  `hostVerbMinConfidence`, so a verdict folding `issue` disables the mapped host
  verb silently — signature mapped, cooldown expired, nothing happens.
- **Never hand over a command that needs a live interpreter swap you are not
  running.** State the prerequisite (restart in the same window) in the same
  breath as the command, or the next reader runs half of it.
- **A recommendation that names a third-party file is a signal to check the
  dependency's own changelog first**, not a licence to write a vendor patch. Vendor
  patches are the most expensive shape: they break every upgrade and nobody owns
  them.

## Report shape

Verdict first, one line: whether the recommended fix stands, is superseded
upstream, or is the wrong shape — and what you did with the item. Then one line
per finding: the mechanism (released where, reachable how, gated by what). End
with the single next action and where it is tracked. Do not narrate the commands.
