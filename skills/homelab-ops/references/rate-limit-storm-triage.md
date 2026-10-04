# 429 storm — self-inflicted or upstream?

_Use when an app storms 429s: self-inflicted or upstream?_

A rate-limit storm reaches you as a **count of log lines**, and that count is the
least reliable number in the case: SDKs retry internally, containers are recreated,
and one logical attempt can write several lines. The disposition — fix our retry
path, fix the upstream route, or wait it out — turns on two facts a grep cannot
give you: **how many requests we actually made**, and **what the upstream said when
it refused**. Get both, then answer.

## Procedure

### 1. Read our own retry path first — it bounds the ceiling

- Find which code path talks to *that* upstream:
  `grep -rn "createGateway\|maxRetries\|baseURL\|fetch(" src/`. A 429 in the logs
  belongs to one client path; don't attribute it to the whole app or to the
  request handler.
- Find the concurrency guard and the drain loop. A single-flight pattern
  (`let running = false; let rerun = false`, claim one row, await, repeat) caps
  in-flight calls at 1 — the peak rate is then 1/latency per pass, and a storm
  from that path is arithmetically impossible.
- Find the backoff ladder and the attempt cap (a fixed array plus
  `MAX_ATTEMPTS`). **One row can produce at most `len(ladder)+1` requests ever** —
  multiply by row count for a hard upper bound on failing requests.
- Note whether the ladder has jitter. A fixed ladder makes every due row retry in
  lockstep, so passes bunch into a few minutes — name it, but it is not what made
  the upstream say no.

### 2. Reconstruct real request volume from the app's durable state

A queue table carrying `attempts` / `next_attempt_at` is a better record than any
log. Read a **copy**, never the live file:

```bash
ssh vps 'tar czf /tmp/db.tgz -C /var/lib/<app> <db> <db>-wal <db>-shm'   # -wal/-shm too, or WAL rows are invisible
scp vps:/tmp/db.tgz ~/.hermes/cache/scratch/ && tar xzf ~/.hermes/cache/scratch/db.tgz -C ~/.hermes/cache/scratch/
# then: sqlite3.connect("file:<db>?mode=ro", uri=True)  — read-only, no writes to prod
```

- Group by `status, attempts`: the top attempt count tells you which rung is next,
  and `next_attempt_at` **minus** the cumulative ladder offset back-computes when
  the first attempt ran.
- Rows written in one pass have `next_attempt_at` values spaced by the failure
  latency — that spacing proves sequential single-flight processing and gives you
  the duration of a pass.
- An `error` column holds only the **last** error per row: a different message there
  means the upstream's refusal changed over time, not that the earlier ones differed.
- Rows with a NULL / not-applicable status are usually that by design (outbound mail,
  never-enqueued rows). Read the schema comment before calling it a bug.

### 3. Reconcile the quoted log count

- **A log-line count is not a request count.** The Vercel AI SDK defaults to
  `maxRetries = 2` — up to 3 HTTP requests, and up to 3 lines, per logical attempt.
  When `lines / failing attempts` lands near 2–3, that is the SDK, not a client loop.
- **Container logs die with the container.** A RollHook deploy recreates it, so a
  count quoted as "the last 24h" from before the deploy is already unverifiable.
  Say which number you verified (the queue counters) and which you could not.

### 4. Probe the upstream once, with the app's own credential, from inside the app

Run the probe **in the container** so the secret never leaves it — never print,
`echo`, or paste the key:

```bash
ssh vps 'bash -s' <<'EOF'
cat > /tmp/probe.ts <<'TS'
const key = process.env[process.env.PROBE_KEY_VAR!];   // set PROBE_KEY_VAR=<the app's env var>
const BASE = "https://ai-gateway.vercel.sh";          // provider / gateway base
async function get(p: string) {
  try {
    const r = await fetch(BASE + p, { headers: { Authorization: "Bearer " + key } });
    console.log("GET", p, "->", r.status, (await r.text()).slice(0, 500));
  } catch (e) { console.log("GET", p, "ERR", (e as Error).message); }
}
await get("/v1/credits");   // plan / balance first: is the credential entitled at all?
await get("/v1/models");
const mod: any = await import("/app/src/llm/<helper>.ts");   // the app's OWN call path
const t0 = Date.now();
try {
  console.log("CALL OK", Date.now() - t0, JSON.stringify(await mod.<fn>(/* app's arg shape */)).slice(0, 300));
} catch (e: any) {
  console.log("CALL ERR", Date.now() - t0, "|", e?.constructor?.name, "| status", e?.statusCode, "| msg", e?.message, "| body", String(e?.responseBody ?? e?.data ?? "").slice(0, 700));
}
TS
docker cp /tmp/probe.ts <container>:/tmp/probe.ts && docker exec <container> bun /tmp/probe.ts
EOF
```

One call, never a loop; print status and body only. Read the answer:

- **403 / "no access to this model" / "free tier" / "upgrade to paid credits"** →
  entitlement. Permanent; no client-side change fixes it.
- **429 with provider attempts > 0** → genuine upstream saturation: different
  route/provider, or wait it out.
- A refusal answered in ~1 s **before any provider attempt** ("zero provider
  attempts") never reached a provider — the gateway itself refused it.
- The same refusal surfaces as different error classes on different calls
  (`GatewayRateLimitError: … high demand` stored in the app, a 403 entitlement on a
  live probe). Treat them as one refusal and say so in one clause.

### 5. Decide, and name the cheapest correct fix

- **Our side**: client-side rate limit, jitter, a cap on concurrent calls, and park
  on a non-retryable status instead of counting a retry — retrying a 403 to terminal
  wastes the queue *and* looks like a storm in the logs.
- **Their side**: plan/credits, or a different route/provider for the same model.
- **Wait it out** only when the probe shows real provider saturation.
- **Check whether the failing feature is load-bearing before proposing code.** A
  shadow judge / non-authoritative classifier is usually switched off with an env
  unset (look for the code's own disabled path — a worker returning early when its
  key is missing): a zero-code mitigation with no change to user-visible behaviour.
  Say that before proposing a refactor.
- Finish the timeline: rows sitting on the last rung go terminal at a computable
  time. Name that time and what is lost when they do.

## Pitfalls

- **Do not restart or kill the worker to "unblock" the queue.** The queue is the
  evidence; a restart destroys the timeline and fixes nothing upstream.
- **A success after N retries is still evidence.** Rows that eventually completed
  after 3–7 attempts date the refusal: if they succeed up to a point and then all
  fail, the change is at the upstream, not in our code.
- **Never quote a key's value, length, or prefix** — probe with the container's own
  env and report only status codes and provider messages.
- **The storm's shape includes the deadline.** Rows already at max-1 attempts go
  terminal on their next rung whether or not the question is settled; report that
  before the recommendation, so the answer does not read as academic.
