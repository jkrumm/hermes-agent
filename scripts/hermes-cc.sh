#!/usr/bin/env bash
# hermes-cc — the ONLY way the Hermes agent opens a Claude Code episode.
#
# WHY THIS EXISTS. Hermes observes well and reads repos badly: DeepSeek-V4-Flash
# with a `terminal` tool cannot use a repo's CLAUDE.md, .claude/rules/ or
# .claude/skills/, and that context is exactly what triage needs. So Hermes hands
# the episode to Claude Code instead — but "hand work to a coding agent" composed
# as free-form shell by an LLM is the single worst shape this machine could grow.
# A closed verb set breaks the trade the same way hermes-ops.sh does for infra:
# `hermes-cc.sh dispatch sideclaw` is a benign script call whether or not the LLM
# understood what it was doing.
#
# The design rule to defend in review: NO VERB ACCEPTS A FILESYSTEM PATH, A
# COMMAND, OR A URL. A dispatch names a REPO — a bare name, resolved by this
# script under the single root in config/dispatch-repos.json, which also carries
# the denials and the per-repo tier ceilings. One free-form escape hatch and the
# whole exercise is theatre.
#
# THE BRIEF IS DATA, NEVER COMMAND. It arrives on stdin or via --brief-file, and
# is never taken as an argv string. That is not fussiness: the brief is assembled
# by an LLM out of Slack messages, GitHub issue bodies and log lines, i.e. from
# material an attacker can write. As an argv element it would be composed into a
# shell line and expanded by the shell BEFORE this script ever ran, so `$(...)`
# inside a Slack message would execute. On stdin there is no expansion step. The
# skill instructs Hermes to use a QUOTED heredoc (`<<'BRIEF'`) for the same reason
# one level up.
#
# TIERS — the episode's permission profile, capped per-repo by the dispatch policy.
#   investigate  read-only session, verdict only. Cannot lose anything, so it
#                needs no approval theatre and is safe to permit outright.
#   author       read-only session + a filed GitHub issue. Ungated: an issue is
#                a note on a list, and a wrong one is closed in two seconds.
#   implement    write session in an isolated worktree, branch + DRAFT PR.
#                Requires --why AND --confirm. Never merges, never pushes to a
#                default branch, in ANY repo — including the direct-to-master
#                ones. That deviation from the repo's own convention is the
#                point: the convention was written by a human for their own
#                commits, not for an unattended episode.
# A tier a repo does not allow is REFUSED, never quietly downgraded to a weaker
# run whose caller then believes a PR exists.
#
# THE --confirm GATE IS NOT A FORMALITY. Without it, `implement` prints exactly
# what it would do and exits 0 having changed nothing. --confirm means Johannes
# confirmed, which in Slack means Hermes had to ask him first and he answered.
# An agent that passes --confirm because it "seems fine" has removed the only
# human in the loop; the skill says so in those words.
#
# NO RECURSION. A dispatched episode may never dispatch. Enforced structurally,
# not by instruction: this script refuses to run inside a Claude Code session, and
# the brief handed to an episode never carries a credential that would let it call
# back in.
#
# Secrets resolve through `secrets-run`, the op shim (age-encrypted offline cache
# on this headless mini; live biometric op on the MacBook). A bare `op` here hangs
# on a prompt nobody can answer, which is why the backend marker is a hard gate.
# Today only the recursion guard and the budget need no secret — sideclaw is
# localhost and unauthenticated — but the gate stays so a future authenticated
# endpoint cannot be added without noticing.
#
# AUDIT LOG: ~/Library/Logs/hermes-cc.log, one line per invocation, always —
# including usage errors, refusals and budget denials. Register it with the
# existing com.jkrumm.log-rotate LaunchAgent by adding `hermes-cc.log` to the
# FILES array in dotfiles/scripts/log-rotate.sh (that list is DECLARED, never
# globbed, so an unregistered log is an unbounded log).
#
# TESTS: tests/test_hermes_cc.py (run with
# `~/.hermes/hermes-agent/venv/bin/python3 tests/test_hermes_cc.py`) covers the
# properties above — the closed verb set, argument bounding, the repo policy,
# tier gating, the brief-never-from-argv rule, the recursion guard, the daily
# budget, the --json contract and the audit log — against a stubbed job server,
# never a real one. Re-run it after any edit here.

set -euo pipefail

# Hermes invokes this with a minimal environment. Prepend (not replace) Homebrew
# so `timeout`, `python3` and `secrets-run`'s own deps resolve — same reason
# hermes-liveness.sh does it.
export PATH="/opt/homebrew/bin:/usr/local/bin:$PATH"

# --- config ------------------------------------------------------------------

# sideclaw's always-on job server (LaunchAgent, port 7705). Localhost and
# unauthenticated by design — it is reachable only from this machine.
SIDECLAW_BASE="${HERMES_CC_SIDECLAW_BASE:-http://localhost:7705}"

HERMES_HOME="${HERMES_HOME:-$HOME/.hermes}"
REPOS_JSON="${HERMES_CC_REPOS_JSON:-$HERMES_HOME/config/dispatch-repos.json}"
DB_PATH="${HERMES_CC_DB:-$HERMES_HOME/watchdog.db}"
AUDIT_LOG="${HERMES_CC_LOG:-$HOME/Library/Logs/hermes-cc.log}"

SECRETS_RUN="$HOME/.local/bin/secrets-run"
BACKEND_FILE="${SECRETS_BACKEND_FILE:-${XDG_CONFIG_HOME:-$HOME/.config}/secrets/backend}"

HTTP_TIMEOUT=30
# Ceiling on --wait. `--max-budget-usd` is API-only and does not cap a Max
# session, so every bound here is structural. An investigate episode is 30s-3min;
# 240s leaves headroom without letting a wedged worker hold a Slack turn open
# indefinitely. Past this, --wait gives up and the sweeper owns delivery.
WAIT_TIMEOUT=240
WAIT_INTERVAL=5

# Structural spend ceiling: dispatches opened per rolling calendar day (UTC),
# counted from the dispatches table. Hermes runs unattended and a routing bug
# that opens an episode per Slack message would otherwise burn Max quota silently.
MAX_DISPATCHES_PER_DAY="${HERMES_CC_DAILY_BUDGET:-20}"
# A second, much tighter ceiling for `implement` alone. It is not the same kind
# of spend: an investigate episode is 30s-3min and read-only, an implement one
# runs up to 30 minutes, writes code and opens a PR a human then has to read.
# Counting them against one shared budget would let a bad day of triage consume
# the entire allowance for real changes, and vice versa.
MAX_IMPLEMENT_PER_DAY="${HERMES_CC_IMPLEMENT_BUDGET:-5}"
# How few slots left counts as "approaching a ceiling". Both ceilings report a
# warning from here on, so the last slots are visible BEFORE one of them is the
# one that refuses — a bound that is invisible until it fires reads as an
# arbitrary breakage rather than as a budget, which is exactly how this behaved
# when the counts were only computed inside the refusal path.
BUDGET_WARN_REMAINING=3
IMPLEMENT_WARN_REMAINING=1
# Merges landed per UTC day, its own ceiling again and the tightest of the three.
# A merge is the only act in this script that changes what runs — an issue is
# closed in two seconds and a draft PR is a proposal, but a merged commit is on
# master. Three is deliberately fewer than the five implement episodes that can
# produce candidates: not everything that gets written should land.
MAX_MERGES_PER_DAY="${HERMES_CC_MERGE_BUDGET:-3}"

# --- github ------------------------------------------------------------------
# The `merge` verb is the only one that talks to GitHub directly; every other
# verb reaches it through the episode. The owner is a constant, not a parameter:
# `root` holds only Johannes's own repos, so a PR URL naming any other owner is
# a corrupted record, not a repo to merge into.
GH_API="${HERMES_CC_GH_API:-https://api.github.com}"
GH_OWNER=jkrumm
GH_TOKEN_REF="op://mini/github/token"
GH_TOKEN=""
GH_STATUS=""
GH_BODY=""
MERGES_TODAY=-1
# Repos that require a human PR review, read from the single source of truth the
# branch-protection hook and `github-config.sh` already share. Deriving merge
# eligibility from it rather than from a list here means there is nothing to
# maintain: a repo that requires review can never be auto-merged, and a repo
# added to that file stops being auto-mergeable in the same edit.
PR_REQUIRED_JSON="${HERMES_CC_PR_REQUIRED_JSON:-$HOME/.claude/pr-required-repos.json}"
# Re-checked at merge time against sideclaw's own episode ceilings. The episode
# already refused anything bigger, so this catches only the case that matters:
# something pushed to the branch between the PR opening and now.
MAX_MERGE_FILES=40
MAX_MERGE_LINES=2000

# Brief size cap, matched to sideclaw's own input schema so a rejection happens
# here with a clear message rather than as an opaque job failure two minutes later.
MAX_BRIEF_CHARS=8000
MAX_CONTEXT_CHARS=16000

VALID_TIERS=(investigate author implement)
# Tiers this script can actually execute today. Kept as a separate list from
# VALID_TIERS on purpose: a tier named in the design but not yet wired must be
# refused outright rather than silently downgraded, and that distinction has to
# survive the next tier being added.
BUILT_TIERS=(investigate author implement)
# Tiers that need Johannes to have said yes before they run. The criterion is the
# COST OF BEING WRONG, not "does it mutate anything outside this machine" — `author`
# mutates external state too (it files an issue) and is deliberately ungated, because
# a wrong issue is closed in two seconds and leaves nothing behind. A wrong branch and
# draft PR costs a real review. Kept as its own list rather than hardcoded at the call
# site, so adding a tier forces an answer to that question.
#
# NOTE ON WHAT THIS GATE IS. `--confirm` is a flag on the same invocation, supplied by
# the same agent it constrains — so it is an INSTRUCTION-LEVEL gate, not a cryptographic
# one, and a Hermes that decided to lie could pass it. That is accepted: the threat model
# here is prompt injection reaching a brief, and the brief cannot reach argv (see the
# header). Defending against a wholly-compromised Hermes would need an approval artifact
# minted outside the agent and bound to the repo + brief hash, which is a different design.
# What this gate does buy is that the DEFAULT path stops and asks, and that every skip
# leaves a `mode=planned` / `mode=opened` pair in the audit log to be read after the fact.
GATED_TIERS=(implement)

# --- exit codes --------------------------------------------------------------
# 0 ok · 2 precondition failed · 3 remote failed · 4 budget/policy refusal · 64 usage error
EX_PRECONDITION=2
EX_REMOTE=3
EX_POLICY=4
EX_USAGE=64

# --- global flags ------------------------------------------------------------

JSON=0
CONFIRM=0
DRY_RUN=0
WHY=""
TIER=""
WAIT=0
BRIEF_FILE=""
CONTEXT_FILE=""
ORIGIN_CHANNEL=""
ORIGIN_THREAD=""
ORIGIN_EVENT=""

VERB=""
AUDIT_ARGS=""
AUDIT_TARGET="-"

# Set to 1 the moment an episode is actually opened (or a record actually
# abandoned). The audit line derives `mode` from this rather than from the verb,
# because a verb that was REFUSED must not log as though it ran — that is the
# difference between an audit log and a list of intentions.
DID_MUTATE=0

# Set to 1 when the invocation deliberately stopped to show a plan — a gated tier
# without --confirm, or an unconfirmed cancel. Distinct from both `refused` (a
# guard said no) and `dry-run` (the caller asked for a rehearsal): this one is
# the script waiting on a human, and an audit log that could not tell those three
# apart would make the --confirm gate unverifiable after the fact.
PLANNED=0

# A --json error object cannot simply be printed where it is raised: most come
# from helpers every verb calls inside `$( )`, and a subshell's stdout is captured
# by the assignment and thrown away. So the JSON error is staged here and flushed
# to real stdout by the EXIT trap in the parent, which is the one context
# guaranteed not to be inside a command substitution. Same mechanism, and same
# reason, as hermes-ops.sh.
ERR_JSON_FILE=$(mktemp -t hermes-cc 2>/dev/null || true)
START_EPOCH=$(date +%s)

# Set by any verb that has ALREADY written its own JSON object to stdout. The
# --json contract is one object per invocation; staging a second error object
# behind a payload turns the stream into a JSONDecodeError("Extra data"), which
# for the agent parsing it mid-incident is strictly worse than no output at all.
JSON_EMITTED=0

# --- audit -------------------------------------------------------------------

# Masks anything that looks like a credential before it reaches the log. The verb
# grammar admits no secrets (every argument is an enum, an integer, a repo name or
# a Slack id), so this is a net for the mis-invocation — a pasted bearer token
# where a repo name belongs — not the expected path. Length + mixed case + a digit
# is what a token looks like and what this fleet's identifiers are not. op:// refs
# and env var NAMES stay readable: they are what you need to chase a dangling ref,
# and neither is a secret. Newlines collapse so one invocation stays one line.
redact() {
  local out="" w
  for w in ${1//$'\n'/ }; do
    if [ ${#w} -ge 24 ] && [[ "$w" == *[A-Z]* ]] && [[ "$w" == *[0-9]* ]] && [[ "$w" != *[/:]* ]]; then
      w="<redacted>"
    fi
    out="$out$w "
  done
  printf '%s' "${out% }"
}

audit() {
  local rc=$?
  local ts dur mode
  # Flush a staged --json error first: this is the only frame guaranteed to own
  # the real stdout. See ERR_JSON_FILE above.
  if [ -n "$ERR_JSON_FILE" ]; then
    [ -s "$ERR_JSON_FILE" ] && cat "$ERR_JSON_FILE"
    rm -f "$ERR_JSON_FILE"
  fi
  ts=$(date -u +%Y-%m-%dT%H:%M:%SZ)
  dur=$(( $(date +%s) - START_EPOCH ))
  # An audit line that cannot distinguish "printed a plan" from "opened a Max
  # session against a repo" is not an audit line. Reads are `read`; `dispatch` is
  # the only verb that spends anything, and `cancel` is the only other mutation.
  # `refused` is its own mode precisely because it is the interesting one: a
  # refusal that logged as `opened` would hide the guard doing its job.
  case "$VERB" in
    merge)
      # `merged` is its own mode and not folded into `opened`. Grepping this log
      # for what actually landed on a default branch is the reason the log exists,
      # and a merge that reads as "opened an episode" makes that ungreppable.
      if [ "$DID_MUTATE" = 1 ]; then mode="merged"
      elif [ "$DRY_RUN" = 1 ]; then mode="dry-run"
      elif [ "$PLANNED" = 1 ]; then mode="planned"
      else mode="refused"; fi ;;
    dispatch|cancel)
      if [ "$DID_MUTATE" = 1 ]; then mode="opened"
      elif [ "$DRY_RUN" = 1 ]; then mode="dry-run"
      elif [ "$PLANNED" = 1 ]; then mode="planned"
      else mode="refused"; fi ;;
    *) mode="read" ;;
  esac
  mkdir -p "$(dirname "$AUDIT_LOG")" 2>/dev/null || true
  # `approved_by` is the Slack user id whose click signed this invocation, and it is
  # the only field here the agent could not have written for itself — which is exactly
  # why it belongs in the log. Absent (`-`) on every ungated verb.
  printf '%s | verb=%s | mode=%s | tier=%s | args=%s | target=%s | rc=%s | dur=%ss | approved_by=%s | why=%s\n' \
    "$ts" "${VERB:--}" "$mode" "${TIER:--}" "$(redact "${AUDIT_ARGS:--}")" "$AUDIT_TARGET" \
    "$rc" "$dur" "${APPROVED_BY:--}" "$(redact "${WHY:--}")" \
    >> "$AUDIT_LOG" 2>/dev/null || true
  exit "$rc"
}
trap audit EXIT

# --- errors ------------------------------------------------------------------

_err() {
  local code=$1; shift
  if [ "$JSON" = 1 ] && [ "$JSON_EMITTED" != 1 ] && [ -n "$ERR_JSON_FILE" ]; then
    MSG="$*" ERRVERB="$VERB" CODE="$code" python3 -c '
import json, os
print(json.dumps({"verb": os.environ["ERRVERB"] or None, "ok": False,
                  "exitCode": int(os.environ["CODE"]),
                  "error": os.environ["MSG"]}, indent=2))
' > "$ERR_JSON_FILE"
  else
    printf 'hermes-cc: %s\n' "$*" >&2
  fi
  exit "$code"
}

usage_err()  { _err "$EX_USAGE" "$@"; }
precond_err(){ _err "$EX_PRECONDITION" "$@"; }
remote_err() { _err "$EX_REMOTE" "$@"; }
policy_err() { _err "$EX_POLICY" "$@"; }

need() { command -v "$1" >/dev/null 2>&1 || precond_err "missing required tool: $1"; }

in_list() {
  local needle=$1; shift
  local x
  for x in "$@"; do [ "$x" = "$needle" ] && return 0; done
  return 1
}

# --- preconditions -----------------------------------------------------------

# THE RECURSION GUARD. A dispatched episode must never dispatch: that is the one
# cycle the two-door design forbids, and instructing a model not to do it is not
# an enforcement mechanism. Claude Code exports these into every session and tool
# subprocess, so a `claude -p` worker that reaches for this script stops here —
# whatever its prompt says, and whatever an injected brief talked it into.
require_no_recursion() {
  local marker
  for marker in CLAUDE_CODE_SESSION CLAUDECODE CLAUDE_SESSION_ID; do
    if [ -n "${!marker:-}" ]; then
      policy_err "refusing to run inside a Claude Code session ($marker is set): a dispatched episode may never dispatch"
    fi
  done
  if [ "${CLAUDE_ENTRYPOINT:-}" = "worker" ]; then
    policy_err "refusing to run inside a sideclaw worker session (CLAUDE_ENTRYPOINT=worker): a dispatched episode may never dispatch"
  fi
}

# The marker tells us which secrets backend `secrets-run` will use, and that is
# the difference between "resolves from the sealed cache in 0.3s" and "blocks
# forever on a biometric prompt". `cache` is the mini, the machine Hermes runs on.
# `op` is a human's MacBook — allowed only with a TTY attached, because that is
# the only state in which someone can answer the prompt. Anything else fails fast
# rather than hanging. Same signal remote-dev.sh and hermes-ops.sh key off.
require_backend() {
  local backend
  backend=$(cat "$BACKEND_FILE" 2>/dev/null || true)
  case "$backend" in
    cache) : ;;
    op)
      [ -t 0 ] || precond_err "secrets backend is 'op' and there is no TTY — a biometric prompt would hang here. Run this on the Mac mini (backend 'cache') or from an interactive shell."
      ;;
    *)
      precond_err "no secrets backend marker at $BACKEND_FILE — refusing to run rather than hang on an interactive 'op' prompt. This script belongs on the Mac mini."
      ;;
  esac
  [ -x "$SECRETS_RUN" ] || precond_err "secrets-run not found at $SECRETS_RUN"
}

# --- repo resolution ---------------------------------------------------------

# Set by resolve_repo. Never assembled from caller input.
REPO_PATH=""
REPO_MAX_TIER=""

# The property that matters is unchanged: a path never crosses this interface. The caller
# says `sideclaw`, this resolves `~/SourceRoot/sideclaw`. What changed (see the rationale
# in dispatch-repos.json) is that the set of names is DISCOVERED under a single root
# rather than enumerated, because an enumeration silently rots — it listed 22 repos while
# 30 sat on disk, and a missing entry was indistinguishable from a deliberate denial.
#
# Composing a path from caller input is exactly the step the old map lookup did not take,
# so the shape check carries the weight now and is deliberately stricter than "characters
# that could appear in a repo name":
#
#   - The old class [A-Za-z0-9_.-] ADMITS "." and ".." — inert as a dict key, a traversal
#     the moment it is joined onto a root. Both are rejected by name, as is any leading
#     dot (there is no dispatchable repo called .git or .config, and every such name is
#     either hidden state or an escape attempt).
#   - No separator can survive the class, so the name is always a single segment.
#   - And none of that is trusted on its own: the resolved checkout's parent must BE the
#     resolved root, which is what stops a symlinked entry from pointing outside it.
resolve_repo() {
  local name=$1 out
  case "$name" in
    ''|.|..|.*|*[!A-Za-z0-9_.-]*) usage_err "not a repo name: $name" ;;
  esac
  [ -f "$REPOS_JSON" ] || precond_err "dispatch policy not found at $REPOS_JSON"
  out=$(NAME="$name" REPOS_JSON="$REPOS_JSON" python3 -c '
import json, os, sys

VALID = ("investigate", "author", "implement")

with open(os.environ["REPOS_JSON"]) as f:
    policy = json.load(f)

root = os.path.realpath(os.path.expanduser(policy.get("root", "~/SourceRoot")))
default_tier = policy.get("defaultTier", "investigate")
deny = set(policy.get("deny", []))
overrides = {}
for tier, names in (policy.get("tiers") or {}).items():
    # An unknown tier KEY must not be ignored. Ignoring it would silently drop every repo
    # under it to defaultTier — which, with defaultTier=author, quietly PROMOTES the
    # read-only floor repos. A typo here has to be loud.
    if tier not in VALID:
        sys.stderr.write("unknown tier %r in `tiers` (must be one of: %s)\n"
                         % (tier, ", ".join(VALID)))
        sys.exit(2)
    for n in names:
        overrides[n] = tier

if default_tier not in VALID:
    sys.stderr.write("unrecognized defaultTier %r (must be one of: %s)\n"
                     % (default_tier, ", ".join(VALID)))
    sys.exit(2)

# deny and tiers disagreeing is a contradiction, not a precedence question. Picking a
# winner would mean one of the two readings of this file is wrong and nobody is told.
both = deny & set(overrides)
if both:
    sys.stderr.write("named in both `deny` and `tiers`: %s\n" % ", ".join(sorted(both)))
    sys.exit(2)

def discoverable():
    try:
        entries = os.listdir(root)
    except OSError:
        return []
    out = []
    for n in sorted(entries):
        if n.startswith(".") or n in deny:
            continue
        p = os.path.join(root, n)
        if os.path.isdir(p) and os.path.exists(os.path.join(p, ".git")):
            out.append(n)
    return out

name = os.environ["NAME"]

if name in deny:
    sys.stderr.write("denied by policy\n")
    sys.exit(3)

path = os.path.join(root, name)
real = os.path.realpath(path)
# Confinement, checked against the REAL path on both sides: the checkout must sit
# directly in the root, not merely start with its prefix.
if os.path.dirname(real) != root:
    sys.stderr.write("resolves outside %s\n" % root)
    sys.exit(3)

# A name that is simply misspelled lands here, not on the denial branch — so this is the
# one failure where listing what DOES resolve helps the caller fix itself. The denial
# branch deliberately stays silent about the rest of the root.
if not os.path.isdir(real) or not os.path.exists(os.path.join(real, ".git")):
    sys.stderr.write("no git checkout at %s\ndispatchable: %s\n"
                     % (path, ", ".join(discoverable())))
    # A name someone deliberately wrote into `tiers` is expected to exist, so its absence
    # is an infrastructure problem to report. Any other name is discovered, so its absence
    # is a misspelling to retry. Same condition, two different things to do about it.
    sys.exit(5 if name in overrides else 4)

print(real)
print(overrides.get(name, default_tier))
') || {
    local rc=$?
    case "$rc" in
      2) precond_err "dispatch policy at $REPOS_JSON is malformed (see above). Refusing rather than defaulting — a policy that does not parse must never read as a permissive one." ;;
      3) usage_err "repo '$name' is not dispatchable: denied by policy, or it resolves outside the dispatch root. This is deliberate, not an oversight — do not offer to add it." ;;
      4) usage_err "repo '$name' has no git checkout under the dispatch root (see the dispatchable list above)" ;;
      5) precond_err "repo '$name' carries a tier in $REPOS_JSON but has no checkout under the dispatch root — the policy names a repo this machine does not have" ;;
      *) precond_err "could not resolve repo '$name'" ;;
    esac
  }
  REPO_PATH=$(printf '%s' "$out" | sed -n 1p)
  REPO_MAX_TIER=$(printf '%s' "$out" | sed -n 2p)
  # The ceiling has to FAIL CLOSED on a malformed value. tier_rank maps anything it does
  # not recognize to 99, which is above every real tier — so a typo in the policy
  # ("implment") would silently lift the cap entirely and hand a write episode to a repo
  # meant to be read-only. The python above rejects an unknown tier key, but this stays:
  # it is the check that holds if the two ever disagree about what a valid tier is.
  in_list "$REPO_MAX_TIER" "${VALID_TIERS[@]}" \
    || precond_err "repo '$name' resolved to an unrecognized tier '$REPO_MAX_TIER' via $REPOS_JSON (must be one of: ${VALID_TIERS[*]}). Refusing rather than defaulting — a malformed ceiling must never read as a permissive one."
}

# The requested tier must be (a) a real tier, (b) implemented, and (c) within the
# repo's own ceiling. Each failure gets its own message: "not built yet" and "this
# repo does not allow that" are different problems with different fixes, and
# collapsing them would send the caller to edit the wrong file.
resolve_tier() {
  local requested=$1 name=$2
  in_list "$requested" "${VALID_TIERS[@]}" \
    || usage_err "unknown tier: $requested (must be one of: ${VALID_TIERS[*]})"
  in_list "$requested" "${BUILT_TIERS[@]}" \
    || policy_err "tier '$requested' is not implemented yet (Phase 4) — refusing rather than silently downgrading to a read-only run that produces no artifact"
  local rank_req rank_max
  rank_req=$(tier_rank "$requested")
  rank_max=$(tier_rank "$REPO_MAX_TIER")
  [ "$rank_req" -le "$rank_max" ] \
    || policy_err "repo '$name' is capped at tier '$REPO_MAX_TIER' by the dispatch policy; '$requested' was requested"
}

# Ranks are compared as `requested <= ceiling`. The unknown case returns 99 — deliberately
# ABOVE every real tier, so an unrecognized *request* is refused. That is the safe direction
# for the left-hand side and the wrong one for the right, which is why `resolve_repo`
# validates the ceiling against VALID_TIERS before it ever gets here rather than relying on
# this default to be safe in both positions. It cannot be: one constant cannot fail closed
# at both ends of a comparison.
# One predicate for "does this tier need a human", and one for "is it still waiting on
# them". Three call sites asked that question inline before; three copies of a security
# condition is three chances for one of them to drift out of step with the others.
tier_is_gated() { in_list "$TIER" "${GATED_TIERS[@]}"; }
awaiting_confirm() { tier_is_gated && [ "$CONFIRM" != 1 ]; }

tier_rank() {
  case "$1" in
    investigate) printf '1' ;;
    author)      printf '2' ;;
    implement)   printf '3' ;;
    *)           printf '99' ;;
  esac
}

# --- brief -------------------------------------------------------------------

# Set by read_brief / read_context. Held in a variable, never in argv, and passed
# to sideclaw inside a JSON body built by python3 from the environment — so it is
# never re-parsed by a shell on the way out either.
BRIEF=""
CONTEXT=""

read_brief() {
  if [ -n "$BRIEF_FILE" ]; then
    [ -f "$BRIEF_FILE" ] || usage_err "--brief-file not found: $BRIEF_FILE"
    BRIEF=$(cat -- "$BRIEF_FILE")
  else
    # No TTY check that would block: when a human runs this interactively without
    # piping anything, `cat` would hang on an empty terminal. Refuse instead, and
    # say which of the two shapes to use.
    [ ! -t 0 ] || usage_err "no brief on stdin. Pass it with a QUOTED heredoc (hermes-cc.sh dispatch <repo> <<'BRIEF' ... BRIEF) or --brief-file <path>. The brief is never an argv string — see the header."
    BRIEF=$(cat)
  fi
  BRIEF=$(printf '%s' "$BRIEF" | sed -e 's/[[:space:]]*$//')
  [ -n "${BRIEF//[[:space:]]/}" ] || usage_err "brief is empty"
  [ "${#BRIEF}" -le "$MAX_BRIEF_CHARS" ] \
    || usage_err "brief is ${#BRIEF} chars, over the $MAX_BRIEF_CHARS limit — summarize it, or attach the bulk with --context-file"
}

read_context() {
  [ -n "$CONTEXT_FILE" ] || return 0
  [ -f "$CONTEXT_FILE" ] || usage_err "--context-file not found: $CONTEXT_FILE"
  CONTEXT=$(cat -- "$CONTEXT_FILE")
  [ "${#CONTEXT}" -le "$MAX_CONTEXT_CHARS" ] \
    || usage_err "context is ${#CONTEXT} chars, over the $MAX_CONTEXT_CHARS limit"
}

# --- origin projections ------------------------------------------------------

# Slack ids and the watchdog event id are bounded by shape before they are stored:
# they are written into the dispatch record that the sweeper later reads to decide
# where to post, so a malformed one is a message delivered somewhere unintended.
valid_origin() {
  if [ -n "$ORIGIN_CHANNEL" ]; then
    case "$ORIGIN_CHANNEL" in
      C[A-Z0-9]*) : ;;
      *) usage_err "not a Slack channel id: $ORIGIN_CHANNEL (expected C…)" ;;
    esac
    case "$ORIGIN_CHANNEL" in
      *[!A-Z0-9]*) usage_err "not a Slack channel id: $ORIGIN_CHANNEL" ;;
    esac
  fi
  if [ -n "$ORIGIN_THREAD" ]; then
    case "$ORIGIN_THREAD" in
      ''|*[!0-9.]*) usage_err "not a Slack thread ts: $ORIGIN_THREAD (expected 1234567890.123456)" ;;
    esac
    [ -n "$ORIGIN_CHANNEL" ] || usage_err "--origin-thread needs --origin-channel: a thread ts alone cannot be delivered to"
  fi
  if [ -n "$ORIGIN_EVENT" ]; then
    case "$ORIGIN_EVENT" in
      ''|*[!0-9]*) usage_err "--origin-event must be a watchdog events.id integer (got: $ORIGIN_EVENT)" ;;
    esac
  fi
}

# --- dispatch record ---------------------------------------------------------

# Lives in the same SQLite file as the watchdog's `events`, which is the mini's one
# durable Hermes store and already holds the incidents a dispatch links back to.
# DDL is idempotent and additive — `events` is never touched. Timestamps are ISO-8601
# TEXT, matching watchdog-poll.py so the two tables join without conversion.
DB_SCHEMA="
CREATE TABLE IF NOT EXISTS dispatches (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    job_id TEXT NOT NULL UNIQUE,
    tier TEXT NOT NULL,
    repo TEXT NOT NULL,
    brief TEXT NOT NULL,
    why TEXT,
    origin_channel TEXT,
    origin_thread_ts TEXT,
    origin_event_id INTEGER,
    status TEXT NOT NULL,
    verdict_json TEXT,
    artifact_url TEXT,
    created_at TEXT NOT NULL,
    finished_at TEXT,
    reported_at TEXT
);
CREATE INDEX IF NOT EXISTS idx_dispatches_open ON dispatches(status) WHERE reported_at IS NULL;
CREATE INDEX IF NOT EXISTS idx_dispatches_created ON dispatches(created_at);

-- The approval ledger for gated verbs. A row is minted here by the plan branch and
-- decided by a Slack button click, which lands in the gateway process — see
-- plugins/dispatch-approval/. Note what is NOT trusted: every column on this table is
-- writable by anything running as this uid, the agent included. Only the signature
-- column means anything, and it is verified against a public key whose private half
-- never leaves gateway memory. The rest of the row is rendering and sweep convenience.
-- (No backticks in this string: DB_SCHEMA is double-quoted shell, so they would run.)
CREATE TABLE IF NOT EXISTS dispatch_approvals (
    nonce TEXT PRIMARY KEY,
    verb TEXT NOT NULL,
    repo TEXT NOT NULL,
    tier TEXT NOT NULL,
    payload_hash TEXT NOT NULL,
    created_at TEXT NOT NULL,
    expires_at TEXT NOT NULL,
    channel TEXT,
    decision TEXT,
    decided_at TEXT,
    decided_by TEXT,
    signature TEXT,
    spent_at TEXT
);
CREATE INDEX IF NOT EXISTS idx_approvals_hash ON dispatch_approvals(payload_hash);
"

# Every DB helper passes values as bound parameters from the environment. No verb
# accepts SQL, and none is assembled from caller input — same rule as the paths.
db_py() {
  DB_PATH="$DB_PATH" DB_SCHEMA="$DB_SCHEMA" python3 -c "
import json, os, sqlite3, sys
conn = sqlite3.connect(os.environ['DB_PATH'])
conn.row_factory = sqlite3.Row
conn.executescript(os.environ['DB_SCHEMA'])
# Additive, idempotent, and outside DB_SCHEMA on purpose: CREATE TABLE IF NOT
# EXISTS is a no-op against the table that already exists on this machine, so a
# column added to it there would never appear. Same shape as the events.dispatch_id
# migration in watchdog-poll.py.
if 'merged_at' not in {r[1] for r in conn.execute('PRAGMA table_info(dispatches)')}:
    conn.execute('ALTER TABLE dispatches ADD COLUMN merged_at TEXT')
$1
conn.commit()
conn.close()
"
}

# The structural budget, in three deliberately separate pieces.
#
# `budget_counts` READS. It never refuses, and every verb that reports anything
# calls it — including the ones that consume nothing. Counts come from the table
# rather than a counter file: the table is the record, and a count that can drift
# from it is not a budget. The implement count is read unconditionally, not only
# when the current tier is `implement`, because a caller running a read-only
# episode still needs to see how much of the write allowance is left before it
# plans one.
#
# `check_budget` REFUSES, from counts already read. Both ceilings name the env
# var that raises them in the refusal text: an escape hatch only discoverable by
# reading this script is not an escape hatch.
#
# `budget_json` / `budget_text` RENDER. Every emitter reports the same object, so
# the ceilings are visible on the way up rather than only at the moment one of
# them says no.
BUDGET_USED=-1
BUDGET_IMPL=-1

budget_counts() {
  local counts
  counts=$(db_py '
import datetime as dt
today = dt.datetime.now(dt.timezone.utc).date().isoformat()
n = conn.execute("SELECT COUNT(*) FROM dispatches WHERE created_at >= ?", (today,)).fetchone()[0]
t = conn.execute("SELECT COUNT(*) FROM dispatches WHERE created_at >= ? AND tier = ?",
                 (today, "implement")).fetchone()[0]
print(n)
print(t)
') || precond_err "could not read the dispatch budget from $DB_PATH"
  BUDGET_USED=$(printf '%s' "$counts" | sed -n 1p)
  BUDGET_IMPL=$(printf '%s' "$counts" | sed -n 2p)
  case "$BUDGET_USED$BUDGET_IMPL" in
    ''|*[!0-9]*) precond_err "unexpected budget count from $DB_PATH: $counts" ;;
  esac
}

check_budget() {
  [ "$BUDGET_USED" -ge 0 ] || budget_counts
  [ "$BUDGET_USED" -lt "$MAX_DISPATCHES_PER_DAY" ] \
    || policy_err "daily dispatch budget exhausted ($BUDGET_USED/$MAX_DISPATCHES_PER_DAY opened today, UTC — resets at 00:00 UTC). This is a structural ceiling on unattended Max spend, not a rate limit. To proceed now, raise it deliberately: HERMES_CC_DAILY_BUDGET=<n> hermes-cc.sh dispatch …"
  if [ "$TIER" = implement ]; then
    [ "$BUDGET_IMPL" -lt "$MAX_IMPLEMENT_PER_DAY" ] \
      || policy_err "daily implement budget exhausted ($BUDGET_IMPL/$MAX_IMPLEMENT_PER_DAY opened today, UTC — resets at 00:00 UTC). Implement is the expensive tier and each episode produces a PR a human has to read, so it has its own ceiling; the shared budget still has $(( MAX_DISPATCHES_PER_DAY - BUDGET_USED )) slot(s) left for the read-only tiers, which is where triage should go. To proceed now, raise it deliberately: HERMES_CC_IMPLEMENT_BUDGET=<n> hermes-cc.sh dispatch …"
  fi
}

# Rendered once per invocation and handed to the emitters as E_BUDGET, rather
# than reassembled inside each python fragment. Prints nothing when the counts
# were never read, and the emitters then omit the key entirely — a null `budget`
# would read as "there is no budget", which is the opposite of true.
budget_json() {
  [ "$BUDGET_USED" -ge 0 ] || return 0
  E_USED="$BUDGET_USED" E_IMPL="$BUDGET_IMPL" E_MAX="$MAX_DISPATCHES_PER_DAY" \
  E_IMPLMAX="$MAX_IMPLEMENT_PER_DAY" E_WARN="$BUDGET_WARN_REMAINING" \
  E_IWARN="$IMPLEMENT_WARN_REMAINING" python3 -c '
import json, os
used, impl = int(os.environ["E_USED"]), int(os.environ["E_IMPL"])
mx, imx = int(os.environ["E_MAX"]), int(os.environ["E_IMPLMAX"])
rem, irem = max(mx - used, 0), max(imx - impl, 0)
out = {"usedToday": used, "max": mx, "remaining": rem,
       "implementToday": impl, "implementMax": imx, "implementRemaining": irem}
warn = []
if rem <= int(os.environ["E_WARN"]):
    warn.append(
        f"{rem} of {mx} dispatches left today (UTC day, resets 00:00). "
        + ("The next dispatch will be REFUSED. " if rem == 0 else "")
        + "This is a spend ceiling, not a rate limit — raise it deliberately with "
          "HERMES_CC_DAILY_BUDGET=<n> if it is wrong, do not retry into it.")
if irem <= int(os.environ["E_IWARN"]):
    warn.append(
        f"{irem} of {imx} implement dispatches left today. "
        + ("The next implement will be REFUSED (read-only tiers are unaffected). "
           if irem == 0 else "")
        + "Raise it deliberately with HERMES_CC_IMPLEMENT_BUDGET=<n> if it is wrong.")
if warn:
    out["warning"] = " ".join(warn)
print(json.dumps(out))
'
}

budget_text() {
  [ "$BUDGET_USED" -ge 0 ] || return 0
  printf 'budget: %s/%s dispatches today · implement %s/%s\n' \
    "$BUDGET_USED" "$MAX_DISPATCHES_PER_DAY" "$BUDGET_IMPL" "$MAX_IMPLEMENT_PER_DAY"
}

# =============================================================================
# SIGNED APPROVAL
# =============================================================================
#
# What `--confirm` alone could never be. The flag is supplied by the same agent it
# constrains, so it is an instruction; this is an artifact. A Slack button click is
# witnessed by the gateway process, which signs it with an Ed25519 key whose private
# half exists only in that process's memory and is minted fresh at every start
# (plugins/dispatch-approval/). This script holds only the public half.
#
# The threat this closes is the one the bridge actually has: prompt injection reaching
# a brief. Injection produces words. Words cannot mint a signature, and they cannot
# cause a Slack interaction payload to exist. Every other column on `dispatch_approvals`
# is writable by this uid and is therefore treated as untrusted decoration — the
# signature is the only thing consulted.
#
# It does NOT defend against a wholly-compromised Hermes with a debugger on the gateway.
# That was never the claim, and the script's header says so about `--confirm` too.
#
# FAILS CLOSED, EVERYWHERE. No public key, no plugin, no gateway, an expired row, a
# hash that does not match the brief in hand, an already-spent approval, a missing
# verifier interpreter — every one of them refuses the verb. The cost of this
# machinery being broken is that nothing writes, never that something writes unchecked.
APPROVAL_TTL_MINUTES="${HERMES_CC_APPROVAL_TTL:-30}"
APPROVAL_PUBKEY="${HERMES_CC_APPROVAL_PUBKEY:-$HERMES_HOME/dispatch-approval.pub}"
# The verifier needs `cryptography`, which the system python3 does not have and the
# gateway's venv does. Resolved rather than assumed so a moved install fails with a
# sentence instead of a traceback.
APPROVAL_PY="${HERMES_CC_APPROVAL_PY:-$HERMES_HOME/hermes-agent/venv/bin/python3}"

# Must agree byte-for-byte with payload_hash() in plugins/dispatch-approval/__init__.py.
# tests/test_dispatch_approval.py asserts the two implementations agree; if you change
# one, the test fails rather than the gate silently never matching.
#
# `why` is in the hash for the same reason the brief is. The button message shows
# Johannes the stated reason, so that is what he approves; if --confirm could carry a
# different one, the audit log would record a justification nobody ever saw. Binding it
# means changing the reason costs a fresh approval, exactly like changing the brief.
approval_hash() {
  A_VERB="$1" A_REPO="$2" A_TIER="$3" A_BODY="$4" A_WHY="${5:-}" python3 -c '
import hashlib, os
h = hashlib.sha256()
for part in (os.environ["A_VERB"], os.environ["A_REPO"], os.environ["A_TIER"],
             os.environ["A_BODY"], os.environ["A_WHY"]):
    h.update(part.encode("utf-8")); h.update(b"\x00")
print(h.hexdigest())
'
}

# Post the plan with Approve/Deny buttons. Best effort by design: if Slack is
# unreachable the row is still on file, the caller still sees its plan, and the verb
# still refuses for want of a signature. A failure here must not look like a refusal.
post_approval_buttons() {
  local nonce="$1" verb="$2" repo="$3" tier="$4" chan="$5" why="$6" detail="${7:-}"
  [ -n "$chan" ] || { warn_approval "no --origin-channel, so no buttons could be posted"; return 0; }
  local token="${SLACK_BOT_TOKEN:-}"
  if [ -z "$token" ] && command -v secrets-run >/dev/null 2>&1; then
    token=$(secrets-run read op://hermes/slack/bot-token 2>/dev/null || true)
  fi
  [ -n "$token" ] || { warn_approval "no SLACK_BOT_TOKEN, so no buttons could be posted"; return 0; }

  local payload
  payload=$(P_NONCE="$nonce" P_VERB="$verb" P_REPO="$repo" P_TIER="$tier" \
            P_CHAN="$chan" P_THREAD="$ORIGIN_THREAD" P_WHY="$why" P_DETAIL="$detail" \
            P_TTL="$APPROVAL_TTL_MINUTES" python3 -c '
import json, os
# The detail line is what makes a merge click a decision rather than a rubber stamp:
# without the PR, its size and its link, the human is approving a job id.
parts = [":lock: *Approval needed* — `%s` %s on `%s`"
         % (os.environ["P_VERB"], os.environ["P_TIER"], os.environ["P_REPO"])]
if os.environ.get("P_DETAIL"):
    parts.append(os.environ["P_DETAIL"])
parts.append("*Why:* %s" % (os.environ["P_WHY"] or "(none given)"))
parts.append("_Expires in %s min._" % os.environ["P_TTL"])
text = "\n".join(parts)
body = {
    "channel": os.environ["P_CHAN"],
    "text": text,
    "blocks": [
        {"type": "section", "text": {"type": "mrkdwn", "text": text}},
        {"type": "actions", "elements": [
            {"type": "button", "style": "primary",
             "text": {"type": "plain_text", "text": "Approve"},
             "action_id": "hermes_cc_approve", "value": os.environ["P_NONCE"]},
            {"type": "button", "style": "danger",
             "text": {"type": "plain_text", "text": "Deny"},
             "action_id": "hermes_cc_deny", "value": os.environ["P_NONCE"]},
        ]},
    ],
}
if os.environ.get("P_THREAD"):
    body["thread_ts"] = os.environ["P_THREAD"]
print(json.dumps(body))
') || { warn_approval "could not build the button payload"; return 0; }

  # Token on stdin as a curl config, never argv — this machine runs triage that reads
  # `ps` output, same rule the merge verb follows for the GitHub credential.
  local out
  out=$(printf 'header = "Authorization: Bearer %s"\n' "$token" | \
        curl -sS -m 15 -K - \
             -H 'Content-type: application/json; charset=utf-8' \
             -X POST --data "$payload" \
             "${HERMES_CC_SLACK_API:-https://slack.com/api}/chat.postMessage" 2>/dev/null) || {
    warn_approval "Slack post failed"; return 0; }
  printf '%s' "$out" | python3 -c '
import json, sys
try:
    d = json.load(sys.stdin)
except Exception:
    sys.exit(1)
sys.exit(0 if d.get("ok") else 1)
' 2>/dev/null || warn_approval "Slack rejected the button message: $(printf '%s' "$out" | head -c 200)"
  return 0
}

warn_approval() {
  [ "$JSON" = 1 ] || printf 'note: %s\n' "$1" >&2
}

# Mint the pending row and ask. Returns the nonce on stdout.
mint_approval() {
  local verb="$1" repo="$2" tier="$3" body="$4" why="${5:-}"
  local nonce hash
  nonce=$(python3 -c 'import secrets; print(secrets.token_hex(16))') \
    || precond_err "could not mint an approval nonce"
  hash=$(approval_hash "$verb" "$repo" "$tier" "$body" "$why") \
    || precond_err "could not hash the approval payload"

  # Supersede any older pending request for the identical payload, so a caller that
  # re-plans the same thing twice does not leave two live buttons that both work.
  A_NONCE="$nonce" A_VERB="$verb" A_REPO="$repo" A_TIER="$tier" A_HASH="$hash" \
  A_CHAN="$ORIGIN_CHANNEL" A_TTL="$APPROVAL_TTL_MINUTES" db_py '
import datetime as dt
now = dt.datetime.now(dt.timezone.utc)
exp = now + dt.timedelta(minutes=int(os.environ["A_TTL"]))
conn.execute("DELETE FROM dispatch_approvals WHERE payload_hash = ? AND decision IS NULL",
             (os.environ["A_HASH"],))
conn.execute(
    "INSERT INTO dispatch_approvals(nonce,verb,repo,tier,payload_hash,created_at,expires_at,channel) "
    "VALUES(?,?,?,?,?,?,?,?)",
    (os.environ["A_NONCE"], os.environ["A_VERB"], os.environ["A_REPO"], os.environ["A_TIER"],
     os.environ["A_HASH"], now.isoformat(), exp.isoformat(), os.environ["A_CHAN"] or None),
)
' || precond_err "could not record the approval request in $DB_PATH"

  post_approval_buttons "$nonce" "$verb" "$repo" "$tier" "$ORIGIN_CHANNEL" "$WHY"
  printf '%s' "$nonce"
}

# The gate. Refuses unless a signed, unexpired, unspent approval exists for exactly
# this payload — and marks it spent in the same statement that accepts it, so an
# approval is good for one invocation.
require_signed_approval() {
  local verb="$1" repo="$2" tier="$3" body="$4" why="${5:-}"
  local hash
  hash=$(approval_hash "$verb" "$repo" "$tier" "$body" "$why") \
    || precond_err "could not hash the approval payload"

  [ -f "$APPROVAL_PUBKEY" ] || policy_err \
    "no approval public key at $APPROVAL_PUBKEY — the dispatch-approval plugin is not loaded, so no click can be verified. Check 'hermes plugins list' and the gateway log, then re-plan."
  [ -x "$APPROVAL_PY" ] || policy_err \
    "no verifier interpreter at $APPROVAL_PY (needs the 'cryptography' module). Set HERMES_CC_APPROVAL_PY if the venv moved."

  local verdict
  verdict=$(A_HASH="$hash" A_PUB="$APPROVAL_PUBKEY" A_PY="$APPROVAL_PY" DB_PATH="$DB_PATH" \
    "$APPROVAL_PY" -c '
import datetime as dt, os, sqlite3, sys
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
from cryptography.exceptions import InvalidSignature

pub = Ed25519PublicKey.from_public_bytes(bytes.fromhex(open(os.environ["A_PUB"]).read().strip()))
conn = sqlite3.connect(os.environ["DB_PATH"]); conn.row_factory = sqlite3.Row
now = dt.datetime.now(dt.timezone.utc)

rows = conn.execute(
    "SELECT * FROM dispatch_approvals WHERE payload_hash = ? AND spent_at IS NULL "
    "ORDER BY decided_at DESC", (os.environ["A_HASH"],)).fetchall()
if not rows:
    print("none"); sys.exit(0)

for r in rows:
    if r["decision"] is None:
        continue
    if r["decision"] != "approve":
        print("denied"); sys.exit(0)
    if not r["signature"]:
        continue
    try:
        exp = dt.datetime.fromisoformat(r["expires_at"])
    except Exception:
        continue
    if exp.tzinfo is None:
        exp = exp.replace(tzinfo=dt.timezone.utc)
    if exp < now:
        continue
    # v1 canonical form — mirrors canonical_message() in the plugin.
    msg = "|".join(["v1", r["nonce"], r["payload_hash"], r["decision"],
                    r["decided_by"] or "", r["expires_at"]]).encode("utf-8")
    try:
        pub.verify(bytes.fromhex(r["signature"]), msg)
    except (InvalidSignature, ValueError):
        continue
    # Spend it here, guarded, so two concurrent invocations cannot both claim it.
    cur = conn.execute("UPDATE dispatch_approvals SET spent_at = ? WHERE nonce = ? AND spent_at IS NULL",
                       (now.isoformat(), r["nonce"]))
    conn.commit()
    if cur.rowcount == 1:
        print("ok " + (r["decided_by"] or "?")); sys.exit(0)
print("pending"); sys.exit(0)
') || precond_err "could not check the approval ledger in $DB_PATH"

  case "$verdict" in
    ok\ *)
      APPROVED_BY="${verdict#ok }"
      return 0 ;;
    denied)
      policy_err "that request was denied in Slack. Nothing was dispatched." ;;
    pending)
      policy_err "the approval for this request has not been clicked yet (or it expired). Re-plan to get a fresh set of buttons." ;;
    none)
      policy_err "no approval on file for this exact request. Run the verb WITHOUT --confirm first: it posts Approve/Deny buttons in Slack, and --confirm only works once Approve has been clicked. Note the approval is bound to the brief — any edit to it needs a fresh approval." ;;
    *)
      precond_err "unexpected approval verdict: $verdict" ;;
  esac
}

APPROVED_BY=""

record_dispatch() {
  JOB_ID="$1" R_TIER="$TIER" R_REPO="$2" R_BRIEF="$BRIEF" R_WHY="$WHY" \
  R_CHAN="$ORIGIN_CHANNEL" R_THREAD="$ORIGIN_THREAD" R_EVENT="$ORIGIN_EVENT" \
  db_py '
import datetime as dt
now = dt.datetime.now(dt.timezone.utc).isoformat()
conn.execute(
    "INSERT INTO dispatches(job_id,tier,repo,brief,why,origin_channel,origin_thread_ts,"
    "origin_event_id,status,created_at) VALUES(?,?,?,?,?,?,?,?,?,?)",
    (os.environ["JOB_ID"], os.environ["R_TIER"], os.environ["R_REPO"],
     os.environ["R_BRIEF"], os.environ["R_WHY"] or None,
     os.environ["R_CHAN"] or None, os.environ["R_THREAD"] or None,
     int(os.environ["R_EVENT"]) if os.environ["R_EVENT"] else None,
     "queued", now),
)
' || precond_err "could not record the dispatch in $DB_PATH"
}

# --- sideclaw transport ------------------------------------------------------

# The job body is serialized by python3 from the environment, never by string
# concatenation — the brief contains arbitrary user text and would otherwise have
# to be JSON-escaped by hand in shell, which is the same class of mistake as
# interpolating it into a command.
sideclaw_submit() {
  local body out status resp
  need curl
  body=$(S_CWD="$REPO_PATH" S_TIER="$TIER" S_BRIEF="$BRIEF" S_CONTEXT="$CONTEXT" python3 -c '
import json, os
params = {"cwd": os.environ["S_CWD"], "tier": os.environ["S_TIER"],
          "brief": os.environ["S_BRIEF"]}
if os.environ.get("S_CONTEXT"):
    params["context"] = os.environ["S_CONTEXT"]
print(json.dumps({"tool": "dispatch", "params": params}))
') || precond_err "could not build the dispatch request body"

  out=$(printf '%s' "$body" | timeout "$HTTP_TIMEOUT" curl -sS -w '\n%{http_code}' \
      --connect-timeout 5 --max-time "$HTTP_TIMEOUT" \
      -H 'Content-Type: application/json' --data-binary @- \
      "${SIDECLAW_BASE}/api/jobs") \
    || remote_err "sideclaw job submit failed (is the LaunchAgent up? \`curl ${SIDECLAW_BASE}/health\`)"
  status="${out##*$'\n'}"
  resp="${out%$'\n'"${status}"}"
  [ "$status" = "200" ] || remote_err "sideclaw returned HTTP $status: $(printf '%s' "$resp" | head -c 300)"
  printf '%s' "$resp"
}

sideclaw_get() {
  local id=$1 out status resp
  need curl
  out=$(timeout "$HTTP_TIMEOUT" curl -sS -w '\n%{http_code}' \
      --connect-timeout 5 --max-time "$HTTP_TIMEOUT" "${SIDECLAW_BASE}/api/jobs/${id}") \
    || remote_err "sideclaw job poll failed (is the LaunchAgent up?)"
  status="${out##*$'\n'}"
  resp="${out%$'\n'"${status}"}"
  [ "$status" = "200" ] || remote_err "sideclaw returned HTTP $status for job $id"
  printf '%s' "$resp"
}

valid_job_id() {
  case "$1" in
    ''|*[!A-Za-z0-9-]*) usage_err "not a job id: $1" ;;
  esac
}

# --- github transport --------------------------------------------------------

# The token is read once per invocation and never reaches argv. `curl -H
# "Authorization: Bearer $T"` would put it in the process table, and this machine
# runs agents that read `ps` output as triage evidence — so the header goes in on
# stdin as a curl config and the request body, when there is one, goes in as a
# file.
gh_token() {
  [ -n "$GH_TOKEN" ] && return 0
  GH_TOKEN=$(timeout 15 "$SECRETS_RUN" read "$GH_TOKEN_REF" 2>/dev/null) \
    || precond_err "could not read $GH_TOKEN_REF through secrets-run — the merge needs a GitHub credential and this machine resolves it from the sealed cache"
  [ -n "$GH_TOKEN" ] || precond_err "$GH_TOKEN_REF resolved empty. Re-seed the cache (make secrets-seed in dotfiles, biometric, MacBook-only)"
}

# One bounded REST call. The path is assembled only from values already validated
# — the owner constant, the repo from the dispatch row, an integer PR number —
# never from caller input.
#
# It sets GH_BODY and GH_STATUS rather than printing the body, and that is not a
# style choice: `body=$(github_api …)` runs the function in a SUBSHELL, so the
# status it recorded — and the token it cached — would be discarded at the closing
# paren, leaving every caller checking a stale GH_STATUS from the previous call.
# The status is half the answer here (404 on the pull request and 404 on the
# branch delete are not the same severity), so it has to survive.
github_api() {
  local method=$1 path=$2 body_file="${3:-}" out
  gh_token
  local -a args=(-sS -w '\n%{http_code}' --connect-timeout 5 --max-time "$HTTP_TIMEOUT"
                 -X "$method" -H "Accept: application/vnd.github+json"
                 -H "X-GitHub-Api-Version: 2022-11-28")
  if [ -n "$body_file" ]; then
    args+=(-H "Content-Type: application/json" --data-binary "@$body_file")
  fi
  out=$(printf 'header = "Authorization: Bearer %s"\n' "$GH_TOKEN" \
        | timeout "$HTTP_TIMEOUT" curl -K - "${args[@]}" "${GH_API}${path}") \
    || remote_err "GitHub request failed: $method $path"
  GH_STATUS="${out##*$'\n'}"
  GH_BODY="${out%$'\n'"${GH_STATUS}"}"
}

# Pull one field out of a JSON response without letting a missing key look like a
# value. Prints nothing and returns 1 when the path is absent, so `|| refuse` is
# always available at the call site.
json_field() {
  RESP="$1" FIELD="$2" python3 -c '
import json, os, sys
try:
    obj = json.loads(os.environ["RESP"])
except ValueError:
    sys.exit(1)
for part in os.environ["FIELD"].split("."):
    if not isinstance(obj, dict) or part not in obj:
        sys.exit(1)
    obj = obj[part]
if obj is None:
    sys.exit(1)
print(obj if not isinstance(obj, bool) else str(obj).lower())
'
}

# =============================================================================
# VERBS
# =============================================================================

cmd_dispatch() {
  local name="${1:-}"
  [ -n "$name" ] || usage_err "usage: hermes-cc.sh dispatch <repo> [--tier investigate] [--wait] [--json] <<'BRIEF' ... BRIEF"
  require_no_recursion
  require_backend
  need python3
  need timeout

  resolve_repo "$name"
  TIER="${TIER:-investigate}"
  resolve_tier "$TIER" "$name"
  # --why is checked before the brief is read: it is a property of the request,
  # not of the payload, so a caller that forgot it should be told immediately
  # rather than after piping in 8k of material.
  if tier_is_gated && [ -z "$WHY" ]; then
    usage_err "tier '$TIER' requires --why \"<reason>\". It lands in the audit log and is the record of why an unattended episode was allowed to write. There is no default."
  fi
  valid_origin
  read_brief
  read_context
  AUDIT_TARGET="${name}:${TIER}"

  # Two different reasons to stop here, one output. An explicit --dry-run is the
  # caller asking what would happen; a gated tier without --confirm is this
  # script refusing to act until a human has. Both change nothing and exit 0 —
  # exit 0 because printing the plan IS the successful outcome of that request,
  # and a non-zero code would read as "the dispatch failed" to whatever parses it.
  # PLANNED is set ONLY for the gated case, so the audit line can tell "stopped to ask a
  # human" from "the caller asked for a rehearsal" — an explicit --dry-run on a gated tier
  # is still a rehearsal, and the audit `case` checks DRY_RUN first for exactly that reason.
  # Counted before the plan branch precisely because a plan consumes nothing: the
  # rehearsal is where a caller decides whether to spend a slot, so it is the one
  # place the standing counts matter most. Reading them never refuses.
  budget_counts

  if awaiting_confirm; then PLANNED=1; fi
  if [ "$DRY_RUN" = 1 ] || [ "$PLANNED" = 1 ]; then
    # A rehearsal asks nobody for anything. Only the gated stop-to-ask mints an
    # approval request, and it does so before the plan is printed so the plan can
    # say the buttons are waiting.
    if [ "$PLANNED" = 1 ] && [ "$DRY_RUN" != 1 ]; then
      mint_approval "dispatch" "$name" "$TIER" "$BRIEF" "$WHY" >/dev/null
    fi
    emit_plan "$name"
    return 0
  fi

  # The gate, before anything is spent or submitted. It refuses unless a Slack button
  # was actually clicked for this exact brief — see the SIGNED APPROVAL section.
  if tier_is_gated; then
    require_signed_approval "dispatch" "$name" "$TIER" "$BRIEF" "$WHY"
  fi

  # The refusal is checked after validation so a refused invocation does not
  # consume a slot, and before submission so an over-budget one never opens a
  # session.
  check_budget

  local resp job_id
  resp=$(sideclaw_submit)
  job_id=$(printf '%s' "$resp" | python3 -c '
import json, sys
print(json.load(sys.stdin)["job"]["id"])
') || remote_err "sideclaw accepted the job but returned no id: $(printf '%s' "$resp" | head -c 300)"
  valid_job_id "$job_id"
  record_dispatch "$job_id" "$name"
  DID_MUTATE=1
  AUDIT_TARGET="${name}:${TIER}:${job_id}"

  # The row is in the table now, so the counts the emitters report must include
  # this dispatch — otherwise the number a caller sees is always one behind the
  # one the next refusal will use.
  budget_counts

  if [ "$WAIT" = 1 ]; then
    wait_for "$job_id" "$name"
    return $?
  fi

  emit_submitted "$job_id" "$name"
}

# In-turn polling for the short tiers: an investigate episode is 30s-3min, which
# fits inside a Slack turn, so Hermes can answer in the thread it is already in
# rather than waiting for the sweeper. Past WAIT_TIMEOUT this gives up and says so
# — the dispatch record is already written, so the sweeper owns delivery from
# there and nothing is lost by not waiting longer.
wait_for() {
  local job_id=$1 name=$2 elapsed=0 resp status
  while :; do
    resp=$(sideclaw_get "$job_id")
    status=$(printf '%s' "$resp" | python3 -c '
import json, sys
print(json.load(sys.stdin)["job"]["status"])
') || remote_err "could not read job status for $job_id"
    case "$status" in
      done|failed|interrupted) break ;;
    esac
    [ "$elapsed" -lt "$WAIT_TIMEOUT" ] || { emit_timeout "$job_id" "$name" "$elapsed"; return 0; }
    sleep "$WAIT_INTERVAL"
    elapsed=$(( elapsed + WAIT_INTERVAL ))
  done
  # Returning a terminal verdict from --wait IS the delivery: --wait exists only
  # so a caller sitting in a live Slack turn can answer in the thread it is
  # already in, so by the time this returns the verdict is in that turn's hands.
  # Stamp `reported_at` here or the sweeper posts the same verdict again five
  # minutes later. A --wait that TIMED OUT deliberately does not reach this line —
  # there the sweeper genuinely does still owe the message.
  sync_record "$job_id" "$resp" reported
  emit_result "$job_id" "$name" "$resp"
}

# Fold a terminal job's outcome back into its dispatch row. The second argument
# decides whether the delivery debt is settled: `reported` stamps `reported_at`,
# anything else leaves it NULL. That split is the whole difference between the two
# callers — `--wait` hands the verdict straight to a live turn, whereas `status`
# is a poll that tells nobody, and stamping there would silently drop a message
# the sweeper still owes the origin thread.
sync_record() {
  JOB_ID="$1" RESP="$2" REPORTED="${3:-no}" db_py '
import datetime as dt
job = json.loads(os.environ["RESP"])["job"]
now = dt.datetime.now(dt.timezone.utc).isoformat()
reported = now if os.environ["REPORTED"] == "reported" else None
result = job.get("result")
# artifact_url is lifted out of the verdict into its own column so "what did this
# dispatch produce" is a column read for the briefing and the watchdog, not a JSON
# parse. Same denormalization dispatch-sweep.py does, deliberately — whichever of
# the two settles a given dispatch has to leave the row in the same shape.
# Normalized to NULL rather than stored verbatim: "" and NULL would be the same fact
# ("no artifact") in two shapes, and every reader filters on IS NOT NULL.
artifact = (result.get("artifactUrl") or None) if isinstance(result, dict) else None
conn.execute(
    "UPDATE dispatches SET status=?, verdict_json=?, artifact_url=?, finished_at=?, "
    "reported_at=COALESCE(reported_at, ?) WHERE job_id=?",
    (job["status"],
     json.dumps(result) if result is not None else None,
     artifact, now, reported, os.environ["JOB_ID"]),
)
' || precond_err "could not update the dispatch record for $1"
}

cmd_status() {
  local job_id="${1:-}"
  [ -n "$job_id" ] || usage_err "usage: hermes-cc.sh status <job-id> [--json]"
  valid_job_id "$job_id"
  need python3
  AUDIT_TARGET="$job_id"
  local resp
  resp=$(sideclaw_get "$job_id")
  case "$(printf '%s' "$resp" | python3 -c 'import json,sys; print(json.load(sys.stdin)["job"]["status"])')" in
    done|failed|interrupted) sync_record "$job_id" "$resp" ;;
  esac
  # A poll is where an agent decides whether to open the next episode, so it
  # reports the same standing counts a dispatch does.
  budget_counts
  emit_result "$job_id" "-" "$resp"
}

cmd_list() {
  local scope="${1:-open}"
  in_list "$scope" open today all \
    || usage_err "unknown list scope: $scope (must be one of: open today all)"
  need python3
  AUDIT_TARGET="$scope"
  local rows
  rows=$(SCOPE="$scope" db_py '
import datetime as dt
scope = os.environ["SCOPE"]
if scope == "open":
    q = "SELECT * FROM dispatches WHERE status IN (?,?,?) OR reported_at IS NULL ORDER BY id DESC LIMIT 50"
    rows = conn.execute(q, ("queued", "running", "pending")).fetchall()
elif scope == "today":
    today = dt.datetime.now(dt.timezone.utc).date().isoformat()
    rows = conn.execute("SELECT * FROM dispatches WHERE created_at >= ? ORDER BY id DESC", (today,)).fetchall()
else:
    rows = conn.execute("SELECT * FROM dispatches ORDER BY id DESC LIMIT 50").fetchall()
out = []
for r in rows:
    d = dict(r)
    d.pop("brief", None)
    d.pop("verdict_json", None)
    out.append(d)
print(json.dumps(out))
') || precond_err "could not read dispatches from $DB_PATH"
  budget_counts
  emit_list "$scope" "$rows"
}

# NOTE — this does NOT kill a running episode. sideclaw has no cancel endpoint
# (server/routes/jobs.ts exposes submit / list / get only), and inventing one that
# silently fails to stop the worker would be worse than not having it. What this
# does is abandon the LOCAL record: the return path stops chasing the job and the
# sweeper will not post its verdict. The episode itself runs to completion and
# expires against sideclaw's own timeout. The help text says so in those words.
cmd_cancel() {
  local job_id="${1:-}"
  [ -n "$job_id" ] || usage_err "usage: hermes-cc.sh cancel <job-id> --why \"<reason>\" [--confirm]"
  valid_job_id "$job_id"
  [ -n "$WHY" ] || usage_err "cancel requires --why \"<reason>\" (it is what lands in the audit log)"
  need python3
  AUDIT_TARGET="$job_id"

  if [ "$CONFIRM" != 1 ]; then PLANNED=1; fi
  if [ "$CONFIRM" != 1 ] || [ "$DRY_RUN" = 1 ]; then
    emit_cancel_plan "$job_id"
    return 0
  fi

  local n
  n=$(JOB_ID="$job_id" db_py '
import datetime as dt
now = dt.datetime.now(dt.timezone.utc).isoformat()
cur = conn.execute(
    "UPDATE dispatches SET status=?, reported_at=?, finished_at=COALESCE(finished_at,?) "
    "WHERE job_id=? AND reported_at IS NULL",
    ("abandoned", now, now, os.environ["JOB_ID"]),
)
print(cur.rowcount)
') || precond_err "could not update the dispatch record for $job_id"
  [ "$n" != "0" ] || precond_err "no open dispatch with job id $job_id (already reported, abandoned, or never recorded)"
  DID_MUTATE=1
  emit_cancelled "$job_id"
}

# =============================================================================
# MERGE
# =============================================================================
#
# The only verb that changes what RUNS. Everything else in this script produces a
# proposal — an issue, a branch, a draft PR — that a human reads before it means
# anything. This one lands a commit on a default branch with no human in the loop,
# by owner decision (2026-08-02), and it inverts a design statement sideclaw's
# `openPullRequest` makes in a comment: "un-drafting is not something the episode
# can do for itself". It is now something a bounded verb can do for it. So the
# bounds have to carry the weight the human used to:
#
#   - It merges only a PR THIS BRIDGE OPENED. The argument is a job id, not a PR
#     number and not a URL: the PR is looked up from the dispatch row, so there is
#     no shape of caller input that names an arbitrary pull request. That is the
#     same property the repo argument has, for the same reason.
#   - It never merges where a human review is required. Eligibility is derived
#     from `pr-required-repos.json`, the file the branch-protection hook and
#     `github-config.sh` already share — not from a list kept here that would
#     drift out of agreement with them.
#   - Every bound the episode was held to is re-checked against the CURRENT head:
#     the base is the default branch, the head is a `dispatch/…` branch in this
#     same repo (never a fork), no `.github/workflows|actions` path is touched,
#     the size ceilings still hold. The merge itself pins that head SHA, so a push
#     landing between inspection and merge fails the merge rather than riding it.
#   - `mergeable_state` must be exactly `clean`. `blocked` (a required review or
#     check is missing) and `unstable` (something is failing) are refusals, not
#     judgement calls.
#
# What it deliberately does NOT do: merge anything it did not open, force-push,
# retarget a base, override a protection rule, or merge a PR a human has pushed
# to. On each of those it stops and says which one.

# Terminal-ish states this verb refuses to look at. Kept as data so the refusal
# can name the actual state rather than "not mergeable".
merge_precheck_repo() {
  local repo=$1 verdict
  [ -f "$PR_REQUIRED_JSON" ] \
    || precond_err "cannot verify merge eligibility: $PR_REQUIRED_JSON is missing. That file decides which repos require a human review, so an unreadable one is a refusal, never an assumption."
  verdict=$(R_REPO="$repo" python3 - "$PR_REQUIRED_JSON" <<'PY'
import json, os, sys
try:
    with open(sys.argv[1]) as fh:
        data = json.load(fh)
except (OSError, ValueError) as exc:
    print("ERR " + str(exc))
    raise SystemExit(0)
repos = data.get("repos")
if not isinstance(repos, list) or not all(isinstance(r, str) for r in repos):
    print("ERR `repos` is not a list of strings")
    raise SystemExit(0)
print("YES" if os.environ["R_REPO"] in repos else "NO")
PY
) || precond_err "could not read $PR_REQUIRED_JSON"
  case "$verdict" in
    NO)  : ;;
    YES) policy_err "$repo requires a human pull-request review (it is listed in $PR_REQUIRED_JSON, the same file the branch-protection hook enforces). This verb will not merge there — say the PR is ready and let Johannes merge it." ;;
    *)   precond_err "could not read merge eligibility from $PR_REQUIRED_JSON: ${verdict#ERR }" ;;
  esac
}

# Split for the same reason the dispatch budget is: the count is read on every
# path that reports, the refusal happens once. After a merge lands, the emitter
# needs the new count — and calling the refusing half there would refuse on the
# merge that just succeeded.
merge_count() {
  local used
  used=$(db_py '
import datetime as dt
today = dt.datetime.now(dt.timezone.utc).date().isoformat()
print(conn.execute("SELECT COUNT(*) FROM dispatches WHERE merged_at >= ?", (today,)).fetchone()[0])
') || precond_err "could not read the merge budget from $DB_PATH"
  case "$used" in ''|*[!0-9]*) precond_err "unexpected merge count from $DB_PATH: $used" ;; esac
  MERGES_TODAY="$used"
}

check_merge_budget() {
  merge_count
  local used="$MERGES_TODAY"
  [ "$used" -lt "$MAX_MERGES_PER_DAY" ] \
    || policy_err "daily merge budget exhausted ($used/$MAX_MERGES_PER_DAY landed today, UTC — resets at 00:00 UTC). This is the tightest ceiling in the script because a merge is the only act here that changes what runs. To proceed now, raise it deliberately: HERMES_CC_MERGE_BUDGET=<n> hermes-cc.sh merge …"
}

cmd_merge() {
  local job_id="${1:-}"
  [ -n "$job_id" ] || usage_err "usage: hermes-cc.sh merge <job-id> --why \"<reason>\" --confirm [--json]"
  require_no_recursion
  require_backend
  need python3
  need curl
  need timeout
  valid_job_id "$job_id"
  [ -n "$WHY" ] || usage_err "merge requires --why \"<reason>\". It is the audit record of why an unattended episode was allowed to land code on a default branch. There is no default."
  AUDIT_TARGET="$job_id"

  # --- the record decides which PR, and whether there is one -----------------
  local row tier repo artifact status
  # NULLs are normalized in python, not with COALESCE: a SQL string literal needs
  # single quotes, and this block is expanded inside db_py's double-quoted python
  # source, where escaping them is a trap with no upside.
  row=$(JOB_ID="$job_id" db_py '
r = conn.execute("SELECT tier, repo, status, artifact_url, merged_at "
                 "FROM dispatches WHERE job_id=?", (os.environ["JOB_ID"],)).fetchone()
if r is None:
    print("MISSING")
else:
    print("\n".join("" if x is None else str(x) for x in r))
') || precond_err "could not read the dispatch record for $job_id"
  [ "$row" != "MISSING" ] || precond_err "no dispatch recorded with job id $job_id. This verb merges only a pull request this bridge opened, so a job it has no record of is not mergeable by it."
  tier=$(printf '%s' "$row" | sed -n 1p)
  repo=$(printf '%s' "$row" | sed -n 2p)
  status=$(printf '%s' "$row" | sed -n 3p)
  artifact=$(printf '%s' "$row" | sed -n 4p)
  local already; already=$(printf '%s' "$row" | sed -n 5p)
  TIER="$tier"

  [ -z "$already" ] || policy_err "dispatch $job_id was already merged at $already. Re-merging is not a retry — if something is wrong with what landed, that is a new change, not a second merge."
  [ "$tier" = implement ] \
    || policy_err "dispatch $job_id ran at tier '$tier', which produces no pull request. Only an implement episode can be merged."
  [ "$status" = "done" ] \
    || policy_err "dispatch $job_id finished as '$status', not 'done'. A merge follows a successful episode, never a failed or still-running one."
  [ -n "$artifact" ] \
    || policy_err "dispatch $job_id recorded no artifact URL — the episode pushed a branch but never opened a pull request (its verdict says why). There is nothing to merge; open the PR by hand if the branch is worth keeping."

  # The URL is parsed, never trusted. Owner is pinned to the constant, and the
  # repo segment must agree with the repo the row says was dispatched — a record
  # whose two halves disagree is corrupt, and corrupt is a refusal.
  local url_re='^https://github\.com/([A-Za-z0-9_.-]+)/([A-Za-z0-9_.-]+)/pull/([0-9]+)$'
  [[ "$artifact" =~ $url_re ]] \
    || policy_err "dispatch $job_id recorded an artifact that is not a pull request URL: $artifact"
  local owner="${BASH_REMATCH[1]}" url_repo="${BASH_REMATCH[2]}" pr="${BASH_REMATCH[3]}"
  [ "$owner" = "$GH_OWNER" ] \
    || policy_err "the recorded pull request belongs to '$owner', not $GH_OWNER. This bridge dispatches only into Johannes's own repos; a foreign owner means a corrupted record."
  [ "$url_repo" = "$repo" ] \
    || policy_err "the dispatch record disagrees with itself: repo '$repo' but a pull request in '$url_repo'."

  # --- the policy still has to allow it, now ---------------------------------
  # Re-resolved rather than trusted from the row: the policy may have changed
  # since the episode ran, and the answer that matters is today's.
  resolve_repo "$repo"
  [ "$(tier_rank "$REPO_MAX_TIER")" -ge "$(tier_rank implement)" ] \
    || policy_err "$repo's ceiling is now '$REPO_MAX_TIER', below the implement tier that produced this pull request. The policy changed after the episode ran; that is a refusal, not a stale record."
  merge_precheck_repo "$repo"
  check_merge_budget

  # --- the pull request has to still be what was inspected -------------------
  local pr_json repo_json files_json
  github_api GET "/repos/$owner/$repo/pulls/$pr"
  [ "$GH_STATUS" = "200" ] \
    || remote_err "GitHub returned HTTP $GH_STATUS for $owner/$repo#$pr — the recorded pull request could not be read"
  pr_json="$GH_BODY"
  github_api GET "/repos/$owner/$repo"
  [ "$GH_STATUS" = "200" ] || remote_err "GitHub returned HTTP $GH_STATUS reading $owner/$repo"
  repo_json="$GH_BODY"

  local pr_state pr_merged pr_base pr_head pr_head_sha pr_head_repo pr_files pr_add pr_del pr_title default_branch
  pr_state=$(json_field "$pr_json" state) || remote_err "pull request response has no state"
  pr_merged=$(json_field "$pr_json" merged) || pr_merged=false
  pr_base=$(json_field "$pr_json" base.ref) || remote_err "pull request response has no base ref"
  pr_head=$(json_field "$pr_json" head.ref) || remote_err "pull request response has no head ref"
  pr_head_sha=$(json_field "$pr_json" head.sha) || remote_err "pull request response has no head sha"
  pr_head_repo=$(json_field "$pr_json" head.repo.full_name) || pr_head_repo=""
  pr_files=$(json_field "$pr_json" changed_files) || pr_files=0
  pr_add=$(json_field "$pr_json" additions) || pr_add=0
  pr_del=$(json_field "$pr_json" deletions) || pr_del=0
  pr_title=$(json_field "$pr_json" title) || pr_title="(untitled)"
  default_branch=$(json_field "$repo_json" default_branch) || remote_err "could not read $repo's default branch"

  [ "$pr_merged" != true ] || policy_err "$owner/$repo#$pr is already merged."
  [ "$pr_state" = open ] || policy_err "$owner/$repo#$pr is '$pr_state', not open."
  [ "$pr_base" = "$default_branch" ] \
    || policy_err "$owner/$repo#$pr targets '$pr_base', not the default branch '$default_branch'. A dispatch PR that has been retargeted is not the thing that was inspected."
  case "$pr_head" in
    dispatch/*) : ;;
    *) policy_err "$owner/$repo#$pr merges '$pr_head', which is not a dispatch/… branch. This verb merges only branches this bridge cut." ;;
  esac
  [ "$pr_head_repo" = "$owner/$repo" ] \
    || policy_err "$owner/$repo#$pr is from '$pr_head_repo', a fork. A fork branch was never inspected by the episode and is never merged here."

  local lines=$(( pr_add + pr_del ))
  [ "$pr_files" -le "$MAX_MERGE_FILES" ] \
    || policy_err "$owner/$repo#$pr touches $pr_files files, over the $MAX_MERGE_FILES-file ceiling. The episode was held to that ceiling, so something has been pushed to the branch since."
  [ "$lines" -le "$MAX_MERGE_LINES" ] \
    || policy_err "$owner/$repo#$pr is $lines changed lines, over the $MAX_MERGE_LINES-line ceiling. The episode was held to that ceiling, so something has been pushed to the branch since."

  github_api GET "/repos/$owner/$repo/pulls/$pr/files?per_page=100"
  [ "$GH_STATUS" = "200" ] || remote_err "GitHub returned HTTP $GH_STATUS listing files on $owner/$repo#$pr"
  files_json="$GH_BODY"
  local forbidden
  forbidden=$(RESP="$files_json" python3 -c '
import json, os, re
bad = [f["filename"] for f in json.loads(os.environ["RESP"])
       if re.match(r"^\.github/(workflows|actions)/", f.get("filename", ""))]
print(",".join(bad))
') || remote_err "could not read the file list for $owner/$repo#$pr"
  [ -z "$forbidden" ] \
    || policy_err "$owner/$repo#$pr touches CI definitions ($forbidden). A dispatch may never change what runs in CI, and merging one that does would launder exactly that."

  local method
  method=$(pick_merge_method "$repo_json") \
    || policy_err "$owner/$repo allows no merge method this verb can use (squash, rebase, merge commit all disabled)."

  # --- the gate --------------------------------------------------------------
  # NOT gated on a signed approval, deliberately (owner decision, restored 2026-08-03).
  # Johannes approved the change when he confirmed the `implement`; merging is finishing
  # the thing he said yes to. A second click per PR trains a rubber stamp, which is worth
  # less than the bounds this verb already carries — job-id lookup rather than a PR
  # number, every implement-time check re-run against the current head, a pinned head SHA
  # on the merge call itself, and its own 3/day ceiling.
  if [ "$CONFIRM" != 1 ]; then PLANNED=1; fi
  if [ "$DRY_RUN" = 1 ] || [ "$CONFIRM" != 1 ]; then
    emit_merge_plan "$owner/$repo" "$pr" "$pr_title" "$pr_head" "$pr_base" "$method" "$pr_files" "$lines"
    return 0
  fi

  # --- land it ---------------------------------------------------------------
  # Ready-for-review first: a draft cannot be merged, and this is the step that
  # used to be the human's click. It is done AFTER every check above, so a PR
  # that fails one is never un-drafted as a side effect of being refused.
  local node_id
  node_id=$(json_field "$pr_json" node_id) || remote_err "pull request response has no node id"
  mark_ready_for_review "$node_id"

  # mergeable is computed asynchronously and is null right after a mutation, so a
  # single read would be a coin flip. Re-read until GitHub has an answer.
  local tries=0 mergeable state_now
  while :; do
    github_api GET "/repos/$owner/$repo/pulls/$pr"
    [ "$GH_STATUS" = "200" ] || remote_err "GitHub returned HTTP $GH_STATUS re-reading $owner/$repo#$pr"
    pr_json="$GH_BODY"
    mergeable=$(json_field "$pr_json" mergeable) || mergeable=""
    state_now=$(json_field "$pr_json" mergeable_state) || state_now=""
    [ -n "$mergeable" ] && [ "$state_now" != unknown ] && break
    tries=$(( tries + 1 ))
    [ "$tries" -lt 5 ] || remote_err "GitHub never finished computing mergeability for $owner/$repo#$pr. Nothing was merged; the pull request is now marked ready for review."
    sleep 2
  done
  [ "$mergeable" = true ] \
    || policy_err "$owner/$repo#$pr is not mergeable (state: $state_now) — usually a conflict with $default_branch. Nothing was merged."
  [ "$state_now" = clean ] \
    || policy_err "$owner/$repo#$pr is '$state_now', not 'clean'. 'blocked' means a required review or status check is missing; 'unstable' means something is failing; 'behind' means the branch needs updating. Each of those is a human's call, not this verb's. Nothing was merged."

  local body_file merge_resp
  body_file=$(mktemp "${TMPDIR:-/tmp}/hermes-cc-merge.XXXXXX") \
    || precond_err "could not create a temp file for the merge request"
  # The head SHA is pinned: every check above was made against it, so a push that
  # lands between the inspection and this call must fail the merge, not ride it.
  M_SHA="$pr_head_sha" M_METHOD="$method" python3 -c '
import json, os
print(json.dumps({"sha": os.environ["M_SHA"], "merge_method": os.environ["M_METHOD"]}))
' > "$body_file" || { rm -f "$body_file"; precond_err "could not build the merge request body"; }
  github_api PUT "/repos/$owner/$repo/pulls/$pr/merge" "$body_file"
  rm -f "$body_file"
  merge_resp="$GH_BODY"
  case "$GH_STATUS" in
    200) : ;;
    409) policy_err "GitHub refused the merge (409): the head moved since it was inspected, or the branch is not in a mergeable state. Nothing was merged. Re-run to inspect the new head." ;;
    405) policy_err "GitHub refused the merge (405): the pull request is not mergeable under this repo's rules. Nothing was merged." ;;
    *)   remote_err "GitHub returned HTTP $GH_STATUS merging $owner/$repo#$pr: $(printf '%s' "$merge_resp" | head -c 300)" ;;
  esac
  DID_MUTATE=1

  local merge_sha; merge_sha=$(json_field "$merge_resp" sha) || merge_sha=""

  # The record is stamped before the branch delete, which is cleanup and is
  # allowed to fail: a merged commit with a leftover branch is untidy, a merge
  # this table does not know about is a second merge waiting to happen.
  JOB_ID="$job_id" db_py '
import datetime as dt
conn.execute("UPDATE dispatches SET merged_at=? WHERE job_id=?",
             (dt.datetime.now(dt.timezone.utc).isoformat(), os.environ["JOB_ID"]))
' || precond_err "MERGED $owner/$repo#$pr but could not stamp the dispatch record — fix $DB_PATH before merging again, or the ceiling will not count this one"

  # Cleanup, and allowed to fail: 422 is "already gone" (the repo deletes on
  # merge), anything else leaves an orphan branch, which is untidy and nothing
  # more. The merge is already recorded.
  local deleted=false
  github_api DELETE "/repos/$owner/$repo/git/refs/heads/$pr_head"
  case "$GH_STATUS" in 204|422) deleted=true ;; esac

  merge_count
  emit_merged "$owner/$repo" "$pr" "$pr_title" "$method" "$merge_sha" "$pr_head" "$deleted"
}

# Squash first: a dispatch branch is one unit of work by construction, and a
# squashed commit is what its history should read as. Rebase next, merge commit
# last — a merge commit on a linear-history repo is refused by GitHub anyway.
pick_merge_method() {
  local repo_json=$1 m
  for m in squash rebase merge; do
    case "$m" in
      squash) json_field "$repo_json" allow_squash_merge | grep -qx true && { printf squash; return 0; } ;;
      rebase) json_field "$repo_json" allow_rebase_merge | grep -qx true && { printf rebase; return 0; } ;;
      merge)  json_field "$repo_json" allow_merge_commit | grep -qx true && { printf merge;  return 0; } ;;
    esac
  done
  return 1
}

# Un-drafting is GraphQL-only — REST has no ready-for-review transition.
mark_ready_for_review() {
  local node_id=$1 body_file resp
  body_file=$(mktemp "${TMPDIR:-/tmp}/hermes-cc-ready.XXXXXX") \
    || precond_err "could not create a temp file for the ready-for-review request"
  M_NODE="$node_id" python3 -c '
import json, os
print(json.dumps({
    "query": "mutation($id:ID!){markPullRequestReadyForReview(input:{pullRequestId:$id})"
             "{pullRequest{isDraft}}}",
    "variables": {"id": os.environ["M_NODE"]},
}))
' > "$body_file" || { rm -f "$body_file"; precond_err "could not build the ready-for-review request"; }
  github_api POST "/graphql" "$body_file"
  rm -f "$body_file"
  resp="$GH_BODY"
  [ "$GH_STATUS" = "200" ] \
    || remote_err "GitHub returned HTTP $GH_STATUS marking the pull request ready for review. Nothing was merged."
  # GraphQL reports errors inside a 200, so the status alone proves nothing.
  printf '%s' "$resp" | python3 -c '
import json, sys
d = json.load(sys.stdin)
sys.exit(1 if d.get("errors") else 0)
' || remote_err "GitHub rejected the ready-for-review mutation: $(printf '%s' "$resp" | head -c 300). Nothing was merged."
}

# =============================================================================
# OUTPUT
# =============================================================================
#
# Exactly one JSON object per invocation under --json, success or failure. Every
# emitter sets JSON_EMITTED so a later _err falls back to stderr rather than
# appending a second object.

emit_submitted() {
  local job_id=$1 name=$2
  if [ "$JSON" = 1 ]; then
    JSON_EMITTED=1
    E_JOB="$job_id" E_REPO="$name" E_TIER="$TIER" E_BUDGET="$(budget_json)" \
    python3 -c '
import json, os
out = {"verb": "dispatch", "ok": True, "jobId": os.environ["E_JOB"],
       "repo": os.environ["E_REPO"], "tier": os.environ["E_TIER"],
       "status": "queued", "waited": False,
       "note": "Episode opened. It is NOT finished — poll with `hermes-cc.sh status "
               + os.environ["E_JOB"] + "`, or let the 5-minute sweeper deliver the "
               "verdict into the origin thread."}
if os.environ.get("E_BUDGET"):
    out["budget"] = json.loads(os.environ["E_BUDGET"])
print(json.dumps(out, indent=2))
'
  else
    printf 'dispatch opened: %s (%s, tier %s)\n' "$job_id" "$name" "$TIER"
    printf 'not finished — poll: hermes-cc.sh status %s\n' "$job_id"
    budget_text
  fi
}

emit_result() {
  local job_id=$1 name=$2 resp=$3
  if [ "$JSON" = 1 ]; then
    JSON_EMITTED=1
    E_JOB="$job_id" E_REPO="$name" E_TIER="${TIER:--}" RESP="$resp" \
    E_BUDGET="$(budget_json)" python3 -c '
import json, os
job = json.loads(os.environ["RESP"])["job"]
result = job.get("result")
r = result if isinstance(result, dict) else {}
# artifactUrl and branch are hoisted to the top level rather than left nested in
# the verdict. They are the only fields a caller ACTS on, and an agent reading
# this should not have to know the verdict object is where a PR link hides.
out = {"verb": "dispatch", "ok": job["status"] == "done",
       "jobId": os.environ["E_JOB"], "repo": os.environ["E_REPO"],
       "tier": os.environ["E_TIER"], "status": job["status"],
       "waited": True, "elapsedMs": job.get("elapsedMs"),
       "artifactUrl": r.get("artifactUrl"), "branch": r.get("branch"),
       "verdict": result, "error": job.get("error")}
if os.environ.get("E_BUDGET"):
    out["budget"] = json.loads(os.environ["E_BUDGET"])
print(json.dumps(out, indent=2))
'
  else
    RESP="$resp" python3 -c '
import json, os
job = json.loads(os.environ["RESP"])["job"]
r = job.get("result") or {}
print(f"status: {job["status"]} ({job.get("elapsedMs", 0)/1000:.0f}s)")
if r:
    print(f"summary: {r.get("summary", "")}")
    print(f"confidence: {r.get("confidence")} | next: {r.get("nextAction")}")
    if r.get("artifactUrl"):
        print(f"artifact: {r["artifactUrl"]}")
    elif r.get("branch"):
        print(f"branch pushed, no PR: {r["branch"]}")
    print()
    print(r.get("verdict", ""))
    print()
    print("recommendation: " + r.get("recommendation", ""))
elif job.get("error"):
    print("error: " + str(job["error"]))
'
    budget_text
  fi
}

emit_timeout() {
  local job_id=$1 name=$2 elapsed=$3
  if [ "$JSON" = 1 ]; then
    JSON_EMITTED=1
    E_JOB="$job_id" E_REPO="$name" E_TIER="$TIER" E_EL="$elapsed" \
    E_BUDGET="$(budget_json)" python3 -c '
import json, os
out = {"verb": "dispatch", "ok": True, "jobId": os.environ["E_JOB"],
       "repo": os.environ["E_REPO"], "tier": os.environ["E_TIER"],
       "status": "running", "waited": True,
       "waitedSeconds": int(os.environ["E_EL"]),
       "note": "Still running after the in-turn wait. The dispatch record is "
               "written, so the sweeper will deliver the verdict into the origin "
               "thread — say so and move on rather than waiting again."}
if os.environ.get("E_BUDGET"):
    out["budget"] = json.loads(os.environ["E_BUDGET"])
print(json.dumps(out, indent=2))
'
  else
    printf 'still running after %ss — the sweeper will deliver it (job %s)\n' "$elapsed" "$job_id"
    budget_text
  fi
}

# The plan. Printed for an explicit --dry-run and for a gated tier awaiting
# --confirm; `needsConfirm` is what tells the two apart, and it is what the agent
# must surface to Johannes before it may pass --confirm. The plan spells out the
# irreversible-looking parts (a branch, a PR) alongside the parts that are
# guaranteed NOT to happen, because "it opens a PR" and "it never merges" are
# both things a human needs before answering yes.
emit_plan() {
  local name=$1 needs_confirm=0
  if awaiting_confirm; then needs_confirm=1; fi
  if [ "$JSON" = 1 ]; then
    JSON_EMITTED=1
    E_REPO="$name" E_TIER="$TIER" E_PATH="$REPO_PATH" E_BRIEF="$BRIEF" E_WHY="$WHY" \
    E_NEEDS="$needs_confirm" E_MAXTIER="$REPO_MAX_TIER" E_BUDGET="$(budget_json)" python3 -c '
import json, os
tier = os.environ["E_TIER"]
needs = os.environ["E_NEEDS"] == "1"
effects = {
    "investigate": ["opens a read-only session inside the repo",
                    "returns a verdict; changes nothing anywhere"],
    "author": ["opens a read-only session inside the repo",
               "files ONE GitHub issue in that repo, or none if it finds nothing worth tracking"],
    "implement": ["cuts a fresh dispatch/… branch in an ISOLATED worktree, never the live checkout",
                  "lets the session edit files and run the validators the repo defines",
                  "commits, pushes that branch, and opens a DRAFT pull request"],
}[tier]
never = ["never merges anything",
         "never pushes to a default branch, in any repo, including direct-to-master ones",
         "never touches .github/workflows or .github/actions",
         "never mutates infrastructure — that is hermes-ops.sh, not this"]
out = {"verb": "dispatch", "ok": True, "dryRun": True, "needsConfirm": needs,
       "repo": os.environ["E_REPO"], "tier": tier,
       "repoMaxTier": os.environ["E_MAXTIER"], "cwd": os.environ["E_PATH"],
       "briefChars": len(os.environ["E_BRIEF"]), "why": os.environ["E_WHY"] or None,
       "wouldDo": effects, "wouldNeverDo": never,
       "note": "nothing ran — no episode was opened and no budget was consumed"}
# The standing counts, reported on the one path that spends nothing. A rehearsal
# is where the decision to spend a slot is actually made, so it is where the
# remaining slots have to be legible.
if os.environ.get("E_BUDGET"):
    out["budget"] = json.loads(os.environ["E_BUDGET"])
if needs:
    out["note"] += (". This tier is GATED: re-invoke with --confirm ONLY after Johannes has "
                    "seen this plan and said yes. Passing --confirm on your own judgement "
                    "removes the only human in the loop.")
print(json.dumps(out, indent=2))
'
  else
    printf 'PLAN — nothing executed.\n'
    printf '  repo:  %s (%s)\n' "$name" "$REPO_PATH"
    printf '  tier:  %s (repo ceiling: %s)\n' "$TIER" "$REPO_MAX_TIER"
    printf '  brief: %s chars\n' "${#BRIEF}"
    [ -n "$WHY" ] && printf '  why:   %s\n' "$WHY"
    budget_text
    if [ "$TIER" = implement ]; then
      printf '  would: isolated worktree -> dispatch/… branch -> draft PR\n'
      printf '  never: merge · push to a default branch · touch CI workflows\n'
    fi
    if [ "$needs_confirm" = 1 ]; then
      printf 'GATED — re-invoke with --confirm only after Johannes has approved this plan.\n'
    else
      printf 'Re-invoke without --dry-run to open the episode.\n'
    fi
  fi
}

emit_list() {
  local scope=$1 rows=$2
  if [ "$JSON" = 1 ]; then
    JSON_EMITTED=1
    E_SCOPE="$scope" ROWS="$rows" E_BUDGET="$(budget_json)" python3 -c '
import json, os
rows = json.loads(os.environ["ROWS"])
out = {"verb": "list", "ok": True, "scope": os.environ["E_SCOPE"],
       "count": len(rows), "dispatches": rows}
if os.environ.get("E_BUDGET"):
    out["budget"] = json.loads(os.environ["E_BUDGET"])
print(json.dumps(out, indent=2))
'
  else
    ROWS="$rows" python3 -c '
import json, os
rows = json.loads(os.environ["ROWS"])
if not rows:
    print("no dispatches")
for r in rows:
    print(f"{r["job_id"][:8]}  {r["status"]:<11} {r["repo"]:<18} {r["tier"]:<11} {r["created_at"][:19]}")
'
    budget_text
  fi
}

emit_cancel_plan() {
  local job_id=$1
  if [ "$JSON" = 1 ]; then
    JSON_EMITTED=1
    E_JOB="$job_id" E_WHY="$WHY" python3 -c '
import json, os
print(json.dumps({"verb": "cancel", "ok": True, "dryRun": True, "confirmed": False,
                  "jobId": os.environ["E_JOB"], "why": os.environ["E_WHY"] or None,
                  "effect": "marks the LOCAL dispatch record abandoned so the sweeper stops "
                            "chasing it. It does NOT kill the running episode — sideclaw has "
                            "no cancel endpoint.",
                  "note": "nothing ran — re-invoke with --confirm to abandon the record"}, indent=2))
'
  else
    printf 'DRY RUN — nothing executed.\n'
    printf '  would abandon the local dispatch record for %s\n' "$job_id"
    printf '  (this does NOT kill the running episode — sideclaw has no cancel endpoint)\n'
    printf 'Re-invoke with --confirm --why "<reason>" to execute.\n'
  fi
}

emit_cancelled() {
  local job_id=$1
  if [ "$JSON" = 1 ]; then
    JSON_EMITTED=1
    E_JOB="$job_id" python3 -c '
import json, os
print(json.dumps({"verb": "cancel", "ok": True, "dryRun": False, "confirmed": True,
                  "jobId": os.environ["E_JOB"], "status": "abandoned",
                  "effect": "local record only — the episode itself runs to completion"}, indent=2))
'
  else
    printf 'abandoned local record for %s (the episode itself still runs)\n' "$job_id"
  fi
}

# The merge plan. Printed for --dry-run and, more importantly, whenever --confirm
# is absent — which is the default. Everything it lists has ALREADY been verified
# against the live pull request by the time this prints: it is a statement of what
# will happen to a PR in exactly this state, not a forecast.
emit_merge_plan() {
  local slug=$1 pr=$2 title=$3 head=$4 base=$5 method=$6 files=$7 lines=$8
  if [ "$JSON" = 1 ]; then
    JSON_EMITTED=1
    E_SLUG="$slug" E_PR="$pr" E_TITLE="$title" E_HEAD="$head" E_BASE="$base" \
    E_METHOD="$method" E_FILES="$files" E_LINES="$lines" E_MERGES="$MERGES_TODAY" \
    E_MERGEMAX="$MAX_MERGES_PER_DAY" E_NEEDS="$([ "$CONFIRM" = 1 ] && echo 0 || echo 1)" \
    python3 -c '
import json, os
needs = os.environ["E_NEEDS"] == "1"
out = {"verb": "merge", "ok": True, "dryRun": True, "needsConfirm": needs,
       "repo": os.environ["E_SLUG"], "pullRequest": int(os.environ["E_PR"]),
       "title": os.environ["E_TITLE"], "head": os.environ["E_HEAD"],
       "base": os.environ["E_BASE"], "mergeMethod": os.environ["E_METHOD"],
       "changedFiles": int(os.environ["E_FILES"]), "changedLines": int(os.environ["E_LINES"]),
       "wouldDo": ["mark the draft pull request ready for review",
                   "merge it into " + os.environ["E_BASE"] + " by " + os.environ["E_METHOD"],
                   "delete the dispatch/… branch"],
       "wouldNeverDo": ["never merge a pull request this bridge did not open",
                        "never merge where a human review is required "
                        "(derived from pr-required-repos.json)",
                        "never merge a fork branch, a retargeted base, or a change "
                        "touching .github/workflows",
                        "never override a failing check or a branch protection rule"],
       "mergeBudget": {"usedToday": int(os.environ["E_MERGES"]),
                       "max": int(os.environ["E_MERGEMAX"])},
       "note": "nothing was merged and nothing was un-drafted"}
if needs:
    out["note"] += (". Re-invoke with --confirm to land it. This is the last point at "
                    "which nothing has changed on GitHub.")
print(json.dumps(out, indent=2))
'
  else
    printf 'PLAN — nothing merged.\n'
    printf '  pr:     %s#%s — %s\n' "$slug" "$pr" "$title"
    printf '  merge:  %s -> %s (%s)\n' "$head" "$base" "$method"
    printf '  size:   %s files, %s lines\n' "$files" "$lines"
    printf '  budget: %s/%s merges today\n' "$MERGES_TODAY" "$MAX_MERGES_PER_DAY"
    [ "$CONFIRM" = 1 ] || printf 'Re-invoke with --confirm to land it.\n'
  fi
}

emit_merged() {
  local slug=$1 pr=$2 title=$3 method=$4 sha=$5 head=$6 deleted=$7
  if [ "$JSON" = 1 ]; then
    JSON_EMITTED=1
    E_SLUG="$slug" E_PR="$pr" E_TITLE="$title" E_METHOD="$method" E_SHA="$sha" \
    E_HEAD="$head" E_DELETED="$deleted" E_MERGES="$MERGES_TODAY" \
    E_MERGEMAX="$MAX_MERGES_PER_DAY" python3 -c '
import json, os
used, mx = int(os.environ["E_MERGES"]), int(os.environ["E_MERGEMAX"])
out = {"verb": "merge", "ok": True, "merged": True,
       "repo": os.environ["E_SLUG"], "pullRequest": int(os.environ["E_PR"]),
       "title": os.environ["E_TITLE"], "mergeMethod": os.environ["E_METHOD"],
       "mergeCommit": os.environ["E_SHA"] or None,
       "branch": os.environ["E_HEAD"],
       "branchDeleted": os.environ["E_DELETED"] == "true",
       "mergeBudget": {"usedToday": used, "max": mx, "remaining": max(mx - used, 0)},
       "note": "This is on the default branch now. Say so plainly, with the "
               "pull request link — a merge is the one outcome here that a human "
               "cannot discover later by reading an open PR list."}
if mx - used <= 1:
    out["mergeBudget"]["warning"] = (
        f"{max(mx - used, 0)} of {mx} merges left today (UTC day). Raise it "
        "deliberately with HERMES_CC_MERGE_BUDGET=<n> if the ceiling is wrong.")
print(json.dumps(out, indent=2))
'
  else
    printf 'MERGED %s#%s (%s) — %s\n' "$slug" "$pr" "$method" "$title"
    [ -n "$sha" ] && printf '  commit: %s\n' "$sha"
    [ "$deleted" = true ] && printf '  branch %s deleted\n' "$head"
    printf '  budget: %s/%s merges today\n' "$MERGES_TODAY" "$MAX_MERGES_PER_DAY"
  fi
}

# =============================================================================

show_help() {
  cat <<'EOF'
hermes-cc — hand a bounded Claude Code episode to one repo, and track it.

  hermes-cc.sh <verb> [args] [--tier T] [--wait] [--json] [--dry-run]
                            [--why "reason"] [--confirm]
                            [--brief-file P] [--context-file P]
                            [--origin-channel C…] [--origin-thread TS]
                            [--origin-event N]

VERBS
  dispatch <repo>      Open an episode inside <repo>. Brief on stdin (quoted
                       heredoc) or --brief-file. --wait polls in-turn.
  status <job-id>      Poll one episode; folds a terminal outcome into its record.
  list [open|today|all]  List dispatch records. Default: open.
  merge <job-id>       Land the draft PR an `implement` episode opened: mark it
                       ready for review, merge it, delete the branch. Needs
                       --why AND --confirm; without --confirm it prints the plan
                       and changes nothing. Takes a JOB ID, never a PR number —
                       it merges only what this bridge opened.
  cancel <job-id>      Abandon the LOCAL record. Needs --why and --confirm.

TIERS
  investigate  read-only session, verdict only. Default. Ungated.
  author       read-only session + one filed GitHub issue. Ungated.
  implement    write session in an ISOLATED worktree, branch + DRAFT PR.
               Requires --why AND --confirm. Without --confirm it prints the
               plan and exits 0 having done nothing. It never merges and never
               pushes to a default branch, in ANY repo — including the
               direct-to-master ones, deliberately.
  A repo's ceiling lives in config/dispatch-repos.json and wins over the request.

BUDGETS   20 dispatches per UTC day overall, and 5 of those may be `implement`
          (HERMES_CC_DAILY_BUDGET / HERMES_CC_IMPLEMENT_BUDGET). Counted from
          the dispatches table, not a counter file. Every dispatch, plan,
          status and list reports the standing counts as `budget`, and adds a
          `budget.warning` naming the env var once a ceiling is close — so the
          bound is visible on the way up, not only when it refuses. A refusal is
          exit 4 and never a downgrade: raise the ceiling deliberately or wait
          for 00:00 UTC, do not retry into it. `merge` has a third, tighter
          ceiling of 3/day (HERMES_CC_MERGE_BUDGET) — it is the only verb that
          changes what runs.

MERGE     `merge <job-id>` lands the draft PR an `implement` episode opened, with
          no human on GitHub. It merges ONLY a PR recorded in the dispatches
          table (a job id in, never a PR number), only where a human review is
          not required — eligibility is derived from pr-required-repos.json, the
          same file the branch-protection hook reads — and only when every bound
          the episode was held to still holds against the CURRENT head: base is
          the default branch, head is a dispatch/… branch in this repo (never a
          fork), no .github/workflows change, size ceilings intact,
          mergeable_state exactly `clean`. The head SHA is pinned in the merge
          call, so a push landing mid-inspection fails the merge instead of
          riding it.

THE BRIEF IS DATA, NEVER COMMAND
  It is read from stdin or a file — never taken as an argv string. Use a QUOTED
  heredoc so the shell does not expand what a Slack message wrote:

      hermes-cc.sh dispatch sideclaw --wait --json <<'BRIEF'
      The check job for repo X has failed three times since 14:00. Why?
      BRIEF

DELIBERATELY NOT IMPLEMENTED
  free-form path / command / URL   The escape hatch that would defeat the point.
  restart / redeploy / any infra   hermes-ops.sh owns mutation, with its own
                                   verb set and tiering. A dispatch that wants to
                                   restart a container is a routing bug.
  mid-run steering                 An episode has a verdict, not a conversation.
                                   `rd bg` + `rd say` already do that shape.
  killing a running episode        sideclaw has no cancel endpoint; `cancel`
                                   abandons the record and says so.
  dispatching from inside a session A dispatched episode may never dispatch.

--json      Exactly ONE JSON object on stdout per invocation, success or failure.
            A failure carries ok:false and exitCode in that same object; anything
            unstructured goes to stderr, so stdout always parses.

EXIT CODES  0 ok · 2 precondition failed · 3 remote failed · 4 policy/budget
            refusal · 64 usage error
AUDIT LOG   ~/Library/Logs/hermes-cc.log (one line per invocation, always)
BUDGET      See BUDGETS above. Counted from the dispatches table, never a file.
EOF
}

# --- argument parsing --------------------------------------------------------
# Global flags are stripped anywhere in the line; what is left is the verb and its
# positional arguments. Every positional is validated by its verb. There is
# deliberately no --brief: see the header.

ARGS=()
while [ $# -gt 0 ]; do
  case "$1" in
    --json)      JSON=1; shift ;;
    --confirm)   CONFIRM=1; shift ;;
    --dry-run)   DRY_RUN=1; shift ;;
    --wait)      WAIT=1; shift ;;
    --why)
      [ $# -ge 2 ] || usage_err "--why needs a reason"
      WHY="$2"; shift 2 ;;
    --why=*)     WHY="${1#--why=}"; shift ;;
    --tier)
      [ $# -ge 2 ] || usage_err "--tier needs a value"
      TIER="$2"; shift 2 ;;
    --tier=*)    TIER="${1#--tier=}"; shift ;;
    --brief-file)
      [ $# -ge 2 ] || usage_err "--brief-file needs a path"
      BRIEF_FILE="$2"; shift 2 ;;
    --brief-file=*) BRIEF_FILE="${1#--brief-file=}"; shift ;;
    --context-file)
      [ $# -ge 2 ] || usage_err "--context-file needs a path"
      CONTEXT_FILE="$2"; shift 2 ;;
    --context-file=*) CONTEXT_FILE="${1#--context-file=}"; shift ;;
    --origin-channel)
      [ $# -ge 2 ] || usage_err "--origin-channel needs a channel id"
      ORIGIN_CHANNEL="$2"; shift 2 ;;
    --origin-channel=*) ORIGIN_CHANNEL="${1#--origin-channel=}"; shift ;;
    --origin-thread)
      [ $# -ge 2 ] || usage_err "--origin-thread needs a thread ts"
      ORIGIN_THREAD="$2"; shift 2 ;;
    --origin-thread=*) ORIGIN_THREAD="${1#--origin-thread=}"; shift ;;
    --origin-event)
      [ $# -ge 2 ] || usage_err "--origin-event needs an events.id"
      ORIGIN_EVENT="$2"; shift 2 ;;
    --origin-event=*) ORIGIN_EVENT="${1#--origin-event=}"; shift ;;
    # The brief is never an argv string. Rejecting the flag by name (rather than
    # letting it fall into "unknown flag") is what teaches the caller the right
    # shape instead of leaving it to guess.
    --brief|--brief=*)
      usage_err "there is no --brief: the brief is data, not an argument. Pass it on stdin with a QUOTED heredoc (<<'BRIEF') or via --brief-file <path>." ;;
    -h|--help)   ARGS+=(help); shift ;;
    -*)          usage_err "unknown flag: $1" ;;
    *)           ARGS+=("$1"); shift ;;
  esac
done

VERB="${ARGS[0]:-}"
[ ${#ARGS[@]} -gt 0 ] && AUDIT_ARGS="${ARGS[*]:1}"

case "$VERB" in
  dispatch)  cmd_dispatch "${ARGS[@]:1}" ;;

  status)    cmd_status "${ARGS[@]:1}" ;;
  list)      cmd_list "${ARGS[@]:1}" ;;

  cancel)    cmd_cancel "${ARGS[@]:1}" ;;
  merge)     cmd_merge "${ARGS[@]:1}" ;;

  help|"")   show_help ;;
  # No fallthrough to a shell, ever. An unknown verb is a usage error and the
  # valid set is printed so the caller can correct itself without guessing.
  *)         usage_err "unknown verb: $VERB
valid verbs:
  dispatch <repo>   open an episode (brief on stdin)
  status <job-id>   poll one
  list [scope]      open | today | all
  merge <job-id>    land the draft PR that dispatch opened (--why --confirm)
  cancel <job-id>   abandon the local record (--why --confirm)
  help" ;;
esac
