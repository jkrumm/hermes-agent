# Cloudflare DNS — jkrumm.com

Quick reference for verifying and fixing DNS records for `jkrumm.com` and its
subdomains. Reach for this when a Mac Mini push-monitor alert carries a
dev-vhost DNS failure, or `mini.jkrumm.com`/another subdomain looks
unresolvable.

## Credentials (1Password)

| What | 1Password ref |
|-|-|
| DNS API token | `op://common/cloudflare/DNS_API_TOKEN` |
| Zone ID (jkrumm.com) | `op://common/cloudflare/ZONE_ID_JKRUMM_COM` |
| Account ID | `op://common/cloudflare/ACCOUNT_ID` |

Resolve on the machine that has `op` access — never echo the token value.

## DNS resolution checks

Always test from multiple sources to distinguish "record is wrong" from
"local resolver is glitchy":

```bash
# Local system resolver
dig +short mini.jkrumm.com A

# Public resolvers
dig @8.8.8.8 +short mini.jkrumm.com A     # Google
dig @1.1.1.1 +short mini.jkrumm.com A     # Cloudflare

# Tailscale's own MagicDNS resolver (see `tailscale status` for its address)
```

If public DNS resolves correctly but the local/tailnet resolver doesn't →
transient local resolver issue, not a record problem. If **no** resolver
returns anything → check the Cloudflare record itself.

## Cloudflare API quick ops

```bash
# List A records for jkrumm.com
curl -s "https://api.cloudflare.com/client/v4/zones/<ZONE_ID>/dns_records?type=A" \
  -H "Authorization: Bearer <TOKEN>" \
  | python3 -c "import json,sys; r=json.load(sys.stdin); [print(f'{rec[\"name\"]} -> {rec[\"content\"]}') for rec in r['result']]"

# Create/update an A record (unproxied — required for a tailnet address)
curl -s -X POST "https://api.cloudflare.com/client/v4/zones/<ZONE_ID>/dns_records" \
  -H "Authorization: Bearer <TOKEN>" \
  -H "Content-Type: application/json" \
  -d '{"type":"A","name":"<subdomain>","content":"<tailnet-ip>","ttl":1,"proxied":false}'
```

## Known records (shape, not values)

| Name | Type | Content | Proxied | Purpose |
|-|-|-|-|-|
| `mini.jkrumm.com` | A | Mac Mini tailnet IP | No | Dev host vhosts |
| `*.mini.jkrumm.com` | A | Mac Mini tailnet IP | No | Wildcard for dev vhosts |
| `argo.jkrumm.com` | A | VPS tailnet IP | No | Argo API |
| `audio-gateway.jkrumm.com` | A | VPS tailnet IP | No | TTS/STT gateway |

Tailnet IPs change only on machine reinstall — a record should always match
that machine's current `tailscale ip -4` output. Look the live values up with
`tailscale status` rather than trusting a cached number in a doc.

## Pitfalls

- **Never proxy a tailnet-IP record** — `proxied: false` is required.
  Cloudflare's edge cannot reach a CGNAT (`100.x.y.z`) address.
- **The DNS API token** has Zone:Read + DNS:Edit scope — broad enough to
  break other records too. Prefer the read-only checks above for triage;
  only mutate when a record is confirmed wrong.
- **A dev-vhost DNS FAIL in a push-monitor alert is usually not a record
  problem.** The record is almost always correct; it's the resolving host's
  own resolver having a transient hiccup. Confirm against a public resolver
  before touching Cloudflare.
