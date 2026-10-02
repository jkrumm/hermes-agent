---
name: live-container-fact-probe
description: "Use when a runtime fact must come from the live container."
version: 1.0.0
metadata:
  hermes:
    tags: [verification, docker, container, deployed-truth, dependency-api, version, read-only]
    related_skills: [homelab-ops, vps-app-verification, runtime-claim-verification, dependency-pinning-audit]
---

# Live container fact probe

A checkout is an **opinion**; the container is the deployment. When the fact you
need is "does this class exist in the installed version", "which version is
deployed", or "what does this library actually raise", the lockfile and the source
tree cannot answer it — the image was built from some earlier commit, and a
dependency the code imports may not be installed locally at all. Ask the process
that is running.

## Procedure

1. **Name the fact precisely.** "Which exception types does `<lib>` expose at
   runtime", not "how does `<lib>` behave". If the answer lives in the process's
   own memory (a loaded config, a bound port) read the process; if it comes from
   installed package metadata, read the image.
2. **One read-only exec per fact.** Reach the host first, then the container
   (`ssh <host> "docker exec <ctr> …"`). Shapes that answer most questions:

   ```bash
   # Python: version + exception/attribute surface
   docker exec <ctr> python -c "import lib; print(getattr(lib,'__version__','?')); print([n for n in dir(lib) if 'Error' in n])"
   # Python: is it installed there at all, and which build
   docker exec <ctr> python -m pip show <pkg>
   # Node
   docker exec <ctr> node -e "console.log(Object.keys(require('lib')))"
   # Any image
   docker exec <ctr> <binary> --version
   ```

3. **Never mutate the container to answer a question.** No `pip install`, no
   redirect into a file, no restart, no config write. A read-only exec into a
   container whose health is currently failing is fine; into one that is
   mid-deploy is not — let the deploy settle first.
4. **Close the caveat before acting on it.** A brief, verdict or review that says
   "verify the exact exception class names — the library is not installed in this
   checkout" is asking for exactly this probe. It takes seconds and de-risks the
   change you are about to write or review, instead of leaving the import to be
   discovered by whatever runs it next.
5. **Report provenance with the fact.** Quote the command and the output line, and
   say it came from the running container at that moment — a measurement of the
   deployment, not of the repository.

## Pitfalls

- **An env dump leaks secrets.** `docker exec <ctr> env` prints bearer tokens, DB
  URLs and service-account keys straight into the transcript. Read key *names* or
  value *lengths* instead (`env | cut -d= -f1`), and never paste a value into a
  reply, an issue or a commit.
- **The container's version wins over the lockfile.** When the two disagree the
  discrepancy *is* the finding: the image predates a dependency bump, so the code
  the repo declares is not the code that is running. Say which side you read.
- **Don't probe what a Tier A verb already answers.** Container state, health and
  logs are `homelab-ops` verbs (`containers`, `logs`); this skill is for facts
  *inside* the process, which no verb exposes.
- **A fact read from a live container is not a licence to patch it.** If the probe
  shows the deployed code is wrong, the fix goes through the repo and a deploy —
  never a live edit inside the container.
- **A single read is a snapshot.** A container recreated by a deploy or a watchdog
  restart can change the answer; re-read if the fact matters and the container has
  moved since.

## Worked shape — a health signal that names the wrong cause

A service whose probe catches bare `Exception` and flips an `auth_ok` flag turns
every upstream fault into an "auth/credential down" self-report; the container then
reads `unhealthy` and any reactive re-login path keyed off that status burns a real
credential round-trip for nothing. The probe is how you separate the two: read the
health body for the upstream status code, and check the dependency directly
(`curl -s -o /dev/null -w '%{http_code}' https://<upstream>/`) rather than trusting
the service's own verdict about itself. When the two disagree, the misclassification
is a code defect for the repo — not an ops condition, and not a reason to restart or
re-authenticate anything.

## Report shape

One line: the fact, the version it came from, and the command if he will re-run it.
No narration of how you reached the host.
