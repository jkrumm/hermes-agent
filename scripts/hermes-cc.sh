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
# COMMAND, OR A URL. A dispatch names a REPO — a key in config/dispatch-repos.json
# — and this script resolves the path. Absence from that file is a denial. One
# free-form escape hatch and the whole exercise is theatre.
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
# TIERS — the episode's permission profile, capped per-repo by the allowlist.
#   investigate  read-only session, verdict only. Cannot lose anything, so it
#                needs no approval theatre and is safe to allowlist outright.
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
# properties above — the closed verb set, argument bounding, the repo allowlist,
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
    dispatch|cancel)
      if [ "$DID_MUTATE" = 1 ]; then mode="opened"
      elif [ "$DRY_RUN" = 1 ]; then mode="dry-run"
      elif [ "$PLANNED" = 1 ]; then mode="planned"
      else mode="refused"; fi ;;
    *) mode="read" ;;
  esac
  mkdir -p "$(dirname "$AUDIT_LOG")" 2>/dev/null || true
  printf '%s | verb=%s | mode=%s | tier=%s | args=%s | target=%s | rc=%s | dur=%ss | why=%s\n' \
    "$ts" "${VERB:--}" "$mode" "${TIER:--}" "$(redact "${AUDIT_ARGS:--}")" "$AUDIT_TARGET" \
    "$rc" "$dur" "$(redact "${WHY:--}")" \
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

# --- repo allowlist ----------------------------------------------------------

# Set by resolve_repo. Never assembled from caller input.
REPO_PATH=""
REPO_MAX_TIER=""

# Two gates, deliberately. The shape check rejects anything that could not be a
# repo key before it is used as one; the allowlist lookup is what makes this
# script incapable of naming a repo Johannes did not list. A path never crosses
# the interface — the caller says `sideclaw`, this resolves `~/SourceRoot/sideclaw`.
resolve_repo() {
  local name=$1 out
  case "$name" in
    ''|*[!A-Za-z0-9_.-]*) usage_err "not a repo name: $name" ;;
  esac
  [ -f "$REPOS_JSON" ] || precond_err "repo allowlist not found at $REPOS_JSON"
  out=$(NAME="$name" REPOS_JSON="$REPOS_JSON" python3 -c '
import json, os, sys
with open(os.environ["REPOS_JSON"]) as f:
    repos = json.load(f).get("repos", {})
name = os.environ["NAME"]
entry = repos.get(name)
if not entry:
    sys.stderr.write("allowed repos: " + ", ".join(sorted(repos)) + "\n")
    sys.exit(1)
print(os.path.expanduser(entry["path"]))
print(entry.get("maxTier", "investigate"))
') || usage_err "repo not in the allowlist: $name (see list above; absence is a denial, not an oversight)"
  REPO_PATH=$(printf '%s' "$out" | sed -n 1p)
  REPO_MAX_TIER=$(printf '%s' "$out" | sed -n 2p)
  # The ceiling has to FAIL CLOSED on a malformed value. tier_rank maps anything it does
  # not recognize to 99, which is above every real tier — so a typo in the allowlist
  # ("implment") would silently lift the cap entirely and hand a write episode to a repo
  # meant to be read-only. That is the exact inversion of this file's "absence is a denial"
  # rule, and it is invisible: the JSON parses, the repo resolves, the dispatch runs.
  in_list "$REPO_MAX_TIER" "${VALID_TIERS[@]}" \
    || precond_err "repo '$name' has an unrecognized maxTier '$REPO_MAX_TIER' in $REPOS_JSON (must be one of: ${VALID_TIERS[*]}). Refusing rather than defaulting — a malformed ceiling must never read as a permissive one."
  [ -d "$REPO_PATH" ] || precond_err "allowlisted repo '$name' has no checkout at $REPO_PATH"
  [ -e "$REPO_PATH/.git" ] || precond_err "allowlisted repo '$name' at $REPO_PATH is not a git repository"
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
    || policy_err "repo '$name' is capped at tier '$REPO_MAX_TIER' in the allowlist; '$requested' was requested"
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
"

# Every DB helper passes values as bound parameters from the environment. No verb
# accepts SQL, and none is assembled from caller input — same rule as the paths.
db_py() {
  DB_PATH="$DB_PATH" DB_SCHEMA="$DB_SCHEMA" python3 -c "
import json, os, sqlite3, sys
conn = sqlite3.connect(os.environ['DB_PATH'])
conn.row_factory = sqlite3.Row
conn.executescript(os.environ['DB_SCHEMA'])
$1
conn.commit()
conn.close()
"
}

# Structural budget check. Counts today's rows rather than trusting a counter file:
# the table is the record, and a count that can drift from it is not a budget.
# Two ceilings, because the two kinds of episode are not the same kind of spend —
# see MAX_IMPLEMENT_PER_DAY. Echoes the total used, which the emitters report.
check_budget() {
  local counts used used_tier
  counts=$(R_TIER="$TIER" db_py '
import datetime as dt
today = dt.datetime.now(dt.timezone.utc).date().isoformat()
n = conn.execute("SELECT COUNT(*) FROM dispatches WHERE created_at >= ?", (today,)).fetchone()[0]
t = conn.execute("SELECT COUNT(*) FROM dispatches WHERE created_at >= ? AND tier = ?",
                 (today, os.environ["R_TIER"])).fetchone()[0]
print(n)
print(t)
') || precond_err "could not read the dispatch budget from $DB_PATH"
  used=$(printf '%s' "$counts" | sed -n 1p)
  used_tier=$(printf '%s' "$counts" | sed -n 2p)
  case "$used$used_tier" in
    ''|*[!0-9]*) precond_err "unexpected budget count from $DB_PATH: $counts" ;;
  esac
  [ "$used" -lt "$MAX_DISPATCHES_PER_DAY" ] \
    || policy_err "daily dispatch budget exhausted ($used/$MAX_DISPATCHES_PER_DAY opened today, UTC). This is a structural ceiling on unattended Max spend, not a rate limit — if it is hit legitimately, raise HERMES_CC_DAILY_BUDGET deliberately."
  if [ "$TIER" = implement ]; then
    [ "$used_tier" -lt "$MAX_IMPLEMENT_PER_DAY" ] \
      || policy_err "daily implement budget exhausted ($used_tier/$MAX_IMPLEMENT_PER_DAY opened today, UTC). Implement episodes are the expensive tier and each one produces a PR a human has to read; raise HERMES_CC_IMPLEMENT_BUDGET deliberately if this is legitimate."
  fi
  printf '%s' "$used"
}

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
  if awaiting_confirm; then PLANNED=1; fi
  if [ "$DRY_RUN" = 1 ] || [ "$PLANNED" = 1 ]; then
    emit_plan "$name"
    return 0
  fi

  # Budget is checked after validation so a refused invocation does not consume a
  # slot, and before submission so an over-budget one never opens a session.
  local used
  used=$(check_budget)

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

  if [ "$WAIT" = 1 ]; then
    wait_for "$job_id" "$name" "$used"
    return $?
  fi

  emit_submitted "$job_id" "$name" "$used"
}

# In-turn polling for the short tiers: an investigate episode is 30s-3min, which
# fits inside a Slack turn, so Hermes can answer in the thread it is already in
# rather than waiting for the sweeper. Past WAIT_TIMEOUT this gives up and says so
# — the dispatch record is already written, so the sweeper owns delivery from
# there and nothing is lost by not waiting longer.
wait_for() {
  local job_id=$1 name=$2 used=$3 elapsed=0 resp status
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
  emit_result "$job_id" "$name" "$resp" "$used"
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
  emit_result "$job_id" "-" "$resp" "-"
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
# OUTPUT
# =============================================================================
#
# Exactly one JSON object per invocation under --json, success or failure. Every
# emitter sets JSON_EMITTED so a later _err falls back to stderr rather than
# appending a second object.

emit_submitted() {
  local job_id=$1 name=$2 used=$3
  if [ "$JSON" = 1 ]; then
    JSON_EMITTED=1
    E_JOB="$job_id" E_REPO="$name" E_TIER="$TIER" E_USED="$used" E_MAX="$MAX_DISPATCHES_PER_DAY" \
    python3 -c '
import json, os
print(json.dumps({"verb": "dispatch", "ok": True, "jobId": os.environ["E_JOB"],
                  "repo": os.environ["E_REPO"], "tier": os.environ["E_TIER"],
                  "status": "queued", "waited": False,
                  "budget": {"usedToday": int(os.environ["E_USED"]), "max": int(os.environ["E_MAX"])},
                  "note": "Episode opened. It is NOT finished — poll with `hermes-cc.sh status "
                          + os.environ["E_JOB"] + "`, or let the 5-minute sweeper deliver the "
                          "verdict into the origin thread."}, indent=2))
'
  else
    printf 'dispatch opened: %s (%s, tier %s)\n' "$job_id" "$name" "$TIER"
    printf 'not finished — poll: hermes-cc.sh status %s\n' "$job_id"
  fi
}

emit_result() {
  local job_id=$1 name=$2 resp=$3 used=$4
  if [ "$JSON" = 1 ]; then
    JSON_EMITTED=1
    E_JOB="$job_id" E_REPO="$name" E_TIER="${TIER:--}" RESP="$resp" python3 -c '
import json, os
job = json.loads(os.environ["RESP"])["job"]
result = job.get("result")
r = result if isinstance(result, dict) else {}
# artifactUrl and branch are hoisted to the top level rather than left nested in
# the verdict. They are the only fields a caller ACTS on, and an agent reading
# this should not have to know the verdict object is where a PR link hides.
print(json.dumps({"verb": "dispatch", "ok": job["status"] == "done",
                  "jobId": os.environ["E_JOB"], "repo": os.environ["E_REPO"],
                  "tier": os.environ["E_TIER"], "status": job["status"],
                  "waited": True, "elapsedMs": job.get("elapsedMs"),
                  "artifactUrl": r.get("artifactUrl"), "branch": r.get("branch"),
                  "verdict": result, "error": job.get("error")}, indent=2))
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
  fi
}

emit_timeout() {
  local job_id=$1 name=$2 elapsed=$3
  if [ "$JSON" = 1 ]; then
    JSON_EMITTED=1
    E_JOB="$job_id" E_REPO="$name" E_TIER="$TIER" E_EL="$elapsed" python3 -c '
import json, os
print(json.dumps({"verb": "dispatch", "ok": True, "jobId": os.environ["E_JOB"],
                  "repo": os.environ["E_REPO"], "tier": os.environ["E_TIER"],
                  "status": "running", "waited": True,
                  "waitedSeconds": int(os.environ["E_EL"]),
                  "note": "Still running after the in-turn wait. The dispatch record is "
                          "written, so the sweeper will deliver the verdict into the origin "
                          "thread — say so and move on rather than waiting again."}, indent=2))
'
  else
    printf 'still running after %ss — the sweeper will deliver it (job %s)\n' "$elapsed" "$job_id"
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
    E_NEEDS="$needs_confirm" E_MAXTIER="$REPO_MAX_TIER" python3 -c '
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
    E_SCOPE="$scope" ROWS="$rows" python3 -c '
import json, os
rows = json.loads(os.environ["ROWS"])
print(json.dumps({"verb": "list", "ok": True, "scope": os.environ["E_SCOPE"],
                  "count": len(rows), "dispatches": rows}, indent=2))
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
          the dispatches table, not a counter file.

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

  help|"")   show_help ;;
  # No fallthrough to a shell, ever. An unknown verb is a usage error and the
  # valid set is printed so the caller can correct itself without guessing.
  *)         usage_err "unknown verb: $VERB
valid verbs:
  dispatch <repo>   open an episode (brief on stdin)
  status <job-id>   poll one
  list [scope]      open | today | all
  cancel <job-id>   abandon the local record (--why --confirm)
  help" ;;
esac
