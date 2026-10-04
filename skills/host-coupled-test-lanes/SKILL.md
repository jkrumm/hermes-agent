---
name: host-coupled-test-lanes
description: Use when a test lane fails on this host for a host reason.
version: 1.0.0
metadata:
  hermes:
    tags: [e2e, docker, compose, ports, host-coupling, checks_failed, dispatch, verify]
    related_skills: [fresh-worktree-test-lanes, claude-dispatch, defect-report-verification, warden-lifecycle-gates]
---

# Test lanes that fail on THIS host

A lane can be green in CI and red on this machine for reasons that have nothing to
do with the diff — a pinned image that speaks a container API the local daemon
refuses, a published host port another local service already owns, a suite that
outruns the runner's per-command cap. Every episode in that repo then lands
`checks_failed` with no PR, and the card reads like a red diff.

This is the **host** twin of `fresh-worktree-test-lanes`, which owns the *worktree*
cause (a gitignored store absent from a fresh checkout). Probe the host before you
read the diff.

## Procedure

1. **Get the failing lane's own words first.** Read the check result and the suite's
   log: the readiness wait that died, the test that failed, the `Duration` line.
   `curl -s http://127.0.0.1:7705/api/jobs/<job-id>` → `.result.steps[]` names which
   step failed and `.result.summary` is quotable verbatim.
2. **Run the probe table before touching the repo.**

   | Class | Probe | What you see | Fix |
   |-|-|-|-|
   | Pinned image speaks an API the daemon refuses | `docker version --format '{{.Server.APIVersion}} min={{.Server.MinAPIVersion}}'` | the readiness endpoint never answers; the service's logs carry `client version X is too old. Minimum supported API version is Y` on every poll | bump the image pin to a release whose client speaks the daemon's minimum |
   | Published host port already held | `lsof -nP -iTCP:<port> -sTCP:LISTEN` | `compose up` succeeds; the test receives an application status from a *stranger* | remap the host side (`'18080:8080'`) **and** the URL the test hardcodes |
   | Suite outruns the runner's per-command cap | the suite's own `Duration` line | the check reports `timed out after 180s` as a failed step on a green suite | run the lane under a longer cap (`gtimeout 300 <cmd>`) and say so in the brief |
   | Compose network left behind by a killed run | the compose output itself | `a network with name X exists but was not created for project Y` | `docker network rm <name>` before re-running |

   One read-only sweep for the first three:

   ```bash
   docker version --format 'server API {{.Server.APIVersion}} (min {{.Server.MinAPIVersion}})'
   grep -rnE '^[[:space:]]*image:' <repo>/ --include='compose*.y*ml' | grep -v node_modules
   for p in <published host ports>; do echo -n "$p "; lsof -nP -iTCP:$p -sTCP:LISTEN | awk 'NR==2{print $1,$2}' || echo free; done
   ```
3. **Reproduce in a fresh worktree at the commit under test**, apply the candidate
   edits, run the suite, and read its own totals (`Test Files`, `Tests`, `Duration`,
   `EXIT`). Never reproduce in the live checkout — it carries state an episode's
   worktree never has.
4. **Re-run after every fix.** See the first pitfall: one green run does not mean one
   edit.
5. **Tear down**, and keep the two cleanups in separate calls — see the deny-rule
   pitfall.

## Turning the reproduction into a brief

A locally verified fix is only useful to an episode if the brief carries all of it.

- **Carry the count from the verified tree, not from your first diagnosis.** If the
  green run needed two edits, the brief names two. A brief naming one is incomplete,
  and the episode aborts on the second or lands `checks_failed`.
- **State the environment caveats as constraints**, not as colour: the longer
  wall-clock cap, the port that must not move, the generated artifact to keep out of
  the diff, the file that must not be touched (production compose, CI workflows).
- **Give the acceptance criterion as the suite's own numbers** — files, tests, exit
  code — so the episode can tell a green run from a plausible one.
- **Say what you already did not change**, so the episode does not "fix" it.

## Pitfalls

- **The first blocker hides the rest.** A readiness wait dies *before* the later
  tests ever execute, so the second host collision is invisible until the first is
  fixed. Fix one, re-run, read the new failure — a one-line brief written off a
  single reproduction is the failure shape this skill exists to prevent.
- **An unexpected status from a localhost service may be a *different process*
  holding that port.** The container starts fine; the request goes to the stranger,
  which answers with its own 404/200. The failure text then names the service under
  test, which is the wrong suspect. Ask who is listening before debugging the
  service.
- **Fix the host-side publish, never the container-internal port.** Sibling services
  reference the internal port by service name (an issuer URL, a callback), and the
  in-container healthcheck uses it too. Only the host mapping and the URL the test
  hardcodes change.
- **A suite longer than the runner's per-command cap reports a false failure.**
  sideclaw's `check` caps each command at 180s and records `timed out after 180s` as
  a failed step, so a green suite that needs ~250s looks red. Run the lane under a
  longer cap and put that in the brief, or the implement episode's own check will
  withhold the PR.
- **Do not change production config to make a test lane pass.** A compose file that
  already floats on a major tag is correct; the fix belongs in the test lane's own
  pin. Check which file the failure actually names before editing either.
- **A generated artifact the suite writes is not part of the fix.** A teardown that
  exports demo/fixture data leaves the file dirty in every worktree; name it as
  excluded in the brief rather than letting it into the diff.
- **Keep `docker` cleanup and `git worktree prune` in separate calls.** The estate's
  deny rule matches `*docker*prune*` across the **whole command line**, so a single
  line carrying both a `docker … rm` and a `git worktree prune` is refused outright —
  subcommands and ordering notwithstanding. The refusal is explicit and must not be
  retried or rephrased.
- **A killed e2e run leaves its containers and network behind.** The suite's own
  teardown never ran, so the next attempt meets a stale network and a port still
  bound. Clean containers and the network before re-running, and expect the compose
  warning about a network it did not create.
