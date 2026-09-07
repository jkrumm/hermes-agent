"""Regression suite for scripts/project-narratives.py's pure functions and
the --run CLI path.

Covers: needs_revision()'s branches (never revised, HEAD moved, newer
transcript, nothing changed); project discovery's deny list + env skip on a
temp SourceRoot; projects/index.md rendering from page frontmatter; state
round-trip; and main(["--run"]) end to end with a monkeypatched job client
(run_narrative_job) and a monkeypatched subprocess.run recording every git/
node invocation — changed:false writes nothing and still advances state,
changed:true writes the page + index, runs lint, and commits by name
(`git -C <vault> ...`); a lint failure reverts the page and skips the
commit.

No network, no real vault, no real git/node process — every case builds its
fixtures under a temp directory and reassigns the module's path globals
(SOURCE_ROOT, VAULT_ROOT, PROJECTS_DIR, ENGINEERING_INDEX, VAULT_LINT,
STATE_PATH, CLAUDE_PROJECTS_DIR) before calling into it, mirroring how
test_agents_overview.py reassigns ao.fetch_agents/ao.refresh.

Run against the live tree:

    ~/.hermes/hermes-agent/venv/bin/python3 tests/test_project_narratives.py

Exit status is 0 only when every case matches.
"""

from __future__ import annotations

import importlib.util
import io
import json
import shutil
import sys
import tempfile
from contextlib import redirect_stdout
from pathlib import Path

_HERE = Path(__file__).resolve().parent
_spec = importlib.util.spec_from_file_location(
    "project_narratives", _HERE.parent / "scripts" / "project-narratives.py",
)
assert _spec and _spec.loader, "Failed to load project-narratives.py"
pn = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(pn)

failures: list[str] = []


def check(name: str, got, want) -> None:
    if got == want:
        print(f"  ok   {name}")
    else:
        failures.append(f"{name}: got {got!r}, want {want!r}")
        print(f"  FAIL {name}: got {got!r}, want {want!r}")


def check_true(name: str, cond: bool) -> None:
    check(name, bool(cond), True)


TMP_ROOT = Path(tempfile.mkdtemp(prefix="project-narratives-test-"))


def _reset_paths() -> None:
    """Point every module-level path constant at a fresh subtree of
    TMP_ROOT — reassigning the global (not a default-arg capture) so every
    function that reads it picks up the new value on its next call."""
    root = TMP_ROOT / f"case-{_reset_paths.counter}"
    _reset_paths.counter += 1
    pn.SOURCE_ROOT = root / "SourceRoot"
    pn.VAULT_ROOT = pn.SOURCE_ROOT / "brain"
    pn.PROJECTS_DIR = pn.VAULT_ROOT / "wiki" / "engineering" / "projects"
    pn.ENGINEERING_INDEX = pn.VAULT_ROOT / "wiki" / "engineering" / "index.md"
    pn.VAULT_LINT = pn.VAULT_ROOT / ".scripts" / "vault-lint.mjs"
    pn.STATE_PATH = root / "state.json"
    pn.CLAUDE_PROJECTS_DIR = root / "claude-projects"
    pn.SOURCE_ROOT.mkdir(parents=True, exist_ok=True)
    return root


_reset_paths.counter = 0


def _mk_repo(name: str) -> Path:
    repo = pn.SOURCE_ROOT / name
    (repo / ".git").mkdir(parents=True, exist_ok=True)
    return repo


def _write_engineering_index() -> None:
    pn.ENGINEERING_INDEX.parent.mkdir(parents=True, exist_ok=True)
    pn.ENGINEERING_INDEX.write_text(
        "---\n"
        "type: Index\n"
        "title: Engineering (wiki)\n"
        "description: test fixture\n"
        "tags:\n"
        "  - moc\n"
        "  - engineering\n"
        "timestamp: 2026-09-04\n"
        "---\n\n"
        "# Engineering (wiki)\n\n"
        "## Concepts\n\n"
        "- [[north-star-stack|North Star]] — the stack.\n"
    )


def make_fake_run(calls: list[list[str]], *, head_sha: str = "abc123", lint_ok: bool = True):
    def fake_run(cmd, **kwargs):
        calls.append(list(cmd))

        class R:
            pass

        r = R()
        r.stdout = ""
        r.stderr = ""
        if cmd[0] == "git" and "rev-parse" in cmd:
            r.returncode = 0
            r.stdout = head_sha + "\n"
        elif cmd[0] == "node":
            r.returncode = 0 if lint_ok else 1
            if not lint_ok:
                r.stderr = "frontmatter: missing `description`"
        else:
            r.returncode = 0
        return r

    return fake_run


# --- needs_revision() --------------------------------------------------------

print("1. needs_revision() — never revised (state is None) always needs revision")
check_true("None state -> True", pn.needs_revision(None, "sha1", None))

print("\n2. needs_revision() — HEAD moved since lastCommit")
state = {"lastCommit": "sha1", "lastSessionMtime": 100.0}
check_true("HEAD moved -> True", pn.needs_revision(state, "sha2", None))

print("\n3. needs_revision() — a transcript is newer than lastSessionMtime")
state = {"lastCommit": "sha1", "lastSessionMtime": 100.0}
check_true("newer transcript -> True", pn.needs_revision(state, "sha1", 200.0))

print("\n4. needs_revision() — nothing changed")
state = {"lastCommit": "sha1", "lastSessionMtime": 100.0}
check("HEAD same, transcript older/absent -> False", pn.needs_revision(state, "sha1", 50.0), False)
check("HEAD same, no transcript at all -> False", pn.needs_revision(state, "sha1", None), False)

print("\n5. needs_revision() — lastSessionMtime absent, a transcript exists")
state = {"lastCommit": "sha1", "lastSessionMtime": None}
check_true("no prior mtime, any transcript -> True", pn.needs_revision(state, "sha1", 1.0))


# --- discover_projects() -----------------------------------------------------

print("\n6. discover_projects() — deny list + env skip on a temp SourceRoot")
_reset_paths()
for name in ["proj-a", "proj-b", "dotfiles-private", "hermes-webui", "brain", "not-a-repo"]:
    if name == "not-a-repo":
        (pn.SOURCE_ROOT / name).mkdir(parents=True, exist_ok=True)  # dir, no .git
    else:
        _mk_repo(name)

import os as _os

check(
    "deny list + non-git dir excluded",
    pn.discover_projects(),
    ["proj-a", "proj-b"],
)

_os.environ["HERMES_NARRATIVE_SKIP"] = "proj-a"
try:
    check("env skip removes proj-a", pn.discover_projects(), ["proj-b"])
finally:
    del _os.environ["HERMES_NARRATIVE_SKIP"]

check("restrict narrows to the given set", pn.discover_projects(restrict={"proj-b"}), ["proj-b"])


# --- projects/index.md rendering ---------------------------------------------

print("\n7. _regenerate_projects_index() — renders from each page's frontmatter")
_reset_paths()
pn.PROJECTS_DIR.mkdir(parents=True, exist_ok=True)
(pn.PROJECTS_DIR / "meteo.md").write_text(
    "---\ntype: Reference\ndescription: Weather/wave service.\n---\n\n# meteo\n"
)
(pn.PROJECTS_DIR / "sideclaw.md").write_text(
    "---\ntype: Reference\ndescription: Local MCP daemon.\n---\n\n# sideclaw\n"
)
pn._regenerate_projects_index()
index_text = (pn.PROJECTS_DIR / "index.md").read_text()
check_true("frontmatter type: Index", "type: Index" in index_text)
check_true("frontmatter title: Projects", "title: Projects" in index_text)
check_true("meteo line with its description", "- [[meteo]] — Weather/wave service." in index_text)
check_true("sideclaw line with its description", "- [[sideclaw]] — Local MCP daemon." in index_text)

print("\n8. _ensure_engineering_index_links_projects() — adds a Subdomains link once")
_write_engineering_index()
pn._ensure_engineering_index_links_projects()
text_after_first = pn.ENGINEERING_INDEX.read_text()
check_true("Subdomains section added", "## Subdomains" in text_after_first)
check_true("projects index link present", pn.SUBDOMAIN_LINK in text_after_first)
pn._ensure_engineering_index_links_projects()
text_after_second = pn.ENGINEERING_INDEX.read_text()
check("idempotent — no duplicate link", text_after_second.count(pn.SUBDOMAIN_LINK), 1)


# --- state round-trip ---------------------------------------------------------

print("\n9. state round-trip — save then load")
_reset_paths()
state = {"meteo": {"lastRevisedAt": "2026-09-07T06:00:00+00:00", "lastCommit": "sha1",
                    "lastSessionMtime": 123.0, "summary": "Added CDN icon mirroring."}}
pn._save_state(state)
loaded = pn._load_state()
check("round-tripped state matches", loaded, state)


# --- main(["--run"]) — changed:false ------------------------------------------

print("\n10. main(['--run']) — changed:false writes nothing, advances state")
_reset_paths()
_mk_repo("meteo")
calls: list[list[str]] = []
pn.subprocess.run = make_fake_run(calls, head_sha="sha-new")
pn.run_narrative_job = lambda base, project, cwd, previous_page, since, **kw: {
    "project": project, "changed": False, "reason": "no substantive change",
    "summary": None, "page": None, "sections": [], "inputs": {}, "model": "test",
}
try:
    out = io.StringIO()
    with redirect_stdout(out):
        rc = pn.main(["--run"])
    check("exit 0", rc, 0)
    check("no stdout — nothing revised", out.getvalue(), "")
    check_true("no page written", not (pn.PROJECTS_DIR / "meteo.md").exists())
    saved = pn._load_state()
    check("state advanced to the new HEAD", saved["meteo"]["lastCommit"], "sha-new")
    # git rev-parse HEAD is expected (computing head_sha for the gate/state);
    # no lint (node) and no add/commit for a changed:false result.
    check_true("no vault-lint call", not any(c[0] == "node" for c in calls))
    check_true("no git add/commit calls", not any("add" in c or "commit" in c for c in calls))
finally:
    del pn.run_narrative_job


# --- main(["--run"]) — changed:true --------------------------------------------

print("\n11. main(['--run']) — changed:true writes the page + index, lints, commits by name")
_reset_paths()
_mk_repo("meteo")
_write_engineering_index()
calls = []
pn.subprocess.run = make_fake_run(calls, head_sha="sha-abc", lint_ok=True)
page_md = (
    "---\ntype: Reference\ndescription: Weather/wave service — 8 mini LaunchAgents.\n"
    "timestamp: 2026-09-07\n---\n\n# meteo\n\nShipped CDN icon mirroring this week.\n"
)
pn.run_narrative_job = lambda base, project, cwd, previous_page, since, **kw: {
    "project": project, "changed": True, "reason": "commits landed",
    "summary": "Shipped CDN icon mirroring.", "page": page_md, "sections": ["summary"],
    "inputs": {"commits": 3, "sessions": 1, "sinceUsed": since}, "model": "test",
}
try:
    out = io.StringIO()
    with redirect_stdout(out):
        rc = pn.main(["--run"])
    check("exit 0", rc, 0)
    check("stdout is the one revised line", out.getvalue().strip(), "meteo: Shipped CDN icon mirroring.")
    check_true("page written", (pn.PROJECTS_DIR / "meteo.md").exists())
    check_true("projects index regenerated", (pn.PROJECTS_DIR / "index.md").exists())
    check_true("engineering index links the projects index", pn.SUBDOMAIN_LINK in pn.ENGINEERING_INDEX.read_text())

    node_calls = [c for c in calls if c[0] == "node"]
    check("vault-lint invoked exactly once", len(node_calls), 1)

    git_add_calls = [c for c in calls if c[0] == "git" and "add" in c]
    git_commit_calls = [c for c in calls if c[0] == "git" and "commit" in c]
    check("exactly one git add", len(git_add_calls), 1)
    check("exactly one git commit", len(git_commit_calls), 1)
    check_true("git add names the vault with -C", git_add_calls[0][:3] == ["git", "-C", str(pn.VAULT_ROOT)])
    check_true("git commit names the vault with -C", git_commit_calls[0][:3] == ["git", "-C", str(pn.VAULT_ROOT)])
    check_true("commit message names the project", any("narrative(meteo):" in a for a in git_commit_calls[0]))

    saved = pn._load_state()
    check("state records the new commit", saved["meteo"]["lastCommit"], "sha-abc")
    check("state records the summary", saved["meteo"]["summary"], "Shipped CDN icon mirroring.")
finally:
    del pn.run_narrative_job


# --- main(["--run"]) — lint failure reverts and skips the commit -------------

print("\n12. main(['--run']) — a lint failure reverts the page and skips the commit")
_reset_paths()
_mk_repo("meteo")
_write_engineering_index()
calls = []
pn.subprocess.run = make_fake_run(calls, head_sha="sha-bad", lint_ok=False)
pn.run_narrative_job = lambda base, project, cwd, previous_page, since, **kw: {
    "project": project, "changed": True, "reason": "commits landed",
    "summary": "Bad page.", "page": "---\nbroken frontmatter\n---\n\n# meteo\n",
    "sections": [], "inputs": {}, "model": "test",
}
try:
    out = io.StringIO()
    with redirect_stdout(out):
        rc = pn.main(["--run"])
    check("exit 0 even on a lint failure", rc, 0)
    check("no stdout — nothing counts as revised", out.getvalue(), "")
    git_commit_calls = [c for c in calls if c[0] == "git" and "commit" in c]
    check("no commit issued", len(git_commit_calls), 0)
    saved = pn._load_state()
    check_true("state NOT advanced — retried next run", "meteo" not in saved)
finally:
    del pn.run_narrative_job


# --- --bootstrap -----------------------------------------------------------

print("\n13. main(['--bootstrap', 'meteo']) — forces since=null, writes but never commits")
_reset_paths()
_mk_repo("meteo")
_write_engineering_index()
calls = []
pn.subprocess.run = make_fake_run(calls, head_sha="sha-boot", lint_ok=True)
seen_since = []
seen_previous = []


def _bootstrap_job(base, project, cwd, previous_page, since, **kw):
    seen_since.append(since)
    seen_previous.append(previous_page)
    return {
        "project": project, "changed": True, "reason": "bootstrap",
        "summary": "Bootstrapped.", "page": "---\ntype: Reference\ndescription: x.\n---\n\n# meteo\n",
        "sections": [], "inputs": {}, "model": "test",
    }


pn.run_narrative_job = _bootstrap_job
try:
    out = io.StringIO()
    with redirect_stdout(out):
        rc = pn.main(["--bootstrap", "meteo"])
    check("exit 0", rc, 0)
    check("prints the page path", out.getvalue().strip(), str(pn._page_path("meteo")))
    check("since forced to None", seen_since, [None])
    check("previousPage forced to None", seen_previous, [None])
    git_commit_calls = [c for c in calls if c[0] == "git" and "commit" in c]
    check("bootstrap never commits", len(git_commit_calls), 0)
finally:
    del pn.run_narrative_job


# --- --briefing --------------------------------------------------------------

print("\n14. main(['--briefing']) — only projects revised in the last 26h")
_reset_paths()
import datetime as _dt

now = pn._now_dt()
recent = (now - _dt.timedelta(hours=1)).isoformat()
stale = (now - _dt.timedelta(hours=48)).isoformat()
pn._save_state({
    "meteo": {"lastRevisedAt": recent, "summary": "Fresh narrative."},
    "sideclaw": {"lastRevisedAt": stale, "summary": "Old narrative."},
})
out = io.StringIO()
with redirect_stdout(out):
    rc = pn.main(["--briefing"])
check("exit 0", rc, 0)
check("only the recent project surfaces", out.getvalue().strip(), "narrative: meteo — Fresh narrative.")

print("\n15. main(['--briefing']) — nothing revised recently prints nothing")
_reset_paths()
pn._save_state({"meteo": {"lastRevisedAt": stale, "summary": "Old narrative."}})
out = io.StringIO()
with redirect_stdout(out):
    rc = pn.main(["--briefing"])
check("exit 0", rc, 0)
check("silent", out.getvalue(), "")


# --- --dry-run ----------------------------------------------------------------

print("\n16. main(['--dry-run']) — lists projects that would be revised and why")
_reset_paths()
_mk_repo("meteo")
calls = []
pn.subprocess.run = make_fake_run(calls, head_sha="sha-dry")
out = io.StringIO()
with redirect_stdout(out):
    rc = pn.main(["--dry-run"])
check("exit 0", rc, 0)
check_true("meteo listed as never revised", "meteo: never revised" in out.getvalue())

print("\n17. main(['--dry-run']) — nothing needs revision")
_reset_paths()
_mk_repo("meteo")
pn._save_state({"meteo": {"lastCommit": "sha-dry2", "lastSessionMtime": None}})
calls = []
pn.subprocess.run = make_fake_run(calls, head_sha="sha-dry2")
out = io.StringIO()
with redirect_stdout(out):
    rc = pn.main(["--dry-run"])
check("exit 0", rc, 0)
check("reports nothing to do", out.getvalue().strip(), "no projects need revision")


shutil.rmtree(TMP_ROOT, ignore_errors=True)

print()
if failures:
    print(f"{len(failures)} failure(s):")
    for f in failures:
        print(f"  - {f}")
    sys.exit(1)
print("all cases as expected")
