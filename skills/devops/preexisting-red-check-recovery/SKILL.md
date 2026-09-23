---
name: preexisting-red-check-recovery
description: Use when a check step was already red on master.
version: 1.0.0
metadata:
  hermes:
    tags: [checks_failed, sideclaw, warden, dispatch, format-check, pre-existing, branch-recovery]
    related_skills: [agent-branch-recovery, agent-worktree-test-hygiene, fresh-worktree-test-lanes, agent-pr-handoff]
---

# A check step that was already red on master

sideclaw's check step runs the repo's **canonical scripts over the whole tree**
(`format`/`format:check`, `lint`, `typecheck`, `test`) — never the diff. So one
file already misformatted on `master`, in a directory the brief never touches,
fails the step for **every** episode in that repo: branch pushed,
`checks_failed`, no PR, and an item whose note reads like finished work.

This is the second cause of a `checks_failed` with a pushed branch. The first —
a worktree missing a gitignored store — is `agent-worktree-test-hygiene` and
`fresh-worktree-test-lanes`; recovering one already-pushed branch in general is
`agent-branch-recovery`.

## Procedure

1. **Read the verdict's prose, not the card note.** The verdict names the file
   and says it is pre-existing; the note quotes only the episode's own positive
   summary, which is why the card looks like a code problem.

   ```bash
   curl -s http://127.0.0.1:7735/items/<event_id>     # dispatches[].verdict
   curl -s http://127.0.0.1:7705/api/jobs/<job_id>    # .result.verdict / .evidence
   ```

2. **Confirm it at pristine `master`, nothing linked in.** A worktree at the
   branch does not answer this question — the file is untouched by the diff.

   ```bash
   git worktree add --detach /tmp/<repo>-pristine master
   cd /tmp/<repo>-pristine && <the failing script, e.g. bun run format:check>
   ```

   Red there and green on the branch = pre-existing, and the branch is clean.

3. **Fix it on `master` as its own commit** — a formatter's own output, no
   behaviour change, no other file in the commit — and push.

4. **Rebase the episode's branch onto the new master and re-push.** Same files
   as before; the step must now be green. Re-run the repo's full canonical set in
   the worktree, not just the touched suite.

5. **Open the PR by hand** — the handler's PR step already ran and refused:

   ```bash
   gh pr create --draft --base <default-branch> --head <branch> \
     --title "<the episode's own subject>" --body "<what, why, verification counts>"
   ```

6. **Close the item**, naming the PR URL and the master commit that unblocked it:

   ```bash
   cd ~/SourceRoot/warden && ./scripts/warden close <event_id> --why "<what landed, where, what you verified>"
   ```

## Pitfalls

- **The red step can be the box's own toolchain, older than the CI pin.** Before
  hunting a stray file, price the tool: `weatherorb`'s `bun run typecheck` and
  `build` died inside `@tanstack/router-core@1.171.27`
  (`ReferenceError: Cannot access uninitialized variable`) on the box's Bun
  **1.1.7**, while `.github/workflows/deploy-edge.yml` pins **1.4.0** — identical
  on pristine `master`, on a diff that touches no JS. Compare local to the pin
  (`grep -rn "bun-version\|setup-bun" .github/workflows/`), back the binary up
  (`cp -a ~/.bun/bin/bun ~/.bun/bin/bun-1.1.7.bak`), `bun upgrade`, then re-run
  the lane: the whole TS set went green with no source change, so there is
  nothing to commit on `master` — only the hand-opened PR
  (`agent-branch-recovery` steps 5–6). Note the host tool fix in the PR body and
  in the close `--why`; the next episode in that repo needs it too.
- **Run the repo's canonical lanes from its `AGENTS.md` (or `CLAUDE.md`)** (weatherorb's
  *Python* / *TypeScript* / *Design guard* rows: `uv run pytest`;
  `bun install --frozen-lockfile && bun run typecheck && bun run build && bun test
  packages/engine apps/web`; `bun run --filter weatherorb-web lint`). A green
  touched suite is not the check the handler runs.
- **Build in the verification worktree, never in the live checkout** — on
  weatherorb `apps/web/dist/` is what the running tileserver serves, so a failed
  or partial build there takes the surface down for a check that was never the
  diff's business.
- **`warden merge <job_id>` is closed on this path.** It refuses with "recorded
  no artifact URL — the episode pushed a branch but never opened a pull
  request", because eligibility derives from the artifact the handler never
  created. Do not force it; the owner's merge click is the gate.
- **Re-dispatching the item is the wrong move.** Same verdict, same wall, one
  more episode spent — and on a repo with no `autoMergePaths` the merge gate
  refuses anyway.
- **A green run of the touched test file is not the check the handler runs.**
  The acceptance evidence is the whole canonical set, in a fresh worktree.
- **Two items for one repo never run concurrently.** A re-dispatched item sits in
  `implementing` carrying `note: deferred: repo '<repo>' already has an implement
  episode in flight (item N) — one at a time per repo`. That is the per-repo
  lock working, not a wedged item; read the earlier item instead of aborting
  this one.
- **Do not clean up the episode's branch before the PR exists.** The branch is
  the only artifact of a `checks_failed` episode; the worktree is torn down and
  the job is pruned from sideclaw within a day.
