#!/usr/bin/env python3
"""The two Kuma pushers stay bounded: a hung probe fails its own check and the push still goes out.

Why: launchd never starts a second instance of a running job, so one hung call in a pusher
silences its monitor indefinitely (dotfiles devhost-health, 2026-11-06, ~28 h). The pushers
bound every external call; a failed check pushes `status=down&msg=<reason>`.

Runs the real scripts under a fake HOME with a stub `secrets-run` and a local push server:

    ~/.hermes/hermes-agent/venv/bin/python3 tests/test_liveness_bounded.py
"""

import http.server
import json
import os
import subprocess
import sys
import tempfile
import threading
import time
import urllib.parse

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PUSHES = []


class Handler(http.server.BaseHTTPRequestHandler):
    status_body = {"auth_required": False}

    def do_GET(self):
        if self.path.startswith("/api/status"):
            self._send(json.dumps(self.status_body).encode())
            return
        PUSHES.append(urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query))
        self._send(b'{"ok":true}')

    def _send(self, body):
        self.send_response(200)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *a):
        pass


def make_home(base_url, state="{}", export_ok=False):
    home = tempfile.mkdtemp(prefix="hermes-liveness-test-")
    os.makedirs(f"{home}/.local/bin")
    os.makedirs(f"{home}/.hermes")
    open(f"{home}/.hermes/gateway_state.json", "w").write(state)
    open(f"{home}/.hermes/.env.tpl", "w").write("A=op://x/y/z\n")
    stub = f"{home}/.local/bin/secrets-run"
    # `read` resolves the push URL (with Kuma's usual query); `export` HANGS — the fake hung probe —
    # unless export_ok, where it renders the one ref the template asks for.
    export = 'echo "export A=1"; exit 0' if export_ok else "sleep 60"
    open(stub, "w").write(
        "#!/bin/bash\n"
        f'[[ "$1" == read ]] && {{ echo "{base_url}/api/push/tok?status=up&msg=OK&ping="; exit 0; }}\n'
        f"{export}\n"
    )
    os.chmod(stub, 0o755)
    return home


def run(script, home, extra_env, limit):
    env = {**os.environ, "HOME": home, **extra_env}
    t0 = time.time()
    r = subprocess.run(["/bin/zsh", f"{REPO}/scripts/{script}"], env=env, capture_output=True, text=True, timeout=limit)
    return r, time.time() - t0


def main():
    srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{srv.server_address[1]}"
    fails = []

    def check(name, ok, detail=""):
        print(("  ok   " if ok else "  FAIL ") + name + (f" — {detail}" if detail and not ok else ""))
        if not ok:
            fails.append(name)

    # 1. hermes-liveness: the secret render hangs → bounded by the probe timeout, push names it.
    home = make_home(base)
    PUSHES.clear()
    r, dt = run("hermes-liveness.sh", home, {"HERMES_LIVENESS_PROBE_TIMEOUT": "1"}, 40)
    check("liveness: returns within the bound despite a hung probe", r.returncode == 0 and dt < 15, f"rc={r.returncode} {dt:.1f}s")
    check("liveness: pushes exactly once", len(PUSHES) == 1, str(PUSHES))
    q = PUSHES[0] if PUSHES else {}
    check("liveness: push is down", q.get("status") == ["down"], str(q))
    check("liveness: push names the failed check", "secret cache" in (q.get("msg") or [""])[0], str(q))
    check("liveness: skip is logged", "heartbeat skipped" in r.stdout, r.stdout)

    # 1b. A planned restart (gateway_state=draining) withholds the ping but never pages Kuma.
    home = make_home(base, state='{"gateway_state":"draining"}', export_ok=True)
    PUSHES.clear()
    r, dt = run("hermes-liveness.sh", home, {"HERMES_LIVENESS_PROBE_TIMEOUT": "5"}, 40)
    check("liveness: draining exits 0", r.returncode == 0, f"rc={r.returncode}")
    check("liveness: draining pushes nothing", not PUSHES, str(PUSHES))
    check("liveness: draining is logged", "gateway_state=draining" in r.stdout, r.stdout)

    # 2. hermes-serve-liveness: an ungated serve → down push naming it (ungated is the check it exists for).
    home = make_home(base)
    PUSHES.clear()
    r, dt = run("hermes-serve-liveness.sh", home, {"HERMES_SERVE_BASE": base}, 40)
    q = PUSHES[0] if PUSHES else {}
    check("serve: down push naming the failed check", q.get("status") == ["down"] and "UNGATED" in (q.get("msg") or [""])[0], str(q))
    check("serve: pushes exactly once", len(PUSHES) == 1, str(PUSHES))

    # 3. gated serve, but the ws-ticket mint is not refused (the stub answers 200, not 401) → named down push.
    Handler.status_body = {"auth_required": True}
    home = make_home(base)
    PUSHES.clear()
    r, dt = run("hermes-serve-liveness.sh", home, {"HERMES_SERVE_BASE": base}, 40)
    q = PUSHES[0] if PUSHES else {}
    check("serve: ws-ticket not refused is named", q.get("status") == ["down"] and "ws-ticket" in (q.get("msg") or [""])[0], str(q))

    srv.shutdown()
    if fails:
        print(f"{len(fails)} failed")
        sys.exit(1)
    print("all passed")


if __name__ == "__main__":
    main()
