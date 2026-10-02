---
name: warden-dispatch-failure-triage
description: Use when a Warden dispatch fails before a verdict.
version: 1.0.0
metadata:
  hermes:
    tags: [warden, dispatch, failure, sideclaw, provider, paymentrequired, retry, lifecycle]
    related_skills: [warden, dispatch-liveness-verification, warden-item-trail, warden-item-closure, claude-dispatch]
---

# Warden dispatch failure triage

Use when a Warden card says a dispatch failed, has no verdict, or an item appears stuck after an executor error. The card is only a notification: first establish which item and exact job failed, then classify the failure, then discharge or preserve the item honestly.

## Procedure

1. **Resolve the exact lifecycle item and full executor job.** Read `/items/<event_id>` and capture `state`, `note`, `dispatch_job`/stage job IDs, `dispatches[]`, and transitions. Query the executor with the full UUID: `curl -s http://127.0.0.1:7705/api/jobs/<uuid>`, then check `curl -s http://127.0.0.1:7705/api/jobs/health` for route warnings, `degradedRoutes`, and `lastFailure`. A shortened card ID is not an executor ID.
2. **Classify by the executor's terminal error, not the item state.** A failed job with no `result`/verdict is an execution failure, not a source finding. Distinguish transient gateway errors from persistent provider/account gates (e.g. `PaymentRequired` / organization balance too low); report the actual category and whether the job got any turns.
3. **Check whether this is a retry of existing work.** Read every sibling Warden item for the repo/finding and inspect the existing PR/branch/worktree before opening anything. If a live item or draft PR already carries the code, do not create a parallel item or writer episode. A revision job that failed on a different branch is not evidence the existing PR is fixed.
4. **Retry only when the failure is transient and the same work can resume safely.** First confirm the original job is terminal and the service/route has recovered; then use the existing item/lifecycle where possible. Do not repeatedly open `run` items against a route whose health still shows the same persistent refusal. A new item does not repair billing and creates another dead card.
5. **Discharge truthfully.** If no code verdict exists and retries are blocked, close/abort only via the valid lifecycle verb, recording that the executor failed before a verdict and the exact unresolved gate. Keep any existing PR draft and unmerged when review is blocked; do not claim the proposed fix landed. Verify the resulting item state from `/items/<id>`.

## Pitfalls

- **Do not treat `investigating` as proof a job is running.** The item may point at a failed job until the next sweep folds it; inspect the executor and the item's latest transition before narrating progress.
- **Do not turn `PaymentRequired` into a code diagnosis or billing instruction.** It is a provider-side gate; record it, stop same-route retries, and do not change payment/auto-top-up settings without explicit authorization.
- **A valid step-7 blocker remains valid even if later implement retries fail for infrastructure reasons.** Keep the review finding and dispatch failure as separate facts; a 502/PaymentRequired does not negate the blocker.
- **Stable-looking probes do not prove shared run identity.** A before/after fingerprint only proves neither value changed in the window; it does not prove two systems name the same generation. Require a truly shared identity or report alignment as unprovable; never use a coincident proxy or identical value as proof.
- **Check sibling lanes before closing a terminal item.** Shared Slack threads can race: another Hermes session may already have closed the item or be editing the existing branch. Read back the item and branch/PR after any disposition.

## Reporting

Verdict first, concise German by default: whether a verdict exists, the concrete executor failure, whether another item/PR still carries the fix, and the one remaining owner decision or external blocker. Do not present a failed dispatch as completed work, and do not report transient errors that have already recovered unless they affect the next action.
