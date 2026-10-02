---
name: credential-scope-verification
description: "Use when verifying a credential's permission scope."
version: 1.0.0
metadata:
  hermes:
    tags: [credentials, tokens, scopes, permissions, verification, github, pat]
    related_skills: [headless-secrets, defect-report-verification, warden]
---

# Credential scope verification

`headless-secrets` answers *does the shim resolve this ref*. This skill answers the
next question, which a read-back cannot: **does the credential grant what the
consumer actually does with it.** A token that resolves perfectly and answers
`GET /user` with 200 can still 403 on every write the app performs — and the
failure reads as a broken client, not a missing scope.

Reach for this whenever an app logs a `403`/`401` on a write, whenever a note
claims a credential "was never gated" (or that it was granted), and before
telling the owner to rotate or re-seed anything.

## Procedure

1. **Find the exact operation the consumer performs** — the method and path in
   the client module, not a nearby read. Example: a comment-back path is
   `POST /repos/{owner}/{repo}/issues/{number}/comments`, not `GET /repos/...`.
2. **Resolve the same credential the consumer resolves.** `secrets-run read
   op://<vault>/<item>/<field>`. A CLI's own keyring token (`gh`), an OAuth app
   token, and the app's PAT are three different credentials with three different
   scopes; probing one says nothing about another. Never print the value — probe
   by status code, length, or hash.
3. **Probe the write with a deliberately invalid body** so a permitted call fails
   validation instead of mutating anything (`-d '{"body":""}'`). Read the status:
   - `403 Resource not accessible by personal access token` → the scope is missing.
   - `422` validation error → authorized; the scope is present.
   - `404` → authorized, the object does not exist — still proves the scope.
4. **Read `x-accepted-github-permissions` on the response** (`curl -D -`). It
   names the scope the endpoint requires (`issues=write; pull_requests=write`) —
   read it instead of guessing which tier is needed.
5. **Probe on the resource that actually failed, plus a control.** Run the same
   call on a repo where the consumer succeeded, so "this credential" is separated
   from "this repo". A probe that only ever answers on the failing side proves
   nothing about the boundary.
6. **Report the missing scope by name and the ref it belongs to.** Granting it is
   a 1Password-side owner action — state the exact scope and stop there; do not
   rotate, re-seed, or widen a token on your own initiative.

## Pitfalls

- **A probe that answers on a different resource type proves nothing.** GitHub
  numbers issues and pull requests in one sequence, and a fine-grained PAT can
  hold `pull_requests: write` without `issues: write`: an empty-body comment on a
  **PR** number answers `422` while the identical call on an **issue** number in
  the same repo answers `403`. Pick the probe whose resource type matches the
  failing call — and when re-testing a past "this was never gated" conclusion,
  check which number the original probe used.
- **A successful read proves nothing about write scopes.** `GET /repos/{owner}/{repo}`
  returns `permissions: {push: true, admin: …}` for a token that has no
  `issues: write` at all; `push` is about git contents. Reads, repo metadata and
  pull-request paths all answer fine on a token that cannot comment.
- **A note, a commit message, or a state-log line asserting a credential's scope
  is a hypothesis, not evidence.** It records a probe someone ran, possibly
  against the wrong resource type or a different credential. Re-probe the exact
  operation before repeating the claim to the owner.
- **A `403` on a write is not always a scope problem.** Check the body first: an
  empty or invalid body on a permitted endpoint answers `422`, so a `403` with a
  well-formed body is the scope signal and a `403` on a malformed call is often a
  different layer entirely. Distinguish before reporting.
- **Don't reach for the CLI's credential as a workaround and call it fixed.** A
  one-off shim resolving a different token makes the operation succeed for that
  run while the durable path stays broken — the loop keeps failing on the next
  tick. Name the durable credential that needs the scope.
