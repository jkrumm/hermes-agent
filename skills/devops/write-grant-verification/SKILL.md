---
name: write-grant-verification
description: "Use when a credential-gated write 403s or fails silently."
version: 1.0.0
metadata:
  hermes:
    tags: [credentials, grants, pat, token, 403, permissions, github, silent-failure]
    related_skills: [github-auth, headless-secrets, defect-report-verification]
---

# Verifying what a credential may actually write

A credential that authenticates is not a credential that is *authorized* for the
write you are about to rely on. Prove the grant before trusting the path, and
prove it without creating anything.

## The two status codes are the whole diagnosis

| Code | Means |
|-|-|
| **403** | the credential is valid but lacks the grant the route needs |
| **404** | the credential is authorized; only the resource is unknown |

So probe a **nonexistent** resource. A 404 proves the grant; a 403 proves the
gap; and neither creates, modifies or deletes anything, so the probe is safe to
run against production.

```bash
# GitHub shape — read the accepted-permission header for the grant the route wants
python3 - <<'PY'
import json, urllib.request, urllib.error
req = urllib.request.Request(
    'https://api.github.com/repos/<owner>/<repo>/issues/999999/comments',
    data=json.dumps({'body': 'x'}).encode(), method='POST',
    headers={'Authorization': 'token <TOKEN>', 'User-Agent': 'probe',
             'Accept': 'application/vnd.github+json', 'Content-Type': 'application/json'})
try:
    print('OK', urllib.request.urlopen(req, timeout=20).status)
except urllib.error.HTTPError as e:
    print('HTTP', e.code, '| accepted:', e.headers.get('x-accepted-github-permissions'))
PY
```

`x-accepted-github-permissions` names the exact grant the route requires
(`issues=write; pull_requests=write`, or `contents=write`). Read it rather than
guessing from the route name.

## Pitfalls

- **A repo's `permissions` field describes the *user's* repo role, not the
token's grant set.** `GET /repos/<o>/<r>` returning `admin: true, push: true`
says nothing about which scopes the token carries — which is exactly how a token
that can push branches and merge pull requests still gets 403 on an issue
comment. Never infer write ability from a permissions object; probe the route.
- **Fine-grained GitHub PAT grants are separate.** `Contents: write`,
`Pull requests: write` and `Issues: write` are three independent grants. A token
proven to push and merge is *not* evidence it can comment or label. `gh auth
status`'s scope list describes the **gh CLI's** token, not the one your code
resolves — they are different credentials and one working says nothing about the
other.
- **A refused write can leave no trace in state.** When the retry/dedupe marker
is written only *after* a successful call (the correct design — it prevents
double-posting), a permanently-refused write leaves every record unmarked and the
path silently dead. Check the marker's absence **and** grep the process's own
`.err` log for the refusal line before concluding the path works. "No marker and
no error in state" is not "it worked"; it is "it never ran".
- **Isolate which grant is missing with no-op payloads.** Send the write with an
empty set — `PUT /repos/<o>/<r>/issues/<n>/labels` with `{"labels": []}`
(issues:write), `POST /repos/<o>/<r>/pulls/<n>/requested_reviewers` with
`{"reviewers": []}` (pulls:write). A 201 on one with a 403 on the other names
the single missing grant.
- **This is a grant problem, not a broken tool.** The fix is adding the grant to
the credential (or rotating it), never a workaround around the API. Report it as
the one-line config change it is, and name the exact grant.

## Same shape, other credentials

The pattern generalizes to any credential-gated write: an `op` service account
missing a vault grant, a Slack token missing a scope, a deploy key that can fetch
but not push, a bearer token accepted by one endpoint and refused by another.
Probe the write route against a nonexistent target, read the header or error body
that names the required permission, and report the missing grant.
