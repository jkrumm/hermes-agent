---
name: verify
description: One checklist before you relay or act on a claim — a finished agent episode, a "fixed" status, a defect report, a deploy that "went out". Use whenever something was reported to you rather than observed by you, or before saying "done", "live" or "fixed" to Johannes.
version: 1.0.0
metadata:
  hermes:
    tags: [verify, verification, claim, evidence, probe, deploy, live, fixed, done]
    related_skills: [warden, dispatch, homelab-ops]
---

# Verify — evidence, not prose

A claim and its artifact are different things; only the artifact is evidence. A card
note, a PR body, a brief's "measured" number and an agent's "done" are all written by
the thing being checked.

## The checklist

1. **Name the claim** in one sentence — what exactly would be true if this were right.
2. **Observe it yourself, this turn.** Run the probe; do not repeat an earlier result.
   - Item / episode state → `warden` skill (`/items/<eventId>`), never the ledger file.
   - Code defect → read the code at the cited line on the current default branch.
   - Deploy / "live" → the running thing: container, health URL, process start time
     later than the merge.
   - Host fact → the host itself (`ssh homelab` / `ssh vps` for those machines).
3. **Check the probe measures what it claims.** A green health check that never
   exercises the changed path proves nothing; a process started before the fix still
   runs the old code.
4. **Check the right target.** Live checkout vs the branch you read; the container vs
   the image tag; this host vs CI.
5. **Report in one of three states:** *verified* (what you saw), *unverified* (what you
   could not check, and why), *contradicted* (what you saw instead). Never "should work".

## Reference — read the one that matches

| Situation | File |
|-|-|
| Relaying a dispatched agent's result | `references/agent-claim-verification.md` |
| A reported code defect or review finding | `references/code-probe-verification.md`, `references/runtime-claim-verification.md` |
| A claim about live state | `references/live-invariant-probe.md`, `references/live-process-change-verification.md` |
| A probe that may not measure what it says | `references/probe-fidelity.md` |
| A merge that must be proven live | `references/deploy-rollout-verification.md`, `references/vps-app-verification.md` |
| A cron/launchd job fails but your shell works | `references/noninteractive-context-verification.md` |
