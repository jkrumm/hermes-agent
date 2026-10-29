#!/usr/bin/env python3
"""quota-nudge — give stalled Claude Code agents in herdr a nudge once a usage limit has reset.

Deterministic, no LLM. Runs every 30 min from the Hermes cron (no_agent).

For every herdr Claude agent that is not actively working:
  1. read the bottom block of its pane (the input box / pause-banner region),
  2. recognise a usage-limit pause ("Paused · usage limit · resets at …",
     "send a prompt to continue", "Automatic continue cancelled", …),
  3. decide whether quota is back, from the platform's quota view (`agw quota`,
     shelled out through `agw_run.py`) plus the pane's own statusline triple,
  4. if it is: `herdr agent prompt <pane> continue` — and verify the agent went
     to `working`, so a silently swallowed prompt is reported instead of
     believed.

Never touches a pane whose input line holds a draft (Enter on someone's typing
is not ours to press) and never answers an approval dialog.

Only panes on the allowlist (`NUDGE_TARGETS`: agent-workflows, iris, the Athena
Teamchat wave chain) are ever prompted; every other stalled pane is reported
once per limit episode and left for him to resume.

State: ~/.hermes/cache/quota-nudge-state.json   (cooldown per pane, episode attempts)
Log:   ~/.hermes/cache/quota-nudge.jsonl

stdout is the cron message: empty output == nothing to say.
"""

import hashlib
import json
import os
import re
import subprocess
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.realpath(__file__)))
import agw_run  # noqa: E402

HOME = os.path.expanduser("~")
STATE_PATH = os.path.join(HOME, ".hermes/cache/quota-nudge-state.json")
LOG_PATH = os.path.join(HOME, ".hermes/cache/quota-nudge.jsonl")

COOLDOWN_S = 20 * 60        # no second nudge on the same pane within 20 min
MAX_ATTEMPTS = 3            # per limit episode; then stop and say so
FIVE_HOUR_HEADROOM = 95     # percent of the 5h window that still counts as "room"
SEVEN_DAY_HEADROOM = 99     # weekly window must not be maxed out either
TAIL_CHARS = 6000

# The pause banner renders above the input box. These are the phrasings Claude
# Code 2.1.x uses (strings verified in the bundle) — matched only inside the
# last pane block, so an agent *talking* about usage limits does not trip them.
LIMIT_PATTERNS = [
    r"usage limit · resets",
    r"usage limit .{0,12}resets (?:at )?",
    r"Paused · .{0,20}limit",
    r"hit your limit",
    r"usage limit reached",
    r"weekly (?:usage )?limit reached",
    r"reached your weekly usage limit",
    r"5-hour limit",
    r"limit will reset at",
    r"Working at lower priority",
    r"Lower priority until",
]
# These mean Claude Code itself will NOT resume on its own.
HARD_PATTERNS = [
    r"Automatic continue cancelled",
    r"send a prompt (?:then )?to continue",
    r"send a message after it resets to continue",
    r"will not resume on its own",
]
# A limit banner that is still attached to an actively generating agent.
WORKING_HINTS = [r"esc to interrupt", r"Newspapering", r"Baked for", r"Polling new run"]

RULER = re.compile(r"^\s*[─━]{10,}\s*$")
DRAFT = re.compile(r"^\s*[❯>]\s+\S")
ACCOUNT_FOOTER = re.compile(r"^\s*(?:MAX|IU|GW|API)\s+([A-Za-z0-9]{2,4})\s*·", re.M)
TRIPLE = re.compile(r"(?:^|[\s·])(iu|me\d?|ca)\s+(\d{1,3})/(\d{1,3})")

# Allowlist: only these panes may be auto-continued. Everything else keeps its
# banner and stays his to resume — he asked for a narrow set (2026-10-28):
# agent-workflows and iris once the weekly IU window rolls over, plus the
# Athena Teamchat wave chain. The Athena "Key Kostenabgleich" pane in
# usage-tracker is deliberately NOT matched: he finishes that one himself.
NUDGE_TARGETS = [
    ("agent-workflows", r"/SourceRoot/agent-workflows(?:/\.claude/worktrees/[^/]+)?/?$"),
    ("iris", r"/SourceRoot/iris(?:/\.claude/worktrees/[^/]+)?/?$"),
    ("athena-teamchat", r"athena\W?team\W?chat"),
    # the Teamchat wave chain's repos: the plan/execution side and the UI side
    ("prometheus-epx", r"/IuRoot/prometheus-epx(?:/\.claude/worktrees/[^/]+)?/?$"),
    ("athena-lanes", r"/wip/athena-r4-[^/]+(?:/\.claude/worktrees/[^/]+)?/?$"),
    ("chat", r"/SourceRoot/chat(?:/\.claude/worktrees/[^/]+)?/?$"),
]


def sh(args, timeout=25):
    try:
        p = subprocess.run(args, capture_output=True, text=True, timeout=timeout)
        return p.returncode, p.stdout, p.stderr
    except Exception as exc:                                    # noqa: BLE001
        return 1, "", f"{type(exc).__name__}: {exc}"


def log(entry):
    entry["ts"] = int(time.time())
    try:
        os.makedirs(os.path.dirname(LOG_PATH), exist_ok=True)
        with open(LOG_PATH, "a") as fh:
            fh.write(json.dumps(entry, ensure_ascii=False) + "\n")
    except OSError:
        pass


def load_state():
    try:
        with open(STATE_PATH) as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return {}


def save_state(state):
    try:
        os.makedirs(os.path.dirname(STATE_PATH), exist_ok=True)
        tmp = STATE_PATH + ".tmp"
        with open(tmp, "w") as fh:
            json.dump(state, fh, indent=1, sort_keys=True)
        os.replace(tmp, STATE_PATH)
    except OSError:
        pass


def quota_accounts():
    """`agw quota` -> ({account: {five_hour_pct, seven_day_pct, ...}}, data). Empty on any failure."""
    try:
        payload = agw_run.call(["quota"])
        return payload.get("accounts") or {}, payload.get("data") or {}
    except Exception:                                            # noqa: BLE001
        return {}, {}


def herdr_agents():
    rc, out, err = sh(["herdr", "agent", "list"])
    if rc != 0:
        raise RuntimeError(f"herdr agent list failed: {err.strip() or rc}")
    data = json.loads(out)
    return data.get("result", {}).get("agents", [])


def pane_text(pane):
    rc, out, _ = sh(["herdr", "pane", "read", pane, "--source", "recent-unwrapped", "--lines", "70"])
    return out if rc == 0 else ""


def bottom_block(text):
    """The last few lines of the pane — where a pause banner and the input box live.

    A usage-limit banner is the agent's last output and stays attached above the
    input box, so the window is small on purpose: an agent *talking* about rate
    limits higher up in the transcript must not trip the detector.
    """
    lines = [ln for ln in text.splitlines() if ln.strip() and not RULER.match(ln)]
    return lines[-18:]


def inspect_block(block):
    joined = "\n".join(block)
    limit_hit = any(re.search(p, joined, re.I) for p in LIMIT_PATTERNS)
    hard = any(re.search(p, joined, re.I) for p in HARD_PATTERNS)
    working_hint = any(re.search(p, joined, re.I) for p in WORKING_HINTS)
    draft = None
    for ln in block:
        if DRAFT.match(ln):
            draft = ln.strip()
    account = None
    m = ACCOUNT_FOOTER.search(joined)
    if m:
        account = m.group(1).lower()
    triples = {}
    for a, five, week in TRIPLE.findall(joined):
        triples[a.lower()] = (int(five), int(week))
    evidence = ""
    for ln in reversed(block):
        if any(re.search(p, ln, re.I) for p in LIMIT_PATTERNS + HARD_PATTERNS):
            evidence = ln.strip()[:180]
            break
    return {
        "limit_hit": limit_hit,
        "hard": hard,
        "working_hint": working_hint,
        "draft": draft,
        "account": account,
        "triples": triples,
        "evidence": evidence,
    }


def quota_view(account, accounts, triples):
    """Return (available: bool|None, reason: str)."""
    acct = accounts.get(account or "")
    if acct:
        five = acct.get("five_hour_pct")
        seven = acct.get("seven_day_pct")
        if five is None:
            return None, "kein 5h-Wert in agw quota"
        if five >= FIVE_HOUR_HEADROOM:
            return False, f"{account} 5h bei {five} %"
        if seven is not None and seven >= SEVEN_DAY_HEADROOM:
            return False, f"{account} Woche bei {seven} %"
        return True, f"{account} 5h {five} % · Woche {seven} %"
    if account and account in triples:
        five, seven = triples[account]
        if five >= FIVE_HOUR_HEADROOM or seven >= SEVEN_DAY_HEADROOM:
            return False, f"{account} laut Statuszeile {five}/{seven}"
        return True, f"{account} laut Statuszeile {five}/{seven}"
    if triples and not account:
        best = min(triples.items(), key=lambda kv: (kv[1][0], kv[1][1]))
        name, (five, seven) = best
        if five < FIVE_HOUR_HEADROOM and seven < SEVEN_DAY_HEADROOM:
            return True, f"kein Konto erkannt, {name} hat Platz ({five}/{seven})"
    return None, "Kontingent unklar"


def title_of(agent):
    return (agent.get("terminal_title_stripped") or agent.get("cwd") or agent.get("pane_id")).strip()


def nudge_target(agent):
    """The allowlist name for this pane, or None when it is not ours to resume."""
    cwd = (agent.get("cwd") or "").rstrip("/")
    title = agent.get("terminal_title_stripped") or ""
    for name, pattern in NUDGE_TARGETS:
        if cwd and re.search(pattern, cwd, re.I):
            return name
        if title and re.search(pattern, title, re.I):
            return name
    return None


def run(dry_run=False, verbose=False, simulate=None):
    state = load_state()
    accounts, summary = quota_accounts()
    messages = []
    now = int(time.time())

    try:
        agents = herdr_agents()
    except Exception as exc:                                     # noqa: BLE001
        print(f"🔴 quota-nudge: herdr nicht lesbar — {exc}")
        return 0

    rows = []
    for agent in agents:
        if (agent.get("agent") or "") != "claude":
            continue
        status = agent.get("agent_status") or "unknown"
        if status == "blocked":
            continue                       # an approval dialog is his to answer
        pane = agent.get("pane_id")
        text = pane_text(pane)
        if not text.strip():
            continue
        block = bottom_block(text)
        info = inspect_block(block)
        if status == "working":
            state[f"{pane}:work"] = now    # eligibility for the rest of the night
        forced = simulate == pane          # test hook, see --simulate
        if forced:
            info["limit_hit"] = info["hard"] = True
            info["evidence"] = "simulated limit banner"
            info["draft"] = None
        if not info["limit_hit"] and not info["hard"]:
            state.pop(pane, None)          # episode over / never started
            continue
        if status == "working" and not (info["hard"] or info["working_hint"] is False):
            rows.append((pane, status, info, None, "läuft weiter", nudge_target(agent) or "-"))
            continue
        available, reason = quota_view(info["account"], accounts, info["triples"])
        rows.append((pane, status, info, available, reason, nudge_target(agent) or "-"))
        if not available:
            continue                       # still blocked, or unknown: wait a tick
        if info["draft"]:
            key = f"{pane}:draft"
            if key not in state:
                state[key] = now
                messages.append(f"🟡 quota-nudge: {title_of(agent)} steht am Limit — im Eingabefeld liegt ein Entwurf (`{info['draft'][:60]}`), ich habe nichts gesendet")
            continue
        target = nudge_target(agent)
        if not target and not forced and now - int(state.get(f"{pane}:work") or 0) < RECENT_WORK_S:
            target = "recent-work"
        if not target and not forced:
            # Not on the allowlist: report once per limit episode, never prompt.
            ep_id = hashlib.sha1(f"{pane}|{info['evidence']}".encode()).hexdigest()[:12]
            if state.get(f"{pane}:offlist") != ep_id:
                state[f"{pane}:offlist"] = ep_id
                messages.append(f"🟡 quota-nudge: {title_of(agent)} steht am Limit, ist aber nicht in der Allowlist — ich lasse ihn liegen")
            continue
        last_nudge = state.get(f"{pane}:ts", 0)
        if now - last_nudge < COOLDOWN_S:
            continue
        episode = hashlib.sha1(f"{pane}|{info['evidence']}".encode()).hexdigest()[:12]
        ep = state.get(f"{pane}:ep") or {}
        if ep.get("id") != episode:
            ep = {"id": episode, "attempts": 0}
        if ep["attempts"] >= MAX_ATTEMPTS:
            if not ep.get("reported"):
                ep["reported"] = True
                state[f"{pane}:ep"] = ep
                messages.append(f"🔴 quota-nudge: {title_of(agent)} hängt zum {ep['attempts']}. Mal am Limit — ich lasse ihn liegen, den muss man sich ansehen")
            continue
        # nudge
        if dry_run:
            messages.append(f"▫️ [dry-run] würde „continue“ senden an {title_of(agent)} — {reason}")
            continue
        rc, out, err = sh(["herdr", "agent", "prompt", pane, "continue"], timeout=40)
        ep["attempts"] = ep.get("attempts", 0) + 1
        state[f"{pane}:ep"] = ep
        state[f"{pane}:ts"] = now
        entry = {
            "pane": pane, "title": title_of(agent), "status": status,
            "account": info["account"], "reason": reason,
            "evidence": info["evidence"], "rc": rc, "err": err.strip()[:200],
        }
        if rc != 0:
            entry["outcome"] = "prompt_failed"
            log(entry)
            messages.append(f"🔴 quota-nudge: {title_of(agent)} — „continue“ kam nicht durch ({err.strip()[:120] or 'herdr rc ' + str(rc)})")
            continue
        # verify delivery: the agent must leave idle/done
        went = None
        for _ in range(6):
            time.sleep(2)
            rc2, out2, _ = sh(["herdr", "agent", "get", pane])
            if rc2 == 0:
                try:
                    went = json.loads(out2).get("result", {}).get("agent", {}).get("agent_status")
                except ValueError:
                    went = None
            if went == "working":
                break
        entry["status_after"] = went
        entry["outcome"] = "nudged" if went == "working" else "unverified"
        log(entry)
        if went == "working":
            messages.append(f"🟢 quota-nudge: {title_of(agent)} war am Limit, Kontingent ist zurück — „continue“ gesendet, läuft wieder")
        else:
            messages.append(f"🟡 quota-nudge: {title_of(agent)} — „continue“ gesendet, aber der Agent ist nicht auf `working` gegangen (Status `{went}`). Bitte die Pane ansehen")

    save_state(state)
    if verbose:
        for pane, status, info, available, reason, target in rows:
            print(f"  {pane:10s} {status:8s} limit={int(info['limit_hit'])} hard={int(info['hard'])} "
                  f"acct={info['account']} avail={available} allow={target} — {reason} | {info['evidence'][:70]}")
    for m in messages:
        print(m)
    return 0


def self_test():
    """Fixture check of the decision logic — no herdr, no network."""
    case = lambda txt: inspect_block(bottom_block(txt))          # noqa: E731
    ok = True

    def check(name, cond):
        nonlocal ok
        print(("  ok   " if cond else "  FAIL ") + name)
        ok = ok and cond

    normal = "\n".join([
        "⏺ Merged the threads PR. All green.",
        "✻ Baked for 1m 28s · done 12:06 AM",
        "─" * 60,
        "❯ ",
        "─" * 60,
        "  MAX ME2 · Opus 5.5 · medium | 160k/600k 26% | iu 0/98 · me 18/98 · me2 33/26 ↺223m · ∑86%",
    ])
    c = case(normal)
    check("fertiger Agent wird nicht angefasst", not c["limit_hit"] and not c["hard"])
    check("Konto aus Statuszeile", c["account"] == "me2")

    paused = "\n".join([
        "⏺ Working on wave 12.",
        "─" * 60,
        "  Paused · usage limit · resets at 3pm",
        "─" * 60,
        "❯ ",
        "─" * 60,
        "  MAX ME · Opus 5.5 | iu 0/98 · me 100/50 · me2 33/26",
    ])
    c = case(paused)
    check("Pause-Banner erkannt", c["limit_hit"])
    check("kein Draft", c["draft"] is None)
    check("hartes Nein bei vollem Konto", quota_view(c["account"], {"me": {"five_hour_pct": 100, "seven_day_pct": 50}}, c["triples"])[0] is False)
    check("frei nach Reset", quota_view(c["account"], {"me": {"five_hour_pct": 4, "seven_day_pct": 50}}, c["triples"])[0] is True)

    cancelled = "\n".join([
        "⏺ Implemented the endpoint.",
        "─" * 60,
        "  Automatic continue cancelled · Claude Code exited during the wait, so the task will not resume on its own when the usage limit resets (send a prompt after the reset to continue)",
        "─" * 60,
        "❯ ",
        "─" * 60,
        "  MAX IU · Sonnet | iu 12/40 · me 18/98",
    ])
    c = case(cancelled)
    check("abgebrochenes Auto-Continue ist hart", c["hard"] and c["limit_hit"])
    check("IU-Konto erkannt", c["account"] == "iu")

    draft = paused.replace("❯ \n", "❯ continue\n")
    check("Draft wird erkannt", case(draft)["draft"] == "❯ continue")

    talk = "\n".join([
        "⏺ Claude subscription status and token usage (5-hour and 7-day windows) is what the statusline shows.",
        "  A usage limit reached message means the 5-hour limit is exhausted.",
    ] + [f"  ⎿  line {i} of ordinary transcript output" for i in range(30)] + [
        "─" * 60,
        "❯ ",
        "─" * 60,
        "  MAX ME2 · Sonnet | me2 41/20",
    ])
    check("Gerede über Limits triggert nicht", not case(talk)["limit_hit"])

    print("self-test:", "OK" if ok else "FAILED")
    return 0 if ok else 1


def main(argv):
    if "--self-test" in argv:
        return self_test()
    simulate = None
    if "--simulate" in argv:
        simulate = argv[argv.index("--simulate") + 1]
    return run(dry_run="--dry-run" in argv,
               verbose="--verbose" in argv or "--status" in argv,
               simulate=simulate)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
