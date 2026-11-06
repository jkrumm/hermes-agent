"""Publish a cron job's notice to ntfy through scripts/ntfy-publish.sh.

Hermes has no ntfy platform, so a job (deliver `local`) publishes itself. The helper
clips to ntfy's body cap; the job keeps the full text in its own stdout. A failed
publish raises NtfyError so the job exits non-zero and shows as failed.
"""

import os
import subprocess

PUBLISH_BIN = os.environ.get("NTFY_PUBLISH_BIN") or os.path.expanduser("~/.hermes/scripts/ntfy-publish.sh")


class NtfyError(RuntimeError):
    pass


def publish(topic: str, title: str, text: str) -> None:
    try:
        r = subprocess.run([PUBLISH_BIN, topic, "--title", title], input=text,
                           capture_output=True, text=True, timeout=60)
    except (OSError, subprocess.SubprocessError) as e:
        raise NtfyError(f"ntfy publish to '{topic}' could not run: {e}") from e
    if r.returncode != 0:
        raise NtfyError(r.stderr.strip() or f"ntfy publish to '{topic}' exited {r.returncode}")
