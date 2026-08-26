---
name: rollhook-deploys
description: Diagnose RollHook VPS deploy failures — IMAGE_TAG validation rejections, unhealthy-container rollbacks, dangling imports, and health-probe 404s during a rollout. Use for a "#alerts" Deployment failed message, a stale image after a push, or a transient 404 during a rollout.
version: 1.0.0
metadata:
  hermes:
    tags: [rollhook, deploy, vps, compose, image-tag, ci, github-actions, rollout, registry]
    related_skills: [homelab-ops, argo-api]
---

# RollHook Deploys (VPS)

RollHook is the self-hosted deploy system on the VPS (registry + rollout engine at
`rollhook.jkrumm.com`, container `rollhook` via `ghcr.io/jkrumm/rollhook`). Apps deploy
label-driven over OIDC from GitHub Actions — no SSH, no manual `docker compose` on the server.

## How a deploy works

1. **Push to `master`** in an app repo (e.g. `research-gateway`) triggers a workflow
   (`.github/workflows/deploy.yml` or a sidecar-specific one like `deploy-lightpanda.yml`).
2. The workflow calls **`jkrumm/rollhook-action@v1`** with `url`, `image_name`, `dockerfile`,
   `context`. The action builds, pushes to the rollhook registry
   (`rollhook.jkrumm.com/<image>:<sha>`), then triggers the rollout via OIDC (id-token: write).
3. RollHook **discovers the running container** by its compose labels
   (`com.docker.compose.project.config_files` → the compose file path on the server),
   validates the compose file, writes `IMAGE_TAG=<full image URI>` into a job-scoped temp
   env file, and rolls the service to the new image.
4. **Authorization** is by label on the running service: `rollhook.allowed_repos=owner/repo`
   — only that repo may deploy it. No label = deploys denied by default. PR refs always denied.

## The IMAGE_TAG validation rule (the #1 failure mode)

`internal/jobs/steps/validate.go` requires the **raw YAML** image field to contain the
literal string `IMAGE_TAG` (checked BEFORE compose-go substitution — a resolved
`svc.Image` would hide the variable and is not checked):

```go
if !strings.Contains(rawSvc.Image, "IMAGE_TAG") {
    return fmt.Errorf("service image must reference IMAGE_TAG (got: %s)", rawSvc.Image)
}
```

**Correct pattern — nested fallback** (gateway, both argo services):

```yaml
image: ${RESEARCH_GATEWAY_IMAGE:-${IMAGE_TAG:-rollhook.jkrumm.com/research-gateway:latest}}
```

**Broken pattern — single-level fallback:**

```yaml
image: ${RESEARCH_GATEWAY_LIGHTPANDA_IMAGE:-rollhook.jkrumm.com/research-gateway-lightpanda:latest}
```

Every service in a rollhook-managed compose file MUST use the nested form. The outer var
(`${SERVICE_IMAGE:-…}`) allows manual overrides; the inner `${IMAGE_TAG:-…}` is what the
validator sees and what rollhook substitutes on each deploy.

## Diagnosing a "Deployment failed: <app>" alert

1. **Check the container, not just the alert.** `GET /api/docker/vps/containers` (argo):
   a failed deploy usually leaves the OLD container running. Running `:latest` while the
   alert names a pinned `:sha` = the rollout never applied; the app can look perfectly
   healthy while the new image never shipped.
2. **Pull the failing image ref from the alert** — that's the SHA the rollout wanted.
3. **Read the compose file rollhook validates.** The live file is on the VPS checkout
   (`ssh vps "cd ~/vps && grep -n image: apps/<app>/compose.yml"`), which deploys from
   origin. Local `~/SourceRoot/vps` may lag or lead — check the server, and `git log -1` there.
4. **Root cause is almost always a missing nested `${IMAGE_TAG}`** on the failing service.
   Fix in `vps/apps/<app>/compose.yml` (the deployed truth), commit, push, then
   `ssh vps "cd ~/vps && git pull"` and re-trigger the app's deploy workflow (or wait for the
   next push to `master`).
5. **Verify the rollout landed:** container shows the pinned SHA image, healthy,
   `restartCount` sane. Only then close the alert.

## Second failure mode: "rolling deploy failed: container <id> became unhealthy"

Distinct from the validator failure: the rollout **applied**, the new container failed its
healthcheck, and rollhook **rolled back**. The alert names a pinned SHA; the running container
is the PREVIOUS image. No user-visible outage (old container kept serving), but the new image
never shipped — and a crash-looping container is a real app bug, not a config hiccup.

Diagnosis path:

1. **Correlate the failing commit** — `gh run list --workflow=<deploy-*.yml> --limit 5` shows
   which push built the failing image. The run that failed names the same SHA as the alert.
2. **Check the push, not just the HEAD commit.** GitHub paths filters evaluate the whole
   push diff. A push carrying `feat(A)` + `docs(B)` fires the sidecar workflow at HEAD `B`
   because `A` touched the watched dir — so a "docs-only" failing SHA may have real code
   behind it one commit earlier.
3. **Named-list `COPY` is the classic trap.** `COPY --chown=bun:bun parse.ts server.ts ./`
   builds fine until someone adds a new source file without touching the line → the image
   misses a module → the server's import fails at boot → crash loop → unhealthy → rollback.
   Durable fix: glob `COPY *.ts ./` + a `.dockerignore` that excludes `*.test.ts` + a boundary
   test asserting every non-test source is reachable through the COPY instruction.
4. **Verify the fix landed:** container shows the FIXED SHA and healthy, `restartCount` sane.
   Only then close the alert.

## Third failure mode: "unhealthy" because the commit shipped a dangling import

Same alert shape ("container <id> became unhealthy") but the rollback is caused by a
**missing module in the built image**: the committed tree imports a file that never
made it into git. Classic cause: an in-progress feature whose files are still
untracked on the working copy (`git status` shows `?? apps/api/src/routes/foo.ts`),
while `app.ts`/route wiring for that same feature WAS committed. CI typecheck catches
it instantly (`TS2307: Cannot find module`), the built image lacks the file, the runtime
fails the import at boot → crash → unhealthy → rollback.

Diagnosis path (fast — the CI log is the smoking gun):

1. **Read the check workflow for the same SHA first.** `gh run list --workflow=check.yml --limit 3`
   → the run for the failing SHA shows the exact TS2307 (or lint/format) error naming the
   missing module. This is faster and more precise than container archaeology.
2. **Confirm with git state:** `git ls-files | grep <module>` (empty = file never committed)
   vs `git status --short` (the file present as `??` untracked). A file that exists on disk
   but not in `git ls-files` is the missing-link fingerprint.
3. **Which commit added the dangling import:** `git log --oneline -S 'importName' -- apps/api/src/app.ts`.
4. **Fix:** either commit the untracked feature files (+ any schema/migration/cron files the
   feature needs) and push, or remove the import + route wiring if the feature must not ship.
   Both are code changes — Claude Code session territory, not an ops verb.
5. **Verify the gate, don't assume it's missing.** Some app repos gate Deploy on check in the
   same workflow (`needs: check` — e.g. `research-gateway/.github/workflows/deploy.yml`);
   others run check as a fully separate workflow that does NOT block deploy (e.g. `argo`,
   `image-gen` — a red check there still ships a broken image). Read the repo's own
   `deploy.yml` before recommending a `needs: check` gate — it may already exist.

## Fourth pattern: health-probe 404s during a rollout

A rolling replacement can 404 an HTTP health probe for a few minutes even though the
service is healthy — the OLD container briefly serves `:latest` while the NEW one
comes up on the pinned `:sha`, and both images already contain the route. Confirm via
`kuma-db heartbeats <id>` (200 → 404 → 200, flip-back near rollout completion) and the
running image's own `/openapi/json` (route listed there = startup artifact, not a
missing route) before touching anything — restarting mid-window destroys the evidence.
No remediation: report and close once it flips back. Registry-pull cousin of this
pattern: `skills/homelab-ops/references/alert-patterns.md`'s "RollHook deploy failure
— transient 502 on manifest GET".

## Template drift — the silent repeat-offender

App repos keep a `deploy/compose.yml` TEMPLATE (e.g. `research-gateway/deploy/compose.yml`)
that is meant to mirror `vps/apps/<app>/compose.yml`. Fixing only the vps copy leaves the
template stale — anyone regenerating from it re-imports the bug, and the next push to the
app repo fails the same validator. **Always fix BOTH the vps copy AND the app-repo template
in the same change.** Check the template explicitly: a fix commit that touches only
`vps/apps/…` is incomplete.

## Sidecar pattern

A repo can ship multiple images from one codebase (e.g. a gateway + a renderer sidecar).
Sidecars get their own workflow (watching only their own subdirectory) and their own image
line in the same compose file — and each image line needs its own nested `${IMAGE_TAG}`.
One broken service line fails the whole compose validation.
