#!/usr/bin/env python3
"""Project narratives — daily project-status pages in the vault, written by
sideclaw's `narrative` job (`POST /api/jobs {"tool":"narrative", ...}`, same
submit/poll shape agents-overview.py's `refresh()` uses against the same
daemon, `http://localhost:7705`).

Less is more: a project with no substantive change since its last revision
gets no model call, no revision, and no mention. The gate (`needs_revision`)
is pure and cheap — HEAD moved, or a Claude Code transcript under
`~/.claude/projects/<encoded cwd>/` is newer than the last revision — so an
idle project costs nothing every run.

Per changed project, sequential, oldest-revised first, capped at
`HERMES_NARRATIVE_MAX_PER_RUN` (default 5) per `--run`: read the existing
vault page (if any) as `previousPage`, call the job with `since` = the last
revision timestamp, and on `changed: true` write the page, regenerate the
`wiki/engineering/projects/index.md` MOC, lint the vault
(`node .scripts/vault-lint.mjs`), and commit — always naming the vault
(`git -C ~/SourceRoot/brain …`), per the repo-write guard's vault exemption
(see hermes-agent/docs/guards.md). A lint failure reverts the page and skips
the commit entirely, retried on the next run.

The add/commit/push runs under brain-sync's own single-instance lock
(`~/Library/Caches/brain-sync.lock`, a `mkdir` dir with a `pid` file — the
exact primitive dotfiles/brain/brain-sync.sh, brain-backup.sh and
audio-gateway's brain-note.ts use), so this never races the 5-minute sync
for `.git/index.lock`. A held lock is retried a few times, then the commit
is skipped for this run (the page stays on disk; the next run — or the
sync itself — picks it up). `git push` is fail-soft: a rejected push logs
and moves on, brain-sync pushes on its next tick.

After a page is written, its summary is POSTed best-effort to Argo
(`/api/agents/narratives`, Bearer = the argo-api skill's key — env
HOMELAB_API_KEY, else `secrets-run read op://common/api/SECRET`), the feed
behind Argo's System → Agents page. The endpoint is being built in parallel:
a 404 — or any failure — is logged and non-fatal.

Page path: ~/SourceRoot/brain/wiki/engineering/projects/<project>.md — part
of the STRICT `wiki/` tree (frontmatter incl. `type`+`description` comes
from the job's `page` field verbatim; this script never authors project-page
frontmatter itself, only the projects/ index it regenerates).

CLI: --run (the cron entry) · --bootstrap a,b,c (forces since=null, no
commit — human review) · --briefing (last 26h from state) · --dry-run
(explains the gate) · --projects a,b (restrict discovery, any mode).

Source of truth: ~/SourceRoot/hermes-agent/scripts/project-narratives.py
~/.hermes/scripts/ is itself a symlink to this directory (see make setup).
Docs: docs/project-narratives.md.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

STATE_PATH = Path.home() / ".hermes" / "project-narratives-state.json"
SOURCE_ROOT = Path.home() / "SourceRoot"
VAULT_ROOT = SOURCE_ROOT / "brain"
PROJECTS_DIR = VAULT_ROOT / "wiki" / "engineering" / "projects"
ENGINEERING_INDEX = VAULT_ROOT / "wiki" / "engineering" / "index.md"
VAULT_LINT = VAULT_ROOT / ".scripts" / "vault-lint.mjs"
CLAUDE_PROJECTS_DIR = Path.home() / ".claude" / "projects"

# brain-sync's lock. Same path + semantics as dotfiles/brain/brain-sync.sh:
# `mkdir` is the atomic primitive, `<lock>/pid` names the holder, only the
# creator removes it. Overridable for tests (brain-sync.sh honors the same var).
BRAIN_LOCK_DIR = Path(os.environ.get("BRAIN_SYNC_LOCK_DIR", str(Path.home() / "Library" / "Caches" / "brain-sync.lock")))
LOCK_RETRY_ATTEMPTS = 6
LOCK_RETRY_DELAY_S = 5.0

ARGO_API_BASE = os.environ.get("HERMES_NARRATIVE_ARGO_BASE", "https://argo.jkrumm.com/api")
ARGO_NARRATIVES_PATH = "/agents/narratives"
ARGO_API_KEY_REF = "op://common/api/SECRET"
SECRETS_RUN = Path.home() / ".local" / "bin" / "secrets-run"
ARGO_HTTP_TIMEOUT = 10

DEFAULT_BASE = "http://localhost:7705"
BASE_ENV = "HERMES_NARRATIVE_SIDECLAW_BASE"

# Deny-listed projects: private-secrets repos, the disposable dispatch
# target, and the vault itself (a narrative page ABOUT the vault, written
# INTO the vault, is a confusing loop).
DENY_LIST = {"dotfiles-private", "homelab-private", "dispatch-scratch", "brain"}
SKIP_ENV = "HERMES_NARRATIVE_SKIP"

MAX_PER_RUN_ENV = "HERMES_NARRATIVE_MAX_PER_RUN"
DEFAULT_MAX_PER_RUN = 5

BRIEFING_WINDOW_HOURS = 26

SUBDOMAIN_LINK = "[[wiki/engineering/projects/index|Projects]]"
SUBDOMAIN_LINE = (
    f"- {SUBDOMAIN_LINK} — project narratives: what each project is, "
    "where it stands, how it got here."
)


# --- project discovery -----------------------------------------------------

def _skip_env_set() -> set[str]:
    raw = os.environ.get(SKIP_ENV, "")
    return {p.strip() for p in raw.split(",") if p.strip()}


def discover_projects(root: Path | None = None, restrict: set[str] | None = None) -> list[str]:
    """Every git repo directly under `root` (default SOURCE_ROOT), basename
    as the project name, minus DENY_LIST and HERMES_NARRATIVE_SKIP, minus
    anything not in `restrict` when given (--projects). A repo is
    `entry.is_dir()` with an `entry/.git` dir — a plain directory (no git)
    is silently not a project, same as a file."""
    root = root if root is not None else SOURCE_ROOT
    if not root.is_dir():
        return []
    skip = DENY_LIST | _skip_env_set()
    names = []
    for entry in sorted(root.iterdir()):
        if not entry.is_dir():
            continue
        if not (entry / ".git").is_dir():
            continue
        if entry.name in skip:
            continue
        if restrict is not None and entry.name not in restrict:
            continue
        names.append(entry.name)
    return names


# --- the change gate ---------------------------------------------------------

def needs_revision(
    project_state: dict[str, Any] | None,
    head_sha: str | None,
    newest_transcript_mtime: float | None,
) -> bool:
    """Pure: revise only when HEAD moved since `lastCommit`, or a transcript
    is newer than `lastSessionMtime`. Never revised before (`project_state`
    is None) always needs revision. No model call otherwise."""
    if project_state is None:
        return True
    if head_sha != project_state.get("lastCommit"):
        return True
    last_mtime = project_state.get("lastSessionMtime")
    if newest_transcript_mtime is not None:
        if last_mtime is None or newest_transcript_mtime > last_mtime:
            return True
    return False


def _dry_run_reason(
    project_state: dict[str, Any] | None,
    head_sha: str | None,
    newest_transcript_mtime: float | None,
) -> str:
    if project_state is None:
        return "never revised"
    reasons = []
    if head_sha != project_state.get("lastCommit"):
        reasons.append(f"HEAD moved ({project_state.get('lastCommit')} -> {head_sha})")
    last_mtime = project_state.get("lastSessionMtime")
    if newest_transcript_mtime is not None and (last_mtime is None or newest_transcript_mtime > last_mtime):
        reasons.append("newer Claude Code session")
    return "; ".join(reasons) if reasons else "needs revision"


# --- git + transcript inputs ------------------------------------------------

def _git_head_sha(project_dir: Path) -> str | None:
    try:
        res = subprocess.run(
            ["git", "-C", str(project_dir), "rev-parse", "HEAD"],
            capture_output=True, text=True, timeout=10,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if res.returncode != 0:
        return None
    sha = res.stdout.strip()
    return sha or None


def _encode_cwd(cwd: Path) -> str:
    """Every non-alphanumeric char -> '-', over the absolute path string —
    matches the encoding Claude Code itself uses for
    ~/.claude/projects/<encoded cwd>/."""
    return re.sub(r"[^A-Za-z0-9]", "-", str(cwd))


def _newest_transcript_mtime(project_dir: Path, claude_projects_dir: Path | None = None) -> float | None:
    base = claude_projects_dir if claude_projects_dir is not None else CLAUDE_PROJECTS_DIR
    transcript_dir = base / _encode_cwd(project_dir)
    if not transcript_dir.is_dir():
        return None
    newest: float | None = None
    for entry in transcript_dir.iterdir():
        try:
            mtime = entry.stat().st_mtime
        except OSError:
            continue
        if newest is None or mtime > newest:
            newest = mtime
    return newest


# Sideclaw job statuses that end the wait without a result. "failed" was the only
# one this loop used to check; "interrupted"/"cancelled" are the same "no result
# coming" case and were previously mis-treated as still-running.
_TERMINAL_FAILURE_STATUSES = frozenset({"failed", "interrupted", "cancelled"})


# --- sideclaw job client (the seam tests monkeypatch) -----------------------

def run_narrative_job(
    base: str, project: str, cwd: str, previous_page: str | None, since: str | None,
    *, poll_interval: int = 10,
) -> dict[str, Any] | None:
    """POST /api/jobs {tool:narrative,...}, poll GET /api/jobs/<id> until the job reaches a
    terminal status. Sideclaw workers have no turn or wall-clock limit (2026-09-12 policy), so
    this polls indefinitely rather than giving up on a healthy job — only a transport failure or
    a genuinely terminal status (`failed`/`interrupted`/`cancelled`) ends the wait early. This
    runs under Hermes cron (narratives-cron.py, no_agent), whose only guard is the idle-output
    watchdog (HERMES_CRON_TIMEOUT) — so a progress line to stderr once a minute is what keeps a
    long, healthy job alive rather than tripping it on silence. Returns the job's `result` dict
    on `done`, None on any transport failure or terminal-failure status — callers treat None as
    'try again next run', never as changed:false."""
    try:
        body = json.dumps({
            "tool": "narrative",
            "params": {"cwd": cwd, "project": project, "previousPage": previous_page, "since": since},
        }).encode()
        req = urllib.request.Request(
            f"{base}/api/jobs", data=body,
            headers={"content-type": "application/json"}, method="POST",
        )
        with urllib.request.urlopen(req, timeout=15) as resp:
            submitted = json.loads(resp.read().decode())
    except (urllib.error.URLError, urllib.error.HTTPError, json.JSONDecodeError, TimeoutError, OSError):
        return None

    job_id = (
        submitted.get("jobId") or submitted.get("id")
        or (submitted.get("job") or {}).get("id")
    )
    if not job_id:
        return None

    elapsed = 0
    while True:
        time.sleep(poll_interval)
        elapsed += poll_interval
        try:
            with urllib.request.urlopen(f"{base}/api/jobs/{job_id}", timeout=15) as resp:
                polled = json.loads(resp.read().decode())
        except (urllib.error.URLError, urllib.error.HTTPError, json.JSONDecodeError, TimeoutError, OSError):
            return None
        job = polled.get("job") or polled
        status = job.get("status")
        if status == "done":
            return job.get("result")
        if status in _TERMINAL_FAILURE_STATUSES:
            return None
        if elapsed % 60 < poll_interval:
            print(
                f"project-narratives: {project} — job {job_id} still {status or 'running'} "
                f"({elapsed}s elapsed)", file=sys.stderr,
            )


def _base_url() -> str:
    return os.environ.get(BASE_ENV, DEFAULT_BASE)


def _max_per_run() -> int:
    try:
        return int(os.environ.get(MAX_PER_RUN_ENV, DEFAULT_MAX_PER_RUN))
    except ValueError:
        return DEFAULT_MAX_PER_RUN


# --- state ------------------------------------------------------------------

def _load_state() -> dict[str, Any]:
    try:
        return json.loads(STATE_PATH.read_text())
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def _save_state(state: dict[str, Any]) -> None:
    try:
        STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
        tmp = STATE_PATH.with_suffix(STATE_PATH.suffix + f".tmp.{os.getpid()}")
        tmp.write_text(json.dumps(state, indent=2, sort_keys=True))
        tmp.replace(STATE_PATH)
    except OSError:
        pass


def _now_dt() -> datetime:
    return datetime.now(timezone.utc)


def _now_iso() -> str:
    return _now_dt().isoformat()


# --- vault pages -------------------------------------------------------------

def _page_path(project: str) -> Path:
    return PROJECTS_DIR / f"{project}.md"


def _read_previous_page(project: str) -> str | None:
    path = _page_path(project)
    if not path.exists():
        return None
    try:
        return path.read_text()
    except OSError:
        return None


def _write_page(project: str, markdown: str) -> None:
    PROJECTS_DIR.mkdir(parents=True, exist_ok=True)
    text = markdown if markdown.endswith("\n") else markdown + "\n"
    _page_path(project).write_text(text)


_FRONTMATTER_RE = re.compile(r"^---\r?\n(.*?)\r?\n---\r?\n", re.DOTALL)


def _extract_description(markdown: str) -> str:
    """Best-effort single-line `description:` value out of a note's YAML
    frontmatter — enough for the index line, not a general YAML parser."""
    m = _FRONTMATTER_RE.match(markdown)
    if not m:
        return ""
    for line in m.group(1).splitlines():
        line = line.strip()
        if line.startswith("description:"):
            value = line.split(":", 1)[1].strip()
            return value.strip('"').strip("'")
    return ""


def _regenerate_projects_index() -> None:
    """Whole-file regeneration from every `<project>.md` currently on disk
    under PROJECTS_DIR — one `- [[<project>]] — <description>` line each,
    sorted by filename."""
    PROJECTS_DIR.mkdir(parents=True, exist_ok=True)
    lines = []
    for path in sorted(PROJECTS_DIR.glob("*.md")):
        if path.name == "index.md":
            continue
        try:
            text = path.read_text()
        except OSError:
            continue
        desc = _extract_description(text)
        line = f"- [[{path.stem}]]"
        if desc:
            line += f" — {desc}"
        lines.append(line)

    body = "\n".join(lines) if lines else "- (none yet)"
    content = (
        "---\n"
        "type: Index\n"
        "description: Project narratives — what each project is, where it "
        "stands, how it got here\n"
        "title: Projects\n"
        "tags:\n"
        "  - moc\n"
        "  - engineering\n"
        "  - projects\n"
        f"timestamp: {_now_dt().date().isoformat()}\n"
        "---\n\n"
        "# Projects\n\n"
        f"{body}\n"
    )
    (PROJECTS_DIR / "index.md").write_text(content)


def _ensure_engineering_index_links_projects() -> None:
    """Append a `## Subdomains` section (matching wiki/health/index.md's
    convention) linking the projects index, if not already present."""
    if not ENGINEERING_INDEX.exists():
        return
    try:
        text = ENGINEERING_INDEX.read_text()
    except OSError:
        return
    if SUBDOMAIN_LINK in text:
        return

    if "## Subdomains" in text:
        lines = text.splitlines()
        out = []
        inserted = False
        for line in lines:
            out.append(line)
            if not inserted and line.strip() == "## Subdomains":
                out.append(SUBDOMAIN_LINE)
                inserted = True
        new_text = "\n".join(out)
        if text.endswith("\n"):
            new_text += "\n"
    else:
        new_text = text if text.endswith("\n") else text + "\n"
        new_text += f"\n## Subdomains\n\n{SUBDOMAIN_LINE}\n"

    ENGINEERING_INDEX.write_text(new_text)


# --- lint + git (vault) ------------------------------------------------------

def _run_vault_lint() -> tuple[bool, str]:
    try:
        res = subprocess.run(
            ["node", str(VAULT_LINT)],
            cwd=str(VAULT_ROOT), capture_output=True, text=True, timeout=60,
        )
    except (OSError, subprocess.SubprocessError) as e:
        return False, str(e)
    output = (res.stdout or "") + (res.stderr or "")
    return res.returncode == 0, output


def _git_vault(*args: str) -> Any:
    return subprocess.run(
        ["git", "-C", str(VAULT_ROOT), *args],
        capture_output=True, text=True, timeout=30,
    )


def acquire_brain_lock(lock_dir: Path | None = None, *, attempts: int = LOCK_RETRY_ATTEMPTS,
                       delay_s: float = LOCK_RETRY_DELAY_S) -> bool:
    """Take brain-sync's mkdir lock. True iff THIS call created it — only then
    may release_brain_lock() remove it. A held lock is retried `attempts`
    times `delay_s` apart (brain-note.ts's tolerance), then given up on:
    skipping one commit is cheap, racing brain-sync for .git/index.lock is
    not. A pidless lock older than 60s whose holder is gone is reclaimed,
    exactly as brain-sync.sh does; a fresh pidless one is another run
    claiming it."""
    lock = lock_dir if lock_dir is not None else BRAIN_LOCK_DIR
    for attempt in range(attempts + 1):
        try:
            lock.mkdir()
        except FileExistsError:
            holder = ""
            try:
                holder = (lock / "pid").read_text().strip()
            except OSError:
                pass
            alive = False
            if holder.isdigit():
                try:
                    os.kill(int(holder), 0)
                    alive = True
                except ProcessLookupError:
                    alive = False
                except PermissionError:
                    alive = True
            if not alive:
                try:
                    age = time.time() - lock.stat().st_mtime
                except OSError:
                    age = 0
                if holder or age >= 60:
                    print(f"project-narratives: reclaiming {lock} left by pid {holder or 'unknown'} ({int(age)}s old)", file=sys.stderr)
                    _rmtree(lock)
                    continue
            if attempt == attempts:
                return False
            time.sleep(delay_s)
        except OSError:
            return False
        else:
            try:
                (lock / "pid").write_text(str(os.getpid()))
            except OSError:
                pass
            return True
    return False


def release_brain_lock(owned: bool, lock_dir: Path | None = None) -> None:
    if not owned:
        return
    _rmtree(lock_dir if lock_dir is not None else BRAIN_LOCK_DIR)


def _rmtree(path: Path) -> None:
    try:
        for child in path.iterdir():
            child.unlink()
        path.rmdir()
    except OSError:
        pass


def _commit_and_push(project: str, summary: str) -> None:
    """add + commit + push under the brain-sync lock. Push is fail-soft."""
    owned = acquire_brain_lock()
    if not owned:
        print(f"project-narratives: brain-sync lock is busy — {project} page written but not committed this run", file=sys.stderr)
        return
    try:
        _git_vault("add", "wiki/engineering/projects", "wiki/engineering/index.md")
        cres = _git_vault("commit", "-m", f"narrative({project}): {summary}")
        if cres.returncode != 0:
            print(f"project-narratives: git commit failed for {project}: {cres.stderr}", file=sys.stderr)
            return
        pres = _git_vault("push")
        if pres.returncode != 0:
            print(f"project-narratives: git push failed for {project} (brain-sync pushes on its next tick): {pres.stderr.strip()}", file=sys.stderr)
    finally:
        release_brain_lock(owned)


# --- Argo feed (System → Agents) ---------------------------------------------

def _resolve_argo_key() -> str:
    """HOMELAB_API_KEY from the process env (the argo-api skill's name for the
    argo key), else the secrets-run cache — mirrors dispatch-sweep.py's
    resolve_api_key(). '' on any failure; never raises."""
    val = os.environ.get("HOMELAB_API_KEY", "")
    if val:
        return val
    env = os.environ.copy()
    env["PATH"] = "/opt/homebrew/bin:/usr/local/bin:" + env.get("PATH", "/usr/bin:/bin")
    try:
        r = subprocess.run([str(SECRETS_RUN), "read", ARGO_API_KEY_REF],
                           capture_output=True, text=True, timeout=15, env=env)
    except (OSError, subprocess.SubprocessError):
        return ""
    return r.stdout.strip() if r.returncode == 0 else ""


def post_narrative_to_argo(project: str, summary: str, revised_at: str) -> bool:
    """Best-effort POST {project, summary, revisedAt, page} to Argo. True on a
    2xx, False otherwise — a 404 (endpoint not deployed yet) is logged at
    stderr and is NOT an error for the run. Never raises."""
    key = _resolve_argo_key()
    if not key:
        print(f"project-narratives: no argo key available, skipping Argo post for {project}", file=sys.stderr)
        return False
    body = json.dumps({
        "project": project, "summary": summary, "revisedAt": revised_at,
        "page": f"wiki/engineering/projects/{project}.md",
    }).encode()
    req = urllib.request.Request(
        f"{ARGO_API_BASE}{ARGO_NARRATIVES_PATH}", data=body, method="POST",
        headers={"Content-Type": "application/json", "Authorization": f"Bearer {key}"},
    )
    try:
        with urllib.request.urlopen(req, timeout=ARGO_HTTP_TIMEOUT) as resp:
            return 200 <= resp.status < 300
    except urllib.error.HTTPError as e:
        print(f"project-narratives: Argo returned {e.code} for {project} narrative post (non-fatal)", file=sys.stderr)
        return False
    except (urllib.error.URLError, TimeoutError, OSError) as e:
        print(f"project-narratives: Argo post failed for {project} (non-fatal): {e}", file=sys.stderr)
        return False


def _revert_or_delete_page(project: str, existed_before: bool) -> None:
    path = _page_path(project)
    if existed_before:
        _git_vault("checkout", "--", str(path.relative_to(VAULT_ROOT)))
    else:
        try:
            path.unlink()
        except OSError:
            pass


# --- per-project processing --------------------------------------------------

def _process_project(
    project: str, state: dict[str, Any], *, force: bool, commit: bool,
) -> str | None:
    """One project through the job -> write -> lint -> commit -> state
    pipeline. Mutates `state` in place (caller persists it); returns
    `'<project>: <summary>'` when a page was written, else None."""
    project_dir = SOURCE_ROOT / project
    head_sha = _git_head_sha(project_dir)
    transcript_mtime = _newest_transcript_mtime(project_dir)
    project_state = state.get(project)

    if not force and not needs_revision(project_state, head_sha, transcript_mtime):
        return None

    previous_page = None if force else _read_previous_page(project)
    since = None if force else (project_state or {}).get("lastRevisedAt")

    result = run_narrative_job(
        _base_url(), project, str(project_dir), previous_page, since,
    )
    if result is None:
        print(f"project-narratives: {project} — job unreachable/failed, retry next run", file=sys.stderr)
        return None

    if not result.get("changed"):
        state[project] = {
            **(project_state or {}),
            "lastCommit": head_sha,
            "lastSessionMtime": transcript_mtime,
        }
        return None

    page_markdown = result.get("page")
    summary = (result.get("summary") or "").strip()[:200]
    if not page_markdown:
        print(f"project-narratives: {project} — changed:true but no page, skipping", file=sys.stderr)
        return None

    existed_before = _page_path(project).exists()
    _write_page(project, page_markdown)
    _regenerate_projects_index()
    _ensure_engineering_index_links_projects()

    ok, lint_output = _run_vault_lint()
    if not ok:
        print(f"project-narratives: vault-lint failed for {project}:", file=sys.stderr)
        print(lint_output, file=sys.stderr)
        _revert_or_delete_page(project, existed_before)
        _regenerate_projects_index()
        return None

    if commit:
        _commit_and_push(project, summary)

    revised_at = _now_iso()
    state[project] = {
        "lastRevisedAt": revised_at,
        "lastCommit": head_sha,
        "lastSessionMtime": transcript_mtime,
        "summary": summary,
    }
    if commit:
        post_narrative_to_argo(project, summary, revised_at)
    return f"{project}: {summary}"


# --- CLI modes ----------------------------------------------------------------

def _cmd_run(restrict: set[str] | None) -> int:
    projects = discover_projects(restrict=restrict)
    state = _load_state()

    candidates = []
    for project in projects:
        project_dir = SOURCE_ROOT / project
        head_sha = _git_head_sha(project_dir)
        transcript_mtime = _newest_transcript_mtime(project_dir)
        if needs_revision(state.get(project), head_sha, transcript_mtime):
            candidates.append(project)

    def sort_key(p: str) -> tuple[bool, str]:
        ts = (state.get(p) or {}).get("lastRevisedAt")
        return (ts is not None, ts or "")

    candidates.sort(key=sort_key)

    revised_lines = []
    for project in candidates[: _max_per_run()]:
        line = _process_project(project, state, force=False, commit=True)
        _save_state(state)
        if line:
            revised_lines.append(line)

    for line in revised_lines:
        print(line)
    return 0


def _cmd_bootstrap(names: list[str]) -> int:
    state = _load_state()
    written = []
    for project in names:
        line = _process_project(project, state, force=True, commit=False)
        _save_state(state)
        if line:
            written.append(project)

    for project in written:
        print(str(_page_path(project)))
    return 0


def _cmd_briefing() -> int:
    state = _load_state()
    cutoff = _now_dt() - timedelta(hours=BRIEFING_WINDOW_HOURS)
    for project in sorted(state.keys()):
        pstate = state[project]
        ts = pstate.get("lastRevisedAt")
        if not ts:
            continue
        try:
            revised_at = datetime.fromisoformat(ts)
        except ValueError:
            continue
        if revised_at.tzinfo is None:
            revised_at = revised_at.replace(tzinfo=timezone.utc)
        if revised_at >= cutoff:
            print(f"narrative: {project} — {pstate.get('summary', '')}")
    return 0


def _cmd_dry_run(restrict: set[str] | None) -> int:
    projects = discover_projects(restrict=restrict)
    state = _load_state()
    found = False
    for project in projects:
        project_dir = SOURCE_ROOT / project
        head_sha = _git_head_sha(project_dir)
        transcript_mtime = _newest_transcript_mtime(project_dir)
        project_state = state.get(project)
        if needs_revision(project_state, head_sha, transcript_mtime):
            found = True
            print(f"{project}: {_dry_run_reason(project_state, head_sha, transcript_mtime)}")
    if not found:
        print("no projects need revision")
    return 0


def main(argv: list[str] | None = None) -> int:
    argv = list(argv if argv is not None else sys.argv[1:])

    restrict: set[str] | None = None
    if "--projects" in argv:
        idx = argv.index("--projects")
        if idx + 1 < len(argv):
            restrict = {p.strip() for p in argv[idx + 1].split(",") if p.strip()}

    if "--bootstrap" in argv:
        idx = argv.index("--bootstrap")
        if idx + 1 >= len(argv):
            print("usage: --bootstrap a,b,c", file=sys.stderr)
            return 2
        names = [p.strip() for p in argv[idx + 1].split(",") if p.strip()]
        return _cmd_bootstrap(names)

    if "--briefing" in argv:
        return _cmd_briefing()

    if "--dry-run" in argv:
        return _cmd_dry_run(restrict)

    if "--run" in argv:
        return _cmd_run(restrict)

    print(
        "usage: project-narratives.py --run | --bootstrap a,b,c | --briefing | "
        "--dry-run [--projects a,b]",
        file=sys.stderr,
    )
    return 2


if __name__ == "__main__":
    sys.exit(main())
