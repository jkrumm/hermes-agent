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
    ticket_code = 501  # the ws-ticket mint answer; 401 is the healthy, gated one
    push_fail = 0  # the next N pushes answer 502 (a Cloudflare blip), then succeed

    def do_GET(self):
        if self.path.startswith("/api/status"):
            self._send(json.dumps(self.status_body).encode())
            return
        PUSHES.append(urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query))
        if Handler.push_fail > 0:
            Handler.push_fail -= 1
            self.send_error(502)
            return
        self._send(b'{"ok":true}')

    def do_POST(self):
        self.send_error(Handler.ticket_code)

    def _send(self, body):
        self.send_response(200)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *a):
        pass


def make_home(base_url, state="{}", export_ok=False, read_fails=0):
    home = tempfile.mkdtemp(prefix="hermes-liveness-test-")
    os.makedirs(f"{home}/.local/bin")
    os.makedirs(f"{home}/.hermes")
    open(f"{home}/.hermes/gateway_state.json", "w").write(state)
    open(f"{home}/.hermes/.env.tpl", "w").write("A=op://x/y/z\n")
    stub = f"{home}/.local/bin/secrets-run"
    # `read` resolves the push URL (with Kuma's usual query); `export` HANGS — the fake hung probe —
    # unless export_ok, where it renders the one ref the template asks for.
    export = 'echo "export A=1"; exit 0' if export_ok else "sleep 60"
    # read_fails: the first N `read` calls fail (a transient cache miss); 99 = always.
    flaky = (
        f'if [[ "$1" == read ]]; then n=$(cat "{home}/reads" 2>/dev/null || echo 0); echo $((n+1)) > "{home}/reads"; '
        f'(( n < {read_fails} )) && {{ echo "sops: boom" >&2; exit 1; }}; fi\n'
    )
    open(stub, "w").write(
        "#!/bin/bash\n"
        + flaky
        + f'[[ "$1" == read ]] && {{ echo "{base_url}/api/push/tok?status=up&msg=OK&ping="; exit 0; }}\n'
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

    # 1c. A running gateway whose API server platform is not connected withholds the ping and says so.
    home = make_home(base, state='{"gateway_state":"running","pid":1,"platforms":{"api_server":{"state":"retrying"}}}', export_ok=True)
    PUSHES.clear()
    r, dt = run("hermes-liveness.sh", home, {"HERMES_LIVENESS_PROBE_TIMEOUT": "5"}, 40)
    q = PUSHES[0] if PUSHES else {}
    check("liveness: api_server not connected is named", q.get("status") == ["down"] and "api_server=retrying" in (q.get("msg") or [""])[0], str(q))

    # 1d. One transient push-URL read failure is retried: the tick goes on (draining is the next guard it reaches).
    home = make_home(base, state='{"gateway_state":"draining"}', export_ok=True, read_fails=1)
    PUSHES.clear()
    r, dt = run("hermes-liveness.sh", home, {"HERMES_LIVENESS_PROBE_TIMEOUT": "5"}, 40)
    check("liveness: one failed URL read is retried", "gateway_state=draining" in r.stdout and "did not resolve" not in r.stdout, r.stdout)

    # 1e. A URL that never resolves is logged with the read's stderr and pushes nothing.
    home = make_home(base, export_ok=True, read_fails=99)
    PUSHES.clear()
    r, dt = run("hermes-liveness.sh", home, {"HERMES_LIVENESS_PROBE_TIMEOUT": "5"}, 40)
    check("liveness: unresolvable URL is logged with the reason", "did not resolve" in r.stdout and "sops: boom" in r.stdout, r.stdout)
    check("liveness: unresolvable URL pushes nothing", not PUSHES, str(PUSHES))

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

    # 4. healthy serve; the success push fails twice (502) then lands → retried, run succeeds.
    Handler.ticket_code = 401
    Handler.push_fail = 2
    home = make_home(base)
    PUSHES.clear()
    r, dt = run("hermes-serve-liveness.sh", home, {"HERMES_SERVE_BASE": base}, 60)
    check("serve: a transient push failure is retried to success", r.returncode == 0 and len(PUSHES) == 3, f"rc={r.returncode} pushes={len(PUSHES)} {r.stdout}")
    check("serve: each failed attempt is logged", "attempt 2/3 failed" in r.stdout, r.stdout)

    # 5. all three pushes fail → the job fails with curl's rc, not a silent 0.
    Handler.push_fail = 99
    home = make_home(base)
    PUSHES.clear()
    r, dt = run("hermes-serve-liveness.sh", home, {"HERMES_SERVE_BASE": base}, 60)
    check("serve: three failed pushes fail the run", r.returncode != 0 and len(PUSHES) == 3, f"rc={r.returncode} pushes={len(PUSHES)}")
    Handler.push_fail = 0

    srv.shutdown()
    if fails:
        print(f"{len(fails)} failed")
        sys.exit(1)
    print("all passed")


if __name__ == "__main__":
    main()
