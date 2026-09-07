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

DEFAULT_BASE = "http://localhost:7705"
BASE_ENV = "HERMES_NARRATIVE_SIDECLAW_BASE"

# Deny-listed projects: private-secrets repos, the disposable dispatch
# target, the upstream-fork checkout, and the vault itself (a narrative
# page ABOUT the vault, written INTO the vault, is a confusing loop).
DENY_LIST = {"dotfiles-private", "homelab-private", "dispatch-scratch", "hermes-webui", "brain"}
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


# --- sideclaw job client (the seam tests monkeypatch) -----------------------

def run_narrative_job(
    base: str, project: str, cwd: str, previous_page: str | None, since: str | None,
    *, timeout_s: int = 300, poll_interval: int = 10,
) -> dict[str, Any] | None:
    """POST /api/jobs {tool:narrative,...}, poll GET /api/jobs/<id> until
    done|failed, bounded by timeout_s (sideclaw's own contract: up to 5 min
    for a Sonnet pass). Returns the job's `result` dict on `done`, None on
    any transport failure, `failed`, or timeout — callers treat None as
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

    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        time.sleep(poll_interval)
        try:
            with urllib.request.urlopen(f"{base}/api/jobs/{job_id}", timeout=15) as resp:
                polled = json.loads(resp.read().decode())
        except (urllib.error.URLError, urllib.error.HTTPError, json.JSONDecodeError, TimeoutError, OSError):
            return None
        job = polled.get("job") or polled
        status = job.get("status")
        if status == "done":
            return job.get("result")
        if status == "failed":
            return None
    return None


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
        _git_vault("add", "wiki/engineering/projects", "wiki/engineering/index.md")
        cres = _git_vault("commit", "-m", f"narrative({project}): {summary}")
        if cres.returncode != 0:
            print(f"project-narratives: git commit failed for {project}: {cres.stderr}", file=sys.stderr)

    state[project] = {
        "lastRevisedAt": _now_iso(),
        "lastCommit": head_sha,
        "lastSessionMtime": transcript_mtime,
        "summary": summary,
    }
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
