# Verifying a VPS app change is actually live

_Use when verifying a change is live in a running VPS app._

Use when something *claims* a change landed in a VPS app — a queue resolution, a
deploy report, a commit message, a "the password is set now" — or when Johannes
asks whether a credential, route or config is live. **The claim is the hypothesis;
the running container is the test.** A field that exists in 1Password is not a
feature that works.

## The chain — verify every hop, in order

1. **Source** — the 1Password item field.
2. **Rendered env** — `~/vps/apps/<app>/.env` on the VPS, materialized from the
   repo's `.env.tpl` (the deploy artifact, not the source of truth).
3. **Container env** — the running container's `Config.Env`.
4. **The door** — the app's own HTTP surface, exercised with the credential.

Hops 1–3 compare **by hash**; hop 4 is the only one that proves the feature works.

```bash
# 1+2 — hash the item field against the rendered env
ssh vps 'cd ~/vps/apps/<app>; python3 - <<"PY"
import json,subprocess,hashlib
h=lambda s: hashlib.sha256(s.encode()).hexdigest()[:12]
out=subprocess.run(["op","item","get","<item>","--vault","<vault>","--format","json"],capture_output=True,text=True).stdout
d=json.loads(out)
opv={f.get("label"):f.get("value") for f in d.get("fields",[])}.get("<FIELD>") or ""
envv=next((l.split("=",1)[1].rstrip("\n") for l in open(".env") if l.startswith("<ENVVAR>=")),"")
print("op",len(opv),h(opv),"env",len(envv),h(envv),"MATCH" if opv and opv==envv else "MISMATCH")
PY'

# 3 — resolve the live container name first, then read its env
ssh vps 'N=$(docker ps --format "{{.Names}}" | grep -i <app> | head -1); echo "$N"; \
  docker inspect "$N" --format "{{range .Config.Env}}{{println .}}{{end}}" | grep "^<ENVVAR>="'

# 4 — exercise the door from inside the app's own container
ssh vps 'docker exec <container> curl -sS -o /dev/null -w "no-auth=%{http_code}\n" http://127.0.0.1:<port>/<route>'
```

Hop 4 reads as a **pair**: `401` (or a redirect to auth) without the credential and
`200`/`302` with it is the proof the gate is on and the value is live. A bare `200`
without the credential means the gate is off, not that the check passed.

## Pitfalls

- **Hash a 1Password field from `--format json`, never from `--fields label=…`.**
  The `--fields` form returns label-and-value text, so a 32-char password hashes as
  65 chars and every cross-hop comparison comes back a false `MISMATCH`. Parse
  `fields[].value` by label. Print only hashes and lengths — never the value.
- **A RollHook-managed app has no stable `container_name`** — that constraint is
  what lets a rollout scale to two instances — so the live name is
  `<app>-<app>-<n>` and `docker inspect <app>` returns *nothing at all*. Resolve it
  with `docker ps --format '{{.Names}}' | grep -i <app>`; an empty `docker inspect`
  is a name-resolution miss, not a missing container.
- **Traefik publishes no host ports** (cloudflared reaches it over the docker
  network), so a host-side `curl 127.0.0.1:80`/`:443` is a connection refusal and
  says nothing about the app. Probe from inside the container, where the port and
  the env are the real ones.
- **Never re-run an `op item edit` "to be sure".** It is an upsert: a second run
  silently rotates a live value, and the container keeps the old one until its env
  is re-rendered. Read the item read-only first.
- **A rotated value needs a re-render and a recreate.** Editing the item or even
  the `.env` changes nothing until `make <app>-env` runs and the container is
  recreated — so hop 3 (container env), not hop 2, is where a stale value shows up.
- **Run `op` on the VPS, not on the mini.** The VPS holds a service-account token
  and answers headlessly; the mini's `op` blocks on a biometric prompt that nobody
  is there to answer.
- **Report what the door returned, not what the queue entry said.** A `done`
  resolution with `exit: 0` is a claim by whoever wrote it; the status codes are
  the evidence, and when the work was done out of band, say that instead of taking
  credit for it.
