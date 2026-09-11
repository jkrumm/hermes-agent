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

    errors = compare(rows, retired, jobs)

    if errors:
        for e in errors:
            print(f"    ✗ cron registry: {e}")
        return 1

    live_n = sum(1 for _, state in rows if state == "live")
    paused_n = len(rows) - live_n
    print(
        f"    ✓ cron registry ({live_n} live, {paused_n} paused, {len(retired)} retired — "
        "matches docs/scheduled-jobs.md)"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
