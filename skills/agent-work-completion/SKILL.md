---
name: agent-work-completion
description: Use when delegated work must land, not stop at a PR.
version: 1.0.0
metadata:
  hermes:
    tags: [merge, deploy, verify, pr-rot, sweep, herdr, warden, dispatch, human-gate]
    related_skills: [claude-dispatch, warden, warden-item-closure, herdr, agents, background-work-watch]
---

# Finishing the work: authored → reviewed → merged → deployed → verified

Triggers: "fix X and ship it", "why does this alert keep coming back", "everything
ends up in dead pull requests", any follow-up after an episode or a pane agent
reported a branch or a draft PR. Also the standing answer to *"why is this not
self-healing"*: the missing link is almost never the fix, it is the **last mile**.

**The deliverable is live behaviour, not a diff.** "PR opened" is an intermediate
state and must never be reported as the outcome. A chain that stops at a draft PR
is how a fix the user already paid for becomes invisible and then recurs.

The lifecycle machinery (tiers, gates, ledger, who may merge what) is
`claude-dispatch` and `warden`. This skill is the part that decides *when the arc
is actually over*, and does the sweeping.

## 1. Owner authorization is per class, not per PR

When he says a class of change should land automatically ("these should be
reviewed, merged, deployed and verified"), that authorizes **every instance of
that class in the session** — do not re-ask per pull request, and do not read a
missing click as a missing permission. What stays hard-gated:

- changes to the code that **runs the loop itself** (the control plane and its
executor) — a loop that merges its own executor has no outside;
- secrets, ACLs and private repos;
- a decision only he can make (product direction, cost, disk, a restart window).

A *structural* refusal (a repo ceiling, a missing policy path) is not a reason to
stop — it is the finding. Fix the policy, or name it as the blocker.

## 2. Anything human-gated must be a visible queue entry

A Slack thread is not a queue. If something genuinely needs him it lands where he
looks without being told: the Warden board's awaiting-owner list, rendered at the
top of the Warden page in Argo, with **title, repo, link, age in days and the
reason**, oldest first. Then say in one line that it is there.

Corollary: an item parked on a gate that has since gone away keeps sitting there
(`needs_human` / `merge_blocked` are terminal until their own deadline). Close it
by hand — `warden close <event-id> --why "…"` — rather than re-dispatching;
re-dispatching spends an episode to reproduce the same refusal. Details:
`warden-item-closure`.

## 3. Sweep the open PRs, do not admire them

Run this whenever a fix round ends, and any time he complains about rot. Enumerate
across his repos, then give **every** PR a disposition — no PR may stay in the
"open, older than a few days, nobody knows" state:

```bash
for r in <repos>; do gh pr list --repo jkrumm/$r --state open \
  --json number,title,isDraft,createdAt \
  --template '{{range .}}#{{.number}} draft={{.isDraft}} {{.createdAt}} {{.title}}{{"\n"}}{{end}}'; done
```

Per PR, in this order:

1. **Supersede check first.** Many stale PRs are already fixed on master
   (`gh api repos/jkrumm/<r>/commits/master`) or replaced by a newer PR/session.
   Closing one as superseded requires proof that the successor carries everything
   the closed one did — otherwise the close loses the fix. Close with a comment
   naming the successor, then confirm the change really is on master.
2. **Review through the house route**, not by eye: `sideclaw review --pr <n>
   --repo <r> --json` (multi-angle + adversary). Skip it for a genuinely trivial
   diff, but say why.
3. **Merge.** `gh pr ready <n>` first — a draft is inert (no merge, no review,
   nothing sees it). Then merge and delete the branch.
4. **Deploy, then verify the deployed artifact** (§4).
5. **Owner-decision PRs are not merged on your judgement** — a huge diff, a body
   that itself says "do not merge until the owner has reviewed", a product
   direction, a restart window. File it into the awaiting-owner list (§2) with one
   line on what he must decide, and let the rest of the sweep keep running.

Do not fight over a PR another lane is already working: the sweep and Warden can
both pick up the same PR, so check first. When two merges do land anyway, one
supersedes the other — recoverable — whereas two lanes each closing the other's
work is not.

## 4. "Deployed" means the artifact, verified at the source

Every claim in an agent's closing summary is a self-report. Verify, then relay:

- **Merge:** `gh pr view <n> --json state,mergedAt` plus the repo's master head.
- **Deploy:** the *live* thing — the running container's image tag on the host,
  the checkout HEAD on the host, the health endpoint. "Merged" and "deployed" are
  different facts, and a deploy poller can lag or skip.
- **Behaviour:** make the fixed code path run once for real (a real job through it,
  a real restart, a real script invocation) and read the record it produced.
- **Counter-check the alarm case.** For anything that suppresses or downgrades an
  alert: prove the alert still fires for a *real* fault, not only that it stopped
  firing. A suppress-the-noise fix that also suppresses the signal is worse than
  the noise.

## 5. Driving the agent that does it

Whether it is a herdr pane agent or a Warden episode: **ask for a report file**
(`/tmp/<task>-report.md`) carrying the handles that matter — PR URL, branch, live
commit, what was verified and how, what is still open. Then watch, don't wait: run
the watcher below as ONE background `terminal` call with `notify=True`, and reply
with the current state plus one clause that the watcher is running.

```zsh
# scripts/watch-pane.sh <pane-id> <report-file> [label] [timeout-s]
# terminal(command="/tmp/watch-pane.sh w1E:pN /tmp/task-report.md warden 7200 > /tmp/watch.log 2>&1",
#          background=True, notify=True)
# exit: 0 finished (idle twice + report non-empty) | 4 idle without report
#       2 blocked (needs the human)                 | 3 timeout | 5 pane gone
PANE=$1; REPORT=$2; LABEL=${3:-$1}; MAX=${4:-10800}
start=$(date +%s); seen=0; idle=0
log() { print -r -- "$(date '+%H:%M:%S') [$LABEL] $*" }
log "watch start pane=$PANE report=$REPORT"
while true; do
  now=$(date +%s); el=$(( now - start ))
  (( el > MAX )) && { log "TERMINAL_STEP=timeout ${el}s"; exit 3 }
  st=$(herdr agent get "$PANE" 2>/dev/null | jq -r '.result.agent.agent_status // "gone"')
  log "status=$st elapsed=${el}s seen=$seen"
  case "$st" in
    working) seen=1; idle=0 ;;
    blocked) log "TERMINAL_STEP=blocked"; exit 2 ;;
    gone|unknown) (( seen == 1 )) && { log "TERMINAL_STEP=pane_gone"; exit 5 } ;;
    idle|done)
      if (( seen == 1 )); then
        idle=$(( idle + 1 ))
        if (( idle >= 2 )); then
          if [[ -s $REPORT ]]; then log "TERMINAL_STEP=finished report=$(wc -c < $REPORT) bytes"; exit 0
          else log "TERMINAL_STEP=idle_no_report"; exit 4; fi
        fi
      fi ;;
  esac
  sleep 60
done
```

Two gates keep that watcher honest, and both matter for any hand-rolled version:
`seen=1` requires a `working` sample before `idle` counts as the end (a freshly
prompted agent, or a stale `done`, reads `idle` immediately), and the **report
file** — not the status word — separates "finished" from "stopped talking".
`blocked` exits at once: an answer-the-dialog state belongs to a human, and waiting
on it burns the whole timeout. `herdr` owns the pane/prompt verb interface;
`background-work-watch` owns the general watcher pattern.

Give the agent the *goal*, not a step list, and end the brief with the report-file
requirement. When a turn ends short of the outcome, prompt the **same** agent
again — it still holds the repo, the diff and the context — instead of starting a
fresh session.

## Pitfalls

- **A pane agent works in the live checkout.** In a repo whose files are symlinked
  live (dotfiles, hermes-agent) its branch *is* the running configuration. After it
  reports done: `git -C <repo> branch --show-current`, then switch back to the
  default branch. The branch is pushed; nothing is lost.
- **A policy change does not wake items already parked on the old policy.**
  `autoMergePaths` and merge gates are read at merge time, so an item blocked for
  "no declared scope" stays blocked after the scope is declared — close or re-drive
  it explicitly.
- **The loop notices a hand-merge on a later tick** (minutes) and may show the stale
  state in between. That is lag, not a second finding.
- **Repeatedly re-opening alerts are usually mis-calibrated monitors**, not code
  bugs: the threshold lives in a UI or a config an episode cannot reach. Fix the
  monitor's own config (export it into the repo that owns it) or the family recurs
  forever.
- **Never thin out a review gate to make a merge possible.** Degrading a check to
  unblock a PR converts a visible failure into an invisible one.
