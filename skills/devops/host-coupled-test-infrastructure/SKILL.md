---
name: host-coupled-test-infrastructure
description: Use when a test stack fails on this host but passes in CI.
version: 1.0.0
metadata:
  hermes:
    tags: [e2e, docker-compose, host-port, checks-failed, sideclaw, dispatch, brief, traefik]
    related_skills: [fresh-worktree-test-lanes, claude-dispatch, warden, rollhook-deploys]
---

# A test stack that collides with the dev host

A compose-based e2e lane can be red on the dev host for reasons that have nothing to
do with the diff, while CI is green. Every one of them reads like an app bug and
ends in the same shape: the episode's own check reports a failed `test` step, the
implement episode withholds its PR, and the item lands `checks_failed`.

Sibling skill: `fresh-worktree-test-lanes` covers the *other* environment gap — a
gitignored store the episode's worktree never receives. This one is about the host
the lane runs on: occupied ports, a daemon the pinned image cannot talk to, and a
suite longer than the harness's per-command cap.

## Procedure

1. **Read the real cause off the container, not the test's error.** The test reports
a readiness timeout; the container names the mechanism.

   ```bash
   docker logs <container> 2>&1 | tail -20
   ```

2. **Check host port occupancy before blaming the app.** A publish that loses to an
already-bound address is silent — the container starts, the mapping does not take,
and every `localhost:<port>` call is answered by the *other* process.

   ```bash
   lsof -nP -iTCP:<port> -sTCP:LISTEN
   ```

3. **Check the daemon's minimum API version against the pinned image.**

   ```bash
   docker version --format '{{.Server.APIVersion}} min={{.Server.MinAPIVersion}}'
   ```

4. **Bring the stack up by hand with the harness's env to isolate the layer.**

   ```bash
   PROJECT_ROOT=$PWD <HARNESS_ENV> docker compose -f <file> --project-name <proj> up -d
   docker port <svc>
   ```

   Answers → the failure is the harness's ordering or its readiness wait. Does not
answer → the image or the port collision.

5. **Measure the suite's wall clock, then compare it to the check runner's cap.**
sideclaw's `check` caps each command at 180s and records `timed out after 180s` as a
**failed** step, so a green suite that needs longer reports red. Run the lane under a
longer cap (`gtimeout 300 <cmd>`) and say so in the brief, or the implement episode's
own check will withhold the PR.

6. **Verify the fix in a fresh worktree at the commit under test** and report the exact
pass count and exit code — the fresh worktree, never the live checkout.

7. **Hand the whole finding to one `run` brief**: every blocker, the fix for each, the
cap, and the scope limits. If the brief you already opened is incomplete, abort and
re-open rather than letting the episode derive a partial verdict.

   ```bash
   ./scripts/warden abort <event-id> --why "brief incomplete: <what is missing>"
   ```

## Pitfalls

- **The first blocker hides the rest.** Fixing the visible failure only advances the run
to the next host collision. Fix one, re-run, read the new failure — a brief naming only
the first blocker reaches a verdict for a fix that does not clear the check, and the
card then reads like finished work.
- **Move the host-side mapping only.** Remap the published port and the URL the tests
hardcode; leave the container-internal port and any URL baked into something durable
(an OIDC issuer inside signed tokens) untouched.
- **Do not touch the production compose file to fix a test pin.** A test-only pin bump
belongs in the test compose file; a production service that floats on a major tag is
already resolving to a fixed version and is not the defect.
- **A test teardown can write a generated artifact into the repo.** Name it as out of
scope in the brief, or the episode's PR carries churn nobody asked for.
- **A `pending` dispatch is queued, not wedged.** sideclaw caps concurrent workers
(`SIDECLAW_JOB_CONCURRENCY`, default 3); read `GET /api/jobs/health` for
`running`/`pending`/`max` before concluding an item is stuck.
- **Clean up explicitly.** `git worktree remove --force`, `docker rm -f <names>`,
`docker network rm <net>`. A `docker *prune*` invocation is deny-listed on this host
and is refused outright.
