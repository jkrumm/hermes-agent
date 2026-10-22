#!/usr/bin/env python3
"""Assert docs/scheduled-jobs.md's registry against the live ~/.hermes/cron/jobs.json.

`jobs.json` is gitignored runtime state, so the git-tracked list of what
should be registered is the State-column table (plus the `## Retired`
bullet list) in `docs/scheduled-jobs.md`. This checks both directions:

- a `live` row needs a live job with `enabled: true` and `state != "paused"`
- a `paused (<reason>)` row needs `enabled: false` AND a recorded
  `paused_reason` (a paused job with no reason is a distinct error — `hermes
  cron pause` from the CLI cannot record one)
- a `## Retired` id must have NO live job
- any live job absent from the registry entirely is a ✗, enabled or not
  (that is how the brain drift audit lived for three weeks in jobs.json alone)
- a registry row's tracked `cron/*.prompt.txt` must equal that job's prompt in
  jobs.json (a copy edited on the live job alone is drift)
- a job pinned to a `model` must pin the live brain (`model.default` in the
  repo's config.yaml); an unpinned job is not checked

Used by `make status` (`Makefile`'s `status` target shells out to this
file); see `tests/test_check_cron_registry.py` for the unit coverage that a
20-line inline `python3 -c` one-liner couldn't have.
"""

from __future__ import annotations

import json
import os
import re
import sys

ROW_RE = re.compile(r"^\| `([0-9a-f]{12})` \|.*\| (live|paused \([^|]*\)) \|$", re.M)
RETIRED_RE = re.compile(r"^- \*\*`([0-9a-f]{12})`", re.M)
PROMPT_ROW_RE = re.compile(r"^\| `([0-9a-f]{12})` \|.*`(cron/[^`]+\.prompt\.txt)`", re.M)
DEFAULT_RE = re.compile(r"[ \t]+default:[ \t]*([^\s#]+)")


def parse_registry(md_text: str) -> tuple[list[tuple[str, str]], list[str]]:
    """Return (rows, retired_ids) parsed out of the registry doc.

    `rows` is every `| `id` | ... | live|paused (...) |` table row, in
    document order, as `(id, state)`. `retired_ids` is every id named in a
    `## Retired` bullet (`- **`id`** — ...`).
    """
    rows = ROW_RE.findall(md_text)
    retired = RETIRED_RE.findall(md_text)
    return rows, retired


def compare(rows: list[tuple[str, str]], retired: list[str], jobs: dict[str, dict]) -> list[str]:
    """Return one error sentence per mismatch; empty means everything matches."""
    errors: list[str] = []

    for job_id, state in rows:
        job = jobs.get(job_id)
        if state == "live":
            if job is None:
                errors.append(
                    f"job {job_id} in docs/scheduled-jobs.md is not registered [hermes cron list]"
                )
            elif not job.get("enabled", True) or job.get("state") == "paused":
                errors.append(
                    f"live job {job_id} ({job.get('name')}) is registered live in "
                    "docs/scheduled-jobs.md but is paused/disabled"
                )
        else:
            if job is None:
                errors.append(
                    f"job {job_id} in docs/scheduled-jobs.md (paused) is not registered "
                    "[hermes cron list]"
                )
            elif job.get("enabled", True):
                errors.append(
                    f"job {job_id} ({job.get('name')}) is still enabled in the live gateway "
                    "but marked paused in docs/scheduled-jobs.md"
                )
            elif not job.get("paused_reason"):
                errors.append(
                    f"job {job_id} ({job.get('name')}) paused with no reason — `hermes cron "
                    "pause` from the CLI cannot record one; pause from chat or document in "
                    "the registry"
                )

    for job_id in retired:
        if job_id in jobs:
            errors.append(
                f"job {job_id} is marked retired in docs/scheduled-jobs.md but still has a "
                "live job [hermes cron list]"
            )

    registered = {job_id for job_id, _ in rows} | set(retired)
    for job_id in sorted(jobs):
        if job_id not in registered:
            errors.append(
                f"live job {job_id} ({jobs[job_id].get('name')}) is not in "
                "docs/scheduled-jobs.md"
            )

    return errors


def parse_prompt_files(md_text: str) -> dict[str, str]:
    """`{job_id: 'cron/<name>.prompt.txt'}` for every registry row that names a
    tracked prompt file in its Script / prompt column."""
    return {m.group(1): m.group(2) for m in PROMPT_ROW_RE.finditer(md_text)}


def parse_brain_model(config_text: str) -> str | None:
    """`model.default` from config.yaml — the live brain. Scans only the
    top-level `model:` block so a commented `# default:` elsewhere never wins."""
    in_model = False
    for line in config_text.splitlines():
        if line and not line[0].isspace() and not line.startswith("#"):
            in_model = line.startswith("model:")
            continue
        m = DEFAULT_RE.match(line)
        if in_model and m:
            return m.group(1)
    return None


def compare_prompts(prompt_files: dict[str, str], jobs: dict[str, dict], read_file) -> list[str]:
    """Each registered job's prompt in jobs.json must equal its tracked
    cron/*.prompt.txt (whitespace at the ends ignored). `read_file(rel)` returns
    the file's text or None when it is missing."""
    errors: list[str] = []
    for job_id, rel in prompt_files.items():
        job = jobs.get(job_id)
        if job is None:
            continue
        repo_text = read_file(rel)
        if repo_text is None:
            errors.append(f"job {job_id} names {rel} in docs/scheduled-jobs.md but the file is missing")
        elif (job.get("prompt") or "").strip() != repo_text.strip():
            errors.append(
                f"job {job_id} ({job.get('name')}) prompt in jobs.json differs from {rel} — "
                "push the edit with `hermes cron edit`"
            )
    return errors


def compare_pins(jobs: dict[str, dict], brain_model: str | None) -> list[str]:
    """A job with a pinned `model` must pin the live brain. An unpinned job
    (empty model) follows the global default and is not checked here."""
    if brain_model is None:
        return ["could not read model.default from config.yaml — cannot check job pins"]
    errors: list[str] = []
    for job_id in sorted(jobs):
        job = jobs[job_id]
        pinned = job.get("model")
        if pinned and pinned != brain_model:
            errors.append(
                f"job {job_id} ({job.get('name')}) is pinned to model {pinned} but the brain is "
                f"{brain_model} (config.yaml model.default) — re-pin with `hermes cron edit`"
            )
    return errors


def _load_jobs(jobs_json_path: str) -> dict[str, dict]:
    if not os.path.exists(jobs_json_path):
        return {}
    with open(jobs_json_path) as f:
        data = json.load(f)
    return {j["id"]: j for j in data.get("jobs", [])}


def main(argv: list[str] | None = None) -> int:
    args = argv if argv is not None else sys.argv[1:]
    md_path = args[0] if len(args) > 0 else os.environ.get("HERMES_SCHEDULED_JOBS_MD")
    jobs_json_path = args[1] if len(args) > 1 else os.environ.get("HERMES_CRON_JOBS_JSON")
    if not md_path or not jobs_json_path:
        print("usage: check-cron-registry.py <scheduled-jobs.md> <cron/jobs.json>", file=sys.stderr)
        return 2

    # A registry MISMATCH is exit 1 with one ✗ line per finding; an inability
    # to compare at all (unreadable file, malformed JSON) is exit 2 with its
    # own ✗ line, so `make status` never has to guess which one it saw.
    try:
        with open(md_path) as f:
            md_text = f.read()
        jobs = _load_jobs(jobs_json_path)
    except (OSError, ValueError) as e:
        print(f"    ✗ cron registry [could not compare jobs.json against docs/scheduled-jobs.md: {e}]")
        return 2

    rows, retired = parse_registry(md_text)
    if not rows and not retired:
        print("    ✗ cron registry [docs/scheduled-jobs.md has no job-id rows]")
        return 1

    repo_root = os.path.dirname(os.path.dirname(os.path.abspath(md_path)))

    def read_file(rel: str) -> str | None:
        try:
            with open(os.path.join(repo_root, rel)) as f:
                return f.read()
        except OSError:
            return None

    try:
        with open(os.path.join(repo_root, "config.yaml")) as f:
            brain_model = parse_brain_model(f.read())
    except OSError:
        brain_model = None

    errors = compare(rows, retired, jobs)
    errors += compare_prompts(parse_prompt_files(md_text), jobs, read_file)
    errors += compare_pins(jobs, brain_model)

    if errors:
        for e in errors:
            print(f"    ✗ cron registry: {e}")
        return 1

    live_n = sum(1 for _, state in rows if state == "live")
    paused_n = len(rows) - live_n
    print(
        f"    ✓ cron registry ({live_n} live, {paused_n} paused, {len(retired)} retired — "
        "matches docs/scheduled-jobs.md; prompts match cron/*.prompt.txt; pins match config.yaml)"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
