# Verifying a finding that asserts runtime behaviour

_Use when a review finding asserts runtime behaviour._

An automated reviewer — a step-7 validation, an adversarial review angle, a
dispatch verdict — reads the **diff**, not the machine the diff runs on. Its
blocking findings are therefore claims, and the ones that assert how the runtime
behaves are the class most likely to be wrong: the reviewer inferred the
environment from the files and had no way to check it.

The diff can be correct and the blocker wrong at the same time. Verify before you
relay it as work, re-dispatch, or hand it to the owner.

## Procedure

1. **Read the finding whole and split it into three parts:** the claim (what it
   says is true), the mechanism (why it says so), and the proposed fix. They fail
   independently — a right claim routinely arrives with a wrong fix.
2. **Classify the claim by where it can be checked.**
   - *About the diff* — verify by reading the pushed diff
     (`gh pr view <n> --json state,isDraft,headRefOid,mergeable` plus the branch's
     `git diff`). The episode's own `summary` is a self-report, not evidence.
   - *About runtime/host behaviour* — verify **at the runtime**, never by
     re-reading the file the claim is about.
3. **Reproduce the runtime claim in the runtime's own environment, A/B.**
   Reproduce the scheduler's environment rather than your interactive shell, and
   run it **with and without** the thing the claim names:

   ```bash
   env -i HOME=/home/<u> PATH=/usr/bin:/bin sh -c "echo VAR=[\$VAR]"
   env -i HOME=/home/<u> PATH=/usr/bin:/bin sh -c ". /home/<u>/.profile; echo VAR=[\$VAR]"
   ```

   A variable set in both, or empty in both, means the probe discriminates
   nothing — the pair is what answers the question. For a claim about what a
   scheduler *runs*, read the real schedule (`crontab -l | grep -v '^#'`) instead
   of assuming the convention holds.
4. **Decide the disposition from what the runtime showed.**
   - **Runtime already correct, repo never documented it** — the finding is still
     real, but the defect is **documentation**, not behaviour: a rebuild from the
     repo reintroduces the bug. Land it yourself (step 5). Do not open another
     implement episode for a paragraph.
   - **Runtime genuinely wrong** — the fix belongs in the runtime's own lane
     (an ops/host change), not in a code episode against the repo. Route it there.
   - **Claim false and nothing to document** — say so plainly and discharge the
     card; do not edit correct code to appease a reviewer.
5. **Land the small fix on the artifact's own branch, not a new one.** Fetch the
   pushed branch, cut a detached worktree, edit, commit, push back to the same
   branch so the existing PR picks it up:

   ```bash
   cd ~/SourceRoot/<repo>
   git fetch origin 'refs/heads/<branch>:refs/remotes/origin/<tmp>'
   git worktree add --detach /tmp/<repo>-fix origin/<tmp>
   cd /tmp/<repo>-fix && <edit> && bash -n <script>
   git add -A && git commit -m "…" && git push origin HEAD:refs/heads/<branch>
   ```

   Read the pushed diff back (`gh api repos/<o>/<r>/pulls/<n>/files`) and confirm
   the head SHA moved before claiming the PR is updated.
6. **Discharge the card with the commit in the record, then verify the record
   moved.** The close note is the durable record — name the commit, what it now
   documents, and that the PR remains open for the owner. Re-read the item and
   confirm the new transition row; a verb that exited 0 is not proof.
7. **Report the blocker's disposition, not the blocker.** One line: whether the
   finding held, what you did, and the single decision that is genuinely the
   owner's (typically: the PR is open and verified, merge it).

## Pitfalls

- **A claim about a machine the reviewer never had access to is the shape to
  suspect.** The reviewer says "this never reaches the call" about a host it
  cannot ssh to; that is inference, not observation.
- **A probe that cannot separate the two classes answers nothing.** Always run
  the negative control — the same command with the fix removed — before treating
  a green result as proof.
- **An interactive ssh session is not the scheduler's environment.** It creates a
  login session and changes what the process resolves; test with a stripped
  environment (`env -i`) or a temporary scheduled probe that you remove afterwards.
- **Do not re-dispatch a whole episode to fix a documentation paragraph.** An
  implement episode costs a session and a PR cycle; a two-line doc change on the
  existing branch costs one commit. Reserve the dispatch for a finding that
  requires re-deriving the change.
- **Never work around a merge gate.** A repo with no declared auto-merge path
  scope is the owner's review by design — report the gate rather than merging on
  the web UI, and say plainly that the PR awaits his merge.
- **A find-and-replace edit to a line carrying nested escaped quotes re-escapes
  them.** Shell lines that print a quoted value have several backslash levels a
  patch tool will happily double; read the line back with `git diff` and run the
  syntax check before committing, or the change looks applied while printing
  something different.
- **A reminder about the card describes the state from before your fix.**
  Reminders and cards render from the row and are only re-synced on the next
  state change, so a "still waiting on you" message arriving after a close is one
  sequence, not a second finding.
