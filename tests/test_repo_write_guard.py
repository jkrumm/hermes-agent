#!/usr/bin/env python3
"""Regression suite for the local raw-repo-write guard.

Covers `_repo_write_reason()` in
`~/.hermes/hermes-agent/tools/tirith_security.py`, installed by
`patches/tirith-hermes-guards.patch`.

WHY THIS GUARD EXISTS. On 2026-08-02, asked in Slack to fix a README in
`dispatch-scratch` "implement tier", Hermes read the repo, saw the branches two
earlier *dispatched* episodes had left behind, said in as many words "I'll put the
fix on master directly", edited the file with the terminal tool, committed, hit a
push rejection because the remote had moved, fetched, rebased, and pushed. Nine
turns and no `hermes-cc.sh` — so the per-repo tier ceiling, worktree isolation, the
never-push-to-a-default-branch rule, the draft-PR gate, the merge checks, three
daily budgets and the audit log were all simply not involved. It is the `claude -p`
incident (see test_raw_agent_guard.py) one layer down: that guard blocks the raw
AGENT, this one blocks the raw REPO WRITE.

It is unconditional rather than path-scoped because it has to be: `git commit -m x`
names no path, the repo comes from the terminal tool's working directory, and a
path-scoped rule is evaded by `cd` — which is literally what happened.

This guard runs before tirith on *every* terminal command, so a false positive is a
Slack approval gate on routine work and an exception is an outage — which is why
the allow half of this suite is as important as the block half. Two capabilities in
particular MUST keep working, and each has cases below:

  * `gh issue create` — the `capture` skill's sanctioned path, and what the
    `author` tier files ungated. An issue changes nothing that runs.
  * committing in `~/SourceRoot/brain` — the `obsidian` skill requires it ("a write
    isn't durable until it's committed") and the vault is DENIED by the dispatch
    policy, so there is no bounded path to redirect it to. The exemption is narrow:
    the command must name the vault.

Run against the live tree (it imports from wherever HERMES_TREE points):

    ~/.hermes/hermes-agent/venv/bin/python3 tests/test_repo_write_guard.py

Exit status is 0 only when every case matches.
"""

import os
import random
import string
import sys

HERMES_TREE = os.environ.get("HERMES_TREE", os.path.expanduser("~/.hermes/hermes-agent"))
sys.path.insert(0, HERMES_TREE)
os.chdir(HERMES_TREE)

from tools.tirith_security import _repo_write_reason as reason  # noqa: E402

VAULT = "~/SourceRoot/brain"

# Shapes that MUST be blocked.
ATTACKS = [
    # --- the literal observed failure, and its parts -------------------------
    "cd /Users/jkrumm/SourceRoot/dispatch-scratch && git add -A && "
    'git commit -m "docs: explain repo purpose" && git push',
    'git commit -m "docs: explain repo purpose"',
    "git push",
    "git push origin master",
    "git push --force-with-lease origin HEAD",
    # after the rejection, the exact recovery it performed
    "git fetch origin && git rebase origin/master && git push",
    # --- reaching a repo without cd ------------------------------------------
    "git -C /Users/jkrumm/SourceRoot/argo commit -am wip",
    "git -C ~/SourceRoot/sideclaw push",
    "git --git-dir=/Users/jkrumm/SourceRoot/argo/.git commit -m x",
    # --- other write verbs ----------------------------------------------------
    "git merge origin/master",
    "git rebase -i HEAD~3",
    "git reset --hard origin/master",
    "git revert HEAD",
    "git cherry-pick abc1234",
    "git checkout -b dispatch/mine",
    "git switch -c feature/x",
    "git restore --staged .",
    "git clean -fd",
    "git rm README.md",
    "git mv a.txt b.txt",
    "git stash push -m wip",
    "git tag v1.2.3",
    "git branch -D old-branch",
    "git branch feature/new",
    "git worktree add /tmp/wt master",
    "git update-ref refs/heads/master abc1234",
    "git apply /tmp/patch.diff",
    "git am /tmp/0001.patch",
    "git config user.email x@y.z",
    "git remote add upstream https://github.com/x/y",
    "git submodule update --init",
    'git filter-branch --tree-filter "rm -f secret" HEAD',
    # cloning into the discovery root creates a dispatchable target
    "git clone https://github.com/someone/thing ~/SourceRoot/thing",
    "git init ~/SourceRoot/newrepo",
    # --- wrappers and nesting -------------------------------------------------
    "timeout 60 git push",
    "nohup git push &",
    "sudo git -C /repo commit -m x",
    'bash -c "cd /repo && git push"',
    "sh -c 'git commit -m x'",
    'ssh mini "cd ~/SourceRoot/x && git commit -m y && git push"',
    "cd /tmp && cd /Users/jkrumm/SourceRoot/argo && git commit -m x",
    # an explicit -C outside the vault beats an earlier cd into it
    "cd ~/SourceRoot/brain && git -C ~/SourceRoot/argo push",
    # --- gh, everything that changes code or its delivery ---------------------
    "gh pr create --title x --body y",
    "gh pr merge 7 --squash --delete-branch",
    "gh pr ready 7",
    "gh pr close 7",
    "gh pr edit 7 --title x",
    "gh release create v1.0.0",
    "gh repo create jkrumm/newthing --private",
    "gh repo delete jkrumm/oldthing",
    "gh repo edit --default-branch main",
    "gh workflow run deploy.yml",
    "gh run rerun 12345",
    "gh secret set FOO --body bar",
    "gh api -X PUT repos/jkrumm/x/pulls/1/merge",
    "gh api --method DELETE repos/jkrumm/x/git/refs/heads/dispatch/y",
    "gh api repos/jkrumm/x/contents/README.md -f message=x -f content=y",
    # --- the GitHub write API by hand ----------------------------------------
    "curl -X PUT --data-binary @/tmp/b https://api.github.com/repos/jkrumm/x/pulls/1/merge",
    "curl -X POST -d @/tmp/pr.json https://api.github.com/repos/jkrumm/x/pulls",
    "curl --request DELETE https://api.github.com/repos/jkrumm/x/git/refs/heads/y",
    'curl -X POST -d @/tmp/gql.json https://api.github.com/graphql',
    "curl -T /tmp/asset https://uploads.github.com/repos/jkrumm/x/releases/1/assets",
]

# Shapes that MUST be allowed. Reading a repo is the agent's job; so is filing an
# issue, and so is committing the vault.
LEGITIMATE = [
    # --- every inspection the triage skills actually use ----------------------
    "git log --oneline -10",
    'git log --pretty=format:"%h %ad %s" --date=format:"%H:%M:%S" -10',
    "git -C /Users/jkrumm/SourceRoot/sideclaw log --oneline -5",
    "git status --short",
    "git diff HEAD~1",
    "git diff --stat",
    "git show abc1234",
    "git blame README.md",
    "git rev-parse HEAD",
    "git for-each-ref --format='%(refname)' refs/heads",
    "git branch",
    "git branch -a",
    "git branch --list --contains HEAD",
    "git tag",
    "git tag -l",
    "git stash list",
    "git remote -v",
    "git config --get user.email",
    "git ls-files",
    "git shortlog -sn",
    "git describe --tags",
    # fetch mutates only remote-tracking refs and is how a read stays current
    "git fetch origin",
    # --- the capture skill's sanctioned GitHub path ---------------------------
    "gh issue create -R jkrumm/homelab --title x --body y",
    'gh issue create -R jkrumm/rollhook --title "deploy 502" --body "see thread"',
    "gh issue close 12 -R jkrumm/x",
    "gh issue comment 12 -R jkrumm/x --body hi",
    "curl -X POST -d @/tmp/i.json https://api.github.com/repos/jkrumm/x/issues",
    # --- gh reads, including ones whose flag VALUES look like subcommands -----
    "gh repo list jkrumm --limit 200 --json name,description,visibility,isArchived",
    "gh pr list --search add",
    "gh pr view 7",
    "gh pr diff 7",
    "gh issue list -R jkrumm/homelab",
    "gh search issues --owner jkrumm --state open",
    "gh api repos/jkrumm/x/pulls/1",
    "gh run list --limit 5",
    "curl -s https://api.github.com/repos/jkrumm/x/pulls/1",
    # --- the vault, named explicitly ------------------------------------------
    f"cd {VAULT} && git add -A && git commit -m 'note: capture'",
    f"git -C {VAULT} commit -am 'note'",
    f"git -C {VAULT} push",
    f"cd {VAULT}/wiki && git add . && git commit -m x",
    "cd /Users/jkrumm/SourceRoot/brain && git commit -m x",
    "cd $HOME/SourceRoot/brain && git commit -m x",
    # --- the sanctioned dispatcher itself -------------------------------------
    "~/.hermes/scripts/hermes-cc.sh dispatch sideclaw --wait --json",
    '~/.hermes/scripts/hermes-cc.sh merge abc-123 --why "approved" --confirm',
    "~/.hermes/scripts/hermes-ops.sh status --json",
    # --- unrelated traffic that merely mentions the words ---------------------
    'curl -sS -H "Authorization: Bearer $HOMELAB_API_KEY" https://argo.jkrumm.com/api/health | jq',
    "python3 ~/.hermes/scripts/watchdog-poll.py --slack-body",
    'sqlite3 ~/.hermes/watchdog.db "select count(*) from events"',
    "ls ~/SourceRoot",
    'grep -rn "git commit" ~/.hermes/skills',
    "cat ~/SourceRoot/argo/README.md",
]

# Deliberate gaps. Documented rather than silently accepted, so the suite says so
# when one closes.
# NOT listed as a gap, because it fails CLOSED and is therefore the correct
# behaviour rather than a hole: `cd <vault>` in one terminal call and `git commit`
# in the next is two commands, and per-command scanning cannot connect them — so
# the commit is refused, and the agent has to name the vault. That is a usability
# cost on one repo, not a bypass.
KNOWN_GAPS = [
    # Editing files without git. Not durable and not outward-facing: nothing is
    # pushed, and `git status` shows it. The guard targets what LANDS.
    "cat > ~/SourceRoot/argo/src/x.ts <<'EOF'\nbroken\nEOF",
    # Value indirection where the program name never appears in command position.
    "G=git; $G push",
]


def _fuzz_inputs(n):
    """Random junk, plus junk with repo-ish substrings, to prove it never raises."""
    rnd = random.Random(20260802)
    alphabet = string.printable
    words = ["git", "gh", "commit", "push", "-C", "api.github.com", "$(", ")", "|",
             "&&", ";", "cd", "~/SourceRoot/brain", "'", '"', "\\", "\n", "--method"]
    for _ in range(n):
        if rnd.random() < 0.5:
            yield "".join(rnd.choice(alphabet) for _ in range(rnd.randint(0, 120)))
        else:
            yield " ".join(rnd.choice(words) for _ in range(rnd.randint(1, 25)))


def main():
    failures = []

    for cmd in ATTACKS:
        if not reason(cmd):
            failures.append(("MISSED", cmd))

    for cmd in LEGITIMATE:
        r = reason(cmd)
        if r:
            failures.append(("FALSE POSITIVE", f"{cmd}  -> {r}"))

    fuzz_raised = 0
    for cmd in _fuzz_inputs(4000):
        try:
            reason(cmd)
        except Exception as exc:  # noqa: BLE001 — the point is that nothing escapes
            fuzz_raised += 1
            if fuzz_raised <= 3:
                failures.append(("RAISED", f"{exc!r} on {cmd!r}"))

    closed = [c for c in KNOWN_GAPS if reason(c)]

    print(f"attacks blocked       {len(ATTACKS) - sum(1 for k, _ in failures if k == 'MISSED')}/{len(ATTACKS)}")
    print(
        f"legitimate allowed    {len(LEGITIMATE) - sum(1 for k, _ in failures if k == 'FALSE POSITIVE')}/{len(LEGITIMATE)}"
    )
    print(f"fuzz (4000 inputs)    {'clean' if fuzz_raised == 0 else f'{fuzz_raised} RAISED'}")
    print(f"known gaps still open {len(KNOWN_GAPS) - len(closed)}/{len(KNOWN_GAPS)}")

    if closed:
        print("\nNote: a documented gap is now closed — update KNOWN_GAPS and CLAUDE.md:")
        for cmd in closed:
            print(f"  {cmd}")

    if failures:
        print("\nFAILURES:")
        for kind, detail in failures:
            print(f"  {kind}: {detail}")
        return 1

    print("\nall cases as expected")
    return 0


if __name__ == "__main__":
    sys.exit(main())
