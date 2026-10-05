# Proving a merge's rollout actually landed

_Use when a merge must be proven live before closing it._

Use when a card says *"merged <PR> but the deploy failed (exit N)"*, when the
question is *"is this change live?"* and no monitor answers it directly, or before
reporting any merged change as shipped. A rollout is a one-shot shell chain that
nothing retries and nothing re-checks: the divergence that made step 1 fail gets
repaired by hand, the deploy then succeeds, and the card still reads *failed*.

Walk the chain in the order it can fail. Stop at the first step that is not live
and fix that one — every later step's evidence is meaningless until it passes.

## 1. Pull

```bash
git -C <live-checkout> pull --ff-only                 # rc=0 / "Already up to date"
git -C <live-checkout> rev-list --left-right --count origin/master...HEAD   # "0	0"
```

An `--ff-only` refusal means the live checkout holds unpushed local commits while
origin carries the merge. The repair is to **push those commits** — they are the
deploy checkout's own truth — never to merge, rebase or force into a checkout that
production execs.

## 2. Re-render (plists, generated config)

`make launchd-install`-style steps reconcile a repo template against what is
installed. Diff the two directly rather than trusting the last run: read the
installed file under `~/Library/LaunchAgents/` and the repo template
(`python3 -c "import plistlib; …"`, `plutil -p`) and compare the keys that matter.
Identical output = the step landed; a key present in the template and absent
installed = it never ran against the new template.

## 3. Restart — the decisive datum, and the cheapest

```bash
launchctl list | grep <job>     # PID column; "-" = loaded, not running
ps -o lstart= -p <pid>          # process start time
```

A process started **after** the merge commit runs the new checkout. When a restart
step was skipped, an otherwise complete-looking deploy still serves the old code —
this is the check that catches it.

## 4. Build artifact

A built bundle is a file, not a commit; freshness is only half the answer.

- mtime after the merge (`git log -1 --format=%ci <merge-sha>`) proves it was rebuilt.
- Fetch the **served** bytes over the port that serves them and grep for a marker
taken from the PR diff (a new constant, an `aria-label`, a log line):

```bash
curl -s http://127.0.0.1:<port>/assets/<chunk>.js | grep -c '<marker>'
```

Grepping the dist directory only proves the build exists, never that the server
hands it out. For a client-rendered route, take the chunk name from the served
entry file rather than from the repo root.

## 5. Edge / proxy in front of the app

The reverse proxy has its own deploy (image build + roll) and its own green check,
so verify **behaviour, not the workflow status**: probe the allowed class (expect
200) and every deny class (expect 404 — other model, missing parameter, duplicated
parameter, percent-encoded key). A deny class answering 200 is the fix not being
live, however green the deploy run was.

## 6. Liveness

Read the app's own health file (its `ok` flag **and** its push-heartbeat field —
`sent`, not merely a fresh file), then the control loop's `/health`
(`pollers.*.ok`). A merge that reached the checkout while a periodic job stayed
dead is still a failed rollout.

## Discharging the parked item

A `needs_decision`/`failed` row never expires —
no poller retries it — so after the proof above, end it yourself:

```bash
~/.hermes/scripts/hermes-cc.sh close <event-id> --why "<what the blocker was, why it is gone, what shipped, where it is>"
```

- `close` writes the `closed by hand: ` prefix itself — never put that phrase in `--why`.
- It refuses an in-flight item (`working`/`merging`/`verifying`); `abort <event-id> --why` is the verb there.
- `--why` carries the **real defect**, not the symptom: the rollout has no retry
  path, so the row never learned the deploy had completed. Name the evidence
  (pull rc, artifact mtime, process start time, probe results).
- Confirm: `curl -s http://127.0.0.1:7735/items/<id>` → `state: closed`. Argo
  `/warden` updates on the next loop tick; a stale Slack line is a snapshot, not a
  second finding.
- One cause files one row per merged PR. Close the siblings in the same pass.

## Pitfalls

- **A card's note can name a downstream step whose upstream input never landed.**
  "needs `make launchd-install` on the host" is a no-op while the plist change sits
  on an unmerged branch (usually a draft PR — implement episodes open drafts, and a
  draft cannot merge). Before performing what a note names, check the change is in
  the live checkout: `git log -3 -- <path>`, `git branch -a --contains <sha>`,
  `gh pr list --state open`. Report the real blocker instead of running the step.
- **A green deploy workflow is not the artifact being served.** Proxy deploys run
  in the app repo or in an infra repo, and the pull/render/restart chain on the
  compute host is a separate deploy with no retry — verify each independently.
- **Never force a merge or a hard reset in a deploy checkout** to make the pull
  step pass. Unpushed local commits there are usually real work; pushing them is
  the reversible fix.
- **Do not restart a healthy service to "re-run" a rollout that already landed.**
  A restart is a production event, and step 3 already told you whether it ran.
- **Do not re-dispatch or re-open the Warden item** to make the card agree with
  reality. Close it with the evidence; a re-dispatch spends an episode against a
  wall that has already fallen.
