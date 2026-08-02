#!/usr/bin/env python3
"""Regression suite for `format_message()` in scripts/dispatch-sweep.py's
merged-dispatch rendering.

WHY THIS GUARD EXISTS. `scripts/hermes-cc.sh`'s `merge <job-id>` verb
deliberately does NOT stamp `reported_at` on the dispatch row — the merge
announcement and the sweeper's own verdict message are considered two
different things, sent at two different times. That is correct, but it
means the sweeper still owes a verdict for a dispatch that has already been
merged, and until this fix it rendered that verdict exactly as it would for
an untouched draft PR.

Observed live 2026-08-02, job `6f7c9cc4-641d-4088-9a94-65845a1b1f4b`:

    merged_at   = 2026-08-02T19:06:00.574298+00:00
    reported_at = 2026-08-02T19:10:02.336915+00:00

Hermes announced the merge in Slack, and four minutes later the sweeper
posted "here is your draft PR, review it" for a PR that was already merged
and closed. The `dispatches` table already carried a `merged_at TEXT`
column; `format_message()` simply never read it.

The fix threads `merged_at` from the row into `format_message()` and makes
a merged dispatch render honestly: the header gets a merged marker, the
artifact line states the merge instead of implying review is pending, and
the footer's `next` field stops repeating the episode's stale `nextAction`
("review the draft PR") in favour of `none (merged)`. A malformed or
missing `merged_at` value must fail *toward* still calling it merged — the
merge happened; only the display of when degrades — because the entire
point of this guard is to stop a stale review instruction from reaching a
human, and silently falling back to the old wording would reintroduce
exactly that bug.

Run against the live tree:

    ~/.hermes/hermes-agent/venv/bin/python3 tests/test_dispatch_sweep.py

Exit status is 0 only when every case matches.
"""

import importlib.util
import sys
from pathlib import Path

SCRIPT_PATH = Path(__file__).resolve().parent.parent / "scripts" / "dispatch-sweep.py"

_spec = importlib.util.spec_from_file_location("dispatch_sweep", SCRIPT_PATH)
assert _spec is not None and _spec.loader is not None
dispatch_sweep = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(dispatch_sweep)

format_message = dispatch_sweep.format_message

JOB_ID = "6f7c9cc4-641d-4088-9a94-65845a1b1f4b"
JOB_SHORT = JOB_ID[:8]
STALE_NEXT_ACTION = "review the draft PR"

BASE_RESULT = {
    "summary": "Fixed the flaky test.",
    "artifactUrl": "https://github.com/jkrumm/example/pull/12",
    "verdict": "All good.",
    "recommendation": "Merge when ready.",
    "evidence": [{"file": "tests/test_x.py", "detail": "fixed race"}],
    "confidence": "high",
    "nextAction": STALE_NEXT_ACTION,
}

# Byte-for-byte expected output of the unmerged path — this is the
# regression bar. If this string ever needs editing, the unmerged rendering
# changed and that is a different, deliberate change, not a side effect of
# the merged-handling patch.
EXPECTED_UNMERGED = (
    ":mag: Dispatch verdict — example\n"
    "Fixed the flaky test.\n"
    "*Artifact:* https://github.com/jkrumm/example/pull/12\n"
    "\n"
    "All good.\n"
    "\n"
    "*Recommendation:* Merge when ready.\n"
    "\n"
    "*Evidence:*\n"
    "- `tests/test_x.py` — fixed race\n"
    "\n"
    f"_confidence high · next {STALE_NEXT_ACTION} · tier implement · job `{JOB_SHORT}`_"
)


def _unmerged() -> str:
    return format_message(
        repo="example", tier="implement", job_id=JOB_ID, status="done",
        result=dict(BASE_RESULT), error=None,
    )


def _merged(merged_at: str, *, result_overrides: dict | None = None) -> str:
    result = dict(BASE_RESULT)
    if result_overrides is not None:
        result = result_overrides
    return format_message(
        repo="example", tier="implement", job_id=JOB_ID, status="done",
        result=result, error=None, merged_at=merged_at,
    )


def main() -> int:
    failures: list[str] = []

    def check(label: str, cond: bool) -> None:
        if not cond:
            failures.append(label)

    # --- unmerged rendering is untouched --------------------------------
    unmerged_cases = 0
    unmerged_ok = 0

    unmerged_cases += 1
    actual = _unmerged()
    if actual == EXPECTED_UNMERGED:
        unmerged_ok += 1
    else:
        failures.append(
            f"unmerged rendering drifted from the pinned string:\n--- expected ---\n"
            f"{EXPECTED_UNMERGED!r}\n--- actual ---\n{actual!r}"
        )

    # --- merged rendering: header, artifact line, footer ----------------
    merged_body = _merged("2026-08-02T19:06:00.574298+00:00")
    merged_checks = [
        ("header carries merged marker",
         ":white_check_mark: Dispatch verdict — example _(already merged)_" in merged_body),
        ("header no longer uses the plain :mag: marker",
         ":mag: Dispatch verdict" not in merged_body),
        ("artifact line states the merge",
         "*Artifact:* https://github.com/jkrumm/example/pull/12 — *merged* 2026-08-02 19:06 UTC"
         in merged_body),
        ("footer says next none (merged)",
         f"_confidence high · next none (merged) · tier implement · job `{JOB_SHORT}`_"
         in merged_body),
        ("footer does not repeat the episode's stale nextAction",
         STALE_NEXT_ACTION not in merged_body),
        ("confidence and tier survive unchanged",
         "confidence high" in merged_body and "tier implement" in merged_body),
    ]
    for label, cond in merged_checks:
        check(f"merged rendering: {label}", cond)
    merged_ok = sum(1 for _, cond in merged_checks if cond)

    # --- malformed / garbage merged_at still renders as merged ----------
    garbage_body = _merged("not-a-real-timestamp")
    garbage_checks = [
        ("header still carries merged marker",
         "_(already merged)_" in garbage_body),
        ("raw garbage value is shown rather than dropped or raised",
         "not-a-real-timestamp" in garbage_body),
        ("footer still says next none (merged)",
         "next none (merged)" in garbage_body),
    ]
    for label, cond in garbage_checks:
        check(f"garbage merged_at: {label}", cond)
    garbage_ok = sum(1 for _, cond in garbage_checks if cond)

    # A completely empty string is just as malformed as garbage text, but
    # bool("") is False in Python, so this is also exercised under the
    # not-merged section below — the two must not be confused.
    empty_string_still_not_merged = "_(already merged)_" not in _merged("")
    check("empty-string merged_at treated as not merged, not as garbage",
          empty_string_still_not_merged)

    # --- merged_at empty string / None => not merged ---------------------
    not_merged_checks = [
        ("merged_at='' renders identically to no merged_at at all",
         _merged("") == _unmerged()),
        ("merged_at=None (the default) renders identically to no merged_at at all",
         format_message(repo="example", tier="implement", job_id=JOB_ID, status="done",
                         result=dict(BASE_RESULT), error=None, merged_at=None) == _unmerged()),
    ]
    for label, cond in not_merged_checks:
        check(f"not-merged treatment: {label}", cond)
    not_merged_ok = sum(1 for _, cond in not_merged_checks if cond)

    # --- pinned: a merged degraded row --------------------------------
    degraded_result = dict(BASE_RESULT)
    degraded_result["degraded"] = True
    degraded_merged_body = _merged("2026-08-02T19:06:00+00:00", result_overrides=degraded_result)
    degraded_checks = [
        ("degraded header carries the merged suffix too",
         ":grey_question: Dispatch degraded — example _(already merged)_" in degraded_merged_body),
        ("degraded explanatory line is preserved",
         "this is not a finding about the repo" in degraded_merged_body),
        ("footer still says next none (merged) on a degraded+merged row",
         "next none (merged)" in degraded_merged_body),
    ]
    for label, cond in degraded_checks:
        check(f"merged degraded row: {label}", cond)
    degraded_ok = sum(1 for _, cond in degraded_checks if cond)

    # --- pinned: a merged row whose result has no artifactUrl ----------
    # Per the brief, this branch cannot actually occur for a real merged
    # dispatch (a merge implies a PR, hence an artifactUrl) — pinning it
    # anyway so the behaviour is deliberate, not accidental. Implementation
    # choice pinned here: the existing `elif branch:` fallback is left
    # exactly as-is (no merged suffix grafted onto the branch line), while
    # the header and footer still reflect the merge.
    no_artifact_result = {
        "summary": "Pushed a fix, no PR opened.",
        "branch": "dispatch/example-fix",
        "confidence": "medium",
        "nextAction": STALE_NEXT_ACTION,
    }
    no_artifact_body = _merged("2026-08-02T19:06:00+00:00", result_overrides=no_artifact_result)
    no_artifact_checks = [
        ("header still carries the merged marker",
         "_(already merged)_" in no_artifact_body),
        ("branch line is unchanged — no merged suffix grafted onto it",
         "*Branch pushed, no PR opened:* `dispatch/example-fix`" in no_artifact_body),
        ("footer still says next none (merged)",
         "next none (merged)" in no_artifact_body),
    ]
    for label, cond in no_artifact_checks:
        check(f"merged, no artifactUrl: {label}", cond)
    no_artifact_ok = sum(1 for _, cond in no_artifact_checks if cond)

    # --- failed / interrupted rows are unaffected by merged_at ----------
    failed_without_merge = format_message(
        repo="example", tier="investigate", job_id=JOB_ID, status="failed",
        result=None, error="sideclaw timed out",
    )
    failed_with_merge = format_message(
        repo="example", tier="investigate", job_id=JOB_ID, status="failed",
        result=None, error="sideclaw timed out", merged_at="2026-08-02T19:06:00+00:00",
    )
    interrupted_without_merge = format_message(
        repo="example", tier="investigate", job_id=JOB_ID, status="interrupted",
        result=None, error=None,
    )
    interrupted_with_merge = format_message(
        repo="example", tier="investigate", job_id=JOB_ID, status="interrupted",
        result=None, error=None, merged_at="2026-08-02T19:06:00+00:00",
    )
    terminal_checks = [
        ("failed rendering identical with and without merged_at",
         failed_without_merge == failed_with_merge),
        ("failed rendering carries no merged marker",
         "merged" not in failed_with_merge.lower()),
        ("interrupted rendering identical with and without merged_at",
         interrupted_without_merge == interrupted_with_merge),
        ("interrupted rendering carries no merged marker",
         "merged" not in interrupted_with_merge.lower()),
    ]
    for label, cond in terminal_checks:
        check(f"failed/interrupted unaffected: {label}", cond)
    terminal_ok = sum(1 for _, cond in terminal_checks if cond)

    # --- done, no result object: also unaffected by merged_at ----------
    no_result_without_merge = format_message(
        repo="example", tier="investigate", job_id=JOB_ID, status="done",
        result=None, error=None,
    )
    no_result_with_merge = format_message(
        repo="example", tier="investigate", job_id=JOB_ID, status="done",
        result=None, error=None, merged_at="2026-08-02T19:06:00+00:00",
    )
    check("done-with-no-result rendering identical with and without merged_at",
          no_result_without_merge == no_result_with_merge)

    print(f"unmerged byte-identical      {unmerged_ok}/{unmerged_cases}")
    print(f"merged rendering             {merged_ok}/{len(merged_checks)}")
    print(f"garbage merged_at            {garbage_ok}/{len(garbage_checks)}")
    print(f"not-merged treatment         {not_merged_ok}/{len(not_merged_checks)}")
    print(f"merged degraded row          {degraded_ok}/{len(degraded_checks)}")
    print(f"merged, no artifactUrl       {no_artifact_ok}/{len(no_artifact_checks)}")
    print(f"failed/interrupted unaffected {terminal_ok}/{len(terminal_checks)}")

    if failures:
        print("\nFAILURES:")
        for f in failures:
            print(f"  {f}")
        return 1

    print("\nall cases as expected")
    return 0


if __name__ == "__main__":
    sys.exit(main())
