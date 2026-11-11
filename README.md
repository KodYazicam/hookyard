<p align="center">
  <img src="assets/banner.svg" alt="hookyard" width="100%">
</p>

<p align="center">
  <strong>Local webhook inspector.</strong><br/>
  Catch GitHub, Stripe, Slack, and Discord callbacks. Inspect, verify signatures, replay — without turning your laptop into an SSRF gadget.
</p>

<p align="center">
  <img src="https://img.shields.io/badge/python-%3E%3D3.10-3776AB?style=flat-square&logo=python&logoColor=white" alt="Python">
  <img src="https://img.shields.io/badge/FastAPI-009688?style=flat-square&logo=fastapi&logoColor=white" alt="FastAPI">
  <img src="https://img.shields.io/badge/license-Apache--2.0-2ea44f?style=flat-square" alt="License">
  <img src="https://img.shields.io/badge/author-KodYazicam-0D0D0D?style=flat-square" alt="Author">
</p>

---

ngrok shows you a tunnel. hookyard shows you the **payload**.

```bash
git clone https://github.com/KodYazicam/hookyard.git
cd hookyard
python -m venv .venv && source .venv/bin/activate
pip install -e .
hookyard --port 4242
# POST http://127.0.0.1:4242/b/demo
```

Open http://127.0.0.1:4242 — the UI lists every request, pretty-prints JSON, shows HMAC results, and can replay the same headers+body at your local API.

Catch URLs (`/b/{bin}`) stay public so vendors can POST. The UI and `/api/*` can be locked with `--token`.

## Table of contents

- [Requirements](#requirements)
- [Install](#install)
- [Quick start](#quick-start)
- [Bins and URLs](#bins-and-urls)
- [Token auth](#token-auth)
- [Expose it to the internet](#expose-it-to-the-internet)
- [Signature verification](#signature-verification)
- [Replay (SSRF-safe)](#replay-ssrf-safe)
- [OpenAPI replay targets](#openapi-replay-targets)
- [Signed replay presets](#signed-replay-presets)
- [Discord Interactions](#discord-interactions)
- [MCP server for AI agents](#mcp-server-for-ai-agents)
- [CLI](#cli)
- [kodyaz umbrella CLI](#kodyaz-umbrella-cli)
- [HTTP API](#http-api)
- [Library](#library)
- [Security](#security)
- [Troubleshooting](#troubleshooting)
- [FAQ](#faq)
- [License](#license)

## Requirements

- Python **3.10+**
- Optional: [PyNaCl](https://pypi.org/project/PyNaCl/) for Discord Ed25519 (`pip install -e ".[discord]"`)
- Optional: [MCP Python SDK](https://pypi.org/project/mcp/) for the agent server (`pip install -e ".[mcp]"`)
- Optional: Cloudflare Tunnel / ngrok if a vendor must reach your machine

## Install

Not on PyPI. Clone and install editable:

```bash
git clone https://github.com/KodYazicam/hookyard.git
cd hookyard
python -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -e ".[dev]"
pytest
hookyard --help
```

With the optional MCP server:

```bash
pip install -e ".[mcp]"
```

## Quick start

```bash
hookyard --port 4242
# persist across restarts:
hookyard --port 4242 --data-file ./hookyard.json
# lock the UI if anyone else can reach the port:
hookyard --port 4242 --token "$HOOKYARD_TOKEN"
```

Then:

1. Browser: http://127.0.0.1:4242 (add `?token=…` if you set `--token`)
2. Bin name in the header (default `demo`) → **Open bin**
3. Point a webhook at `http://127.0.0.1:4242/b/demo` (or `/b/demo/stripe`, any subpath)
4. Send a test event. It appears live (WebSocket). Click a row for headers + pretty JSON.
5. Replay to `http://127.0.0.1:3000/webhook` (localhost / RFC1918 only by default)

Bodies larger than 1 MB are rejected (`413`). Bin ids must match `[A-Za-z0-9._-]{1,64}`.

## Bins and URLs

| URL | Purpose | Auth |
| --- | --- | --- |
| `GET /` | UI | `--token` if set |
| `ANY /b/{bin}` | Catch root of a bin | **none** (vendors POST here) |
| `ANY /b/{bin}/{path}` | Catch with extra path (kept on the record) | none |
| `GET /health` | `{ "status": "ok", "name": "hookyard" }` | none |
| `/api/*` and `/ws` | Inspector API | `--token` if set |

Methods: GET, POST, PUT, PATCH, DELETE, HEAD, OPTIONS. Bodies are stored as UTF-8 (replacement on binary).

Store is **in-memory**, cap 500 requests per bin, unless you pass `--data-file`. Restarting the process clears history when you use memory.

## Token auth

```bash
hookyard --token super-secret
# UI: http://127.0.0.1:4242/?token=super-secret
# API: Authorization: Bearer super-secret
```

The catch URL stays open. That is the point of a webhook inspector. If the UI is on a LAN, **always** set a token.

## Expose it to the internet

Vendors cannot POST to `127.0.0.1`. Tunnel it:

```bash
# terminal 1
hookyard --host 127.0.0.1 --port 4242 --github-secret "$GH_SECRET" --token "$HOOKYARD_TOKEN"

# terminal 2
cloudflared tunnel --url http://127.0.0.1:4242
# or: ngrok http 4242
```

Put the public URL + `/b/demo` in the vendor dashboard. Keep `--host 127.0.0.1` so only the tunnel can reach hookyard.

`--host 0.0.0.0` binds all interfaces. hookyard **warns** on stderr. Without `--token` it warns again.

### Docker

```bash
HOOKYARD_TOKEN=pick-a-token docker compose up --build
# UI: http://127.0.0.1:4242/?token=pick-a-token
# data: named volume hookyard-data  (/data/hookyard.json)
```

Compose publishes **`127.0.0.1:4242`**, not `0.0.0.0`. The image runs as uid `10001` and has a `/health` HEALTHCHECK.

## Signature verification

Pass secrets on the CLI or via env. Each captured request gets `signatures: { github: true/false, ... }` for secrets you configured.

| Provider | Header(s) | Flag / env |
| --- | --- | --- |
| GitHub | `X-Hub-Signature-256` (`sha256=hex`) | `--github-secret` / `HOOKYARD_GITHUB_SECRET` |
| Stripe | `Stripe-Signature` (`t=…,v1=…`, multiple `v1` allowed) | `--stripe-secret` / `HOOKYARD_STRIPE_SECRET` |
| Slack | `X-Slack-Request-Timestamp` + `X-Slack-Signature` | `--slack-secret` / `HOOKYARD_SLACK_SECRET` |
| Discord | `X-Signature-Ed25519` + `X-Signature-Timestamp` | `--discord-public-key` / `HOOKYARD_DISCORD_PUBLIC_KEY` (needs `hookyard[discord]`) |
| Any HMAC-SHA256 service | configurable (default `X-Signature`), hex or base64 digest | `--hmac-secret` / `HOOKYARD_HMAC_SECRET` + `--hmac-header` |

GitHub/Stripe/Slack use HMAC compare (timing-safe, equal-length). Stripe timestamps must be within 300 seconds. Slack signs the **raw bytes**, not a UTF-8 round-trip.

The generic HMAC verifier covers every service that just signs the raw body with HMAC-SHA256 — Shopify (`--hmac-header x-shopify-hmac-sha256`, base64 digest), Contentful, Telegram-style bots, your own services. The digest is accepted as hex **or** base64 of the same MAC.

If you pass a Discord public key but PyNaCl is missing, the CLI warns at startup.

## Replay (SSRF-safe)

`POST /api/bins/{bin}/{id}/replay` `{ "target": "http://127.0.0.1:3000/hook" }`

hookyard **resolves DNS** and checks every address:

- loopback (`127.0.0.0/8`, `::1`) — always allowed
- RFC1918 (`10/8`, `172.16/12`, `192.168/16`) — allowed
- `172.32.0.0/8` is **public** and blocked (hostname prefix `172.` is not trusted)
- link-local, unspecified (`0.0.0.0`), multicast, reserved — blocked
- `169.254.169.254` and GCP metadata hostnames — blocked **even with** `--allow-remote-replay`

`--allow-remote-replay` only unlocks public unicast IPs. Hop-by-hop headers (`Host`, `Content-Length`, `Connection`, …) are stripped.

## OpenAPI replay targets

If your receiving service has an OpenAPI 3 **JSON** document, hookyard can match a captured `method` + `path` to an operation and suggest the replay URL:

```bash
hookyard --openapi ./openapi.json
# spec servers point at production? override suggestions for your local service:
hookyard --openapi ./openapi.json --openapi-base-url http://127.0.0.1:3000
```

The UI pre-fills the replay target for a matching request and shows the operation id. `GET /api/bins/{id}/{req}/openapi` returns the same data for scripts.

- OpenAPI **3.0 and 3.1, JSON only** for now; YAML is not parsed.
- Server precedence: operation → path → root document. Relative server URLs need `--openapi-base-url`.
- `{param}` placeholders use path-parameter examples, defaults, or enums and are URL-encoded. Unknown placeholders stay as `{param}` for you to fill.
- Example bodies come from `example`/`examples`, or are generated from the schema with local `$ref`s resolved.
- This only suggests a URL. Replay still runs the SSRF checks above.

## Signed replay presets

Stripe and Slack reject stale signatures, and your local secret is usually different from the vendor's. A preset file gives replay a named target plus a signing provider; hookyard recomputes the signature from the captured body with the secrets you already configured.

```json
{
  "presets": [
    {"name": "local-stripe", "target": "http://127.0.0.1:3000/webhooks/stripe", "sign": "stripe"},
    {"name": "local-github", "target": "http://127.0.0.1:3000/webhooks/github", "sign": "github"},
    {"name": "local-any", "target": "http://127.0.0.1:3000/hooks", "sign": "hmac"},
    {"name": "plain", "target": "http://127.0.0.1:3000/hooks"}
  ]
}
```

```bash
hookyard --stripe-secret "$STRIPE_WHSEC" --replay-presets ./presets.json
```

- Presets never contain secrets. Signing reuses `--github-secret`, `--stripe-secret`, `--slack-secret`, or `--hmac-secret` (`HOOKYARD_*` works too).
- The UI shows a preset picker. Selecting one fills the target and marks it signed; editing the target switches back to a custom replay.
- `POST /api/bins/{id}/{req}/replay` accepts `{ "preset": "local-stripe" }` instead of `{ "target": … }`.
- A missing secret fails before any network call. Preset targets still go through the SSRF checks above.
- `GET /api/presets` lists names, targets, and providers without secrets.
- Discord is not supported: hookyard only has the public key, so it cannot sign.

## Discord Interactions

If the JSON body has `"type": 1` (PING), hookyard answers `{ "type": 1 }` **only when**:

1. `--discord-public-key` is set, and
2. Ed25519 verifies.

Without a key, PING returns `401`. That stops a public bind from being used as a fake Interactions endpoint.

## MCP server for AI agents

`hookyard mcp` exposes a running inspector to MCP clients over stdio. It is
read-only by default: it can list bins, search requests, read one request,
suggest replay targets, and list presets. It cannot clear or create bins.
`replay_request` is only registered when you opt in with
`HOOKYARD_MCP_ALLOW_REPLAY=1`; it still goes through the inspector's SSRF and
redirect checks.

```bash
pip install -e ".[mcp]"
# terminal 1
hookyard --port 4242 --token "$HOOKYARD_TOKEN" --openapi ./openapi.json
# terminal 2 (or your MCP client)
HOOKYARD_URL=http://127.0.0.1:4242 HOOKYARD_TOKEN="$HOOKYARD_TOKEN" hookyard mcp
# add HOOKYARD_MCP_ALLOW_REPLAY=1 to enable replay_request
```

| Tool | What it does |
| --- | --- |
| `health` | Check the local inspector. |
| `list_bins` | List bins that have captured webhooks. |
| `list_requests` | List recent requests without bodies; optional `q` and `method` filters. |
| `get_request` | Read one request with headers, body, and signature results. |
| `suggest_replay` | Match the request to the loaded OpenAPI spec and suggest a target. |
| `list_presets` | List replay presets (names, targets, providers; no secrets). |
| `replay_request` | Replay to a target or preset. Only with `HOOKYARD_MCP_ALLOW_REPLAY=1`. |

Example client configuration:

```json
{
  "mcpServers": {
    "hookyard": {
      "command": "hookyard",
      "args": ["mcp"],
      "env": {
        "HOOKYARD_URL": "http://127.0.0.1:4242",
        "HOOKYARD_TOKEN": "your-token"
      }
    }
  }
}
```

For Claude Code:

```bash
claude mcp add hookyard \
  -e HOOKYARD_URL=http://127.0.0.1:4242 \
  -e HOOKYARD_TOKEN="$HOOKYARD_TOKEN" \
  -- hookyard mcp
```

MCP output is local-only and bounded. `Authorization`, `Cookie`, and API-key
headers are redacted by default; pass `include_sensitive_headers: true` to
`get_request` when you intentionally need them. Bodies are truncated to 20,000
characters by default, OpenAPI example bodies to 4,000, and replay response
bodies and headers are bounded/redacted too. Captured webhook payloads can
contain live secrets — review them before sending the output anywhere.

## CLI

```bash
hookyard --host 127.0.0.1 --port 4242 \
  --token "$HOOKYARD_TOKEN" \
  --github-secret "$GH_SECRET" \
  --stripe-secret "$STRIPE_WHSEC" \
  --slack-secret "$SLACK_SIGNING" \
  --discord-public-key "$DISCORD_PUBLIC_KEY" \
  --allow-remote-replay   # optional, still blocks metadata
```

```text
--host                  default 127.0.0.1
--port                  default 4242
--token                 protect UI + /api
--github-secret
--stripe-secret
--slack-secret
--discord-public-key
--hmac-secret           raw HMAC-SHA256 verification (hex or base64 digest)
--hmac-header           header that carries it (default x-signature; Shopify: x-shopify-hmac-sha256)
--allow-remote-replay
--data-file PATH         persist bins as JSON (or HOOKYARD_DATA_FILE)
--openapi PATH           OpenAPI 3 JSON spec for replay target suggestions (or HOOKYARD_OPENAPI)
--openapi-base-url URL   override spec servers, e.g. http://127.0.0.1:3000 (or HOOKYARD_OPENAPI_BASE_URL)
--replay-presets PATH    named replay targets + signing providers (or HOOKYARD_REPLAY_PRESETS)
--version
```

## kodyaz umbrella CLI

`kodyaz` is one entry point for the tools in this package:

```bash
kodyaz --version
kodyaz hookyard --port 4242
kodyaz mcp
kodyaz openapi ./openapi.json --operation stripeWebhook
kodyaz openapi ./openapi.json --json > operations.json
```

`kodyaz hookyard` and `kodyaz mcp` delegate to the existing commands. `kodyaz openapi` lists operations with their suggested replay target and example body; `--base-url` overrides spec servers and `--operation` filters by `operationId`. Invalid specs exit `2`; a filter with no match exits `1`.

## HTTP API

| Method | Path | Body / notes |
| --- | --- | --- |
| POST | `/api/bins` | `{ "id": "demo" }` optional; random id if omitted |
| GET | `/api/bins` | list bin ids |
| GET | `/api/presets` | replay presets (name, target, sign; no secrets) |
| GET | `/api/bins/{id}` | recent requests; optional `q`, `method`, and `limit` filters |
| GET | `/api/bins/{id}/{req}` | one request + `pretty` JSON |
| GET | `/api/bins/{id}/{req}/openapi` | matched OpenAPI operation + suggested replay target |
| DELETE | `/api/bins/{id}` | clear |
| POST | `/api/bins/{id}/{req}/replay` | `{ "target": "http://127.0.0.1:3000/x" }` or `{ "preset": "local-stripe" }` |
| WS | `/ws` | `{ "type": "request", "record": {…} }` |

`GET /api/bins/{id}` filters are applied newest-first before the limit:

- `q` — case-insensitive substring match on path, body, or headers.
- `method` — case-insensitive HTTP method; invalid method tokens return `400`.
- `limit` — `1`–`500`, default `100`.

Without query parameters the response shape is unchanged.

## Library

```python
from hookyard.signatures import verify_github, verify_stripe
from hookyard.app import create_app
from hookyard.replay import replay, host_allowed

assert verify_github(body, header, secret)
ok, reason = host_allowed("127.0.0.1", allow_remote=False)

app = create_app(secrets={"github": "..."}, allow_remote_replay=False, token="ui-secret")
```

`create_app` is a FastAPI app. Mount it behind your own process if you want.

## Security

- Default bind is loopback.
- Replay resolves IPs; metadata stays blocked.
- UI method/path are rendered with `textContent` (no HTML injection from a crafted webhook path).
- Do not commit captured payloads (`hookyard.json` is gitignored); they can contain live secrets.
- Treat `--host 0.0.0.0` without `--token` as “anyone can read my webhooks.”

Full policy: [SECURITY.md](./SECURITY.md).

## Troubleshooting

| Symptom | Fix |
| --- | --- |
| Vendor timeout | You are still on 127.0.0.1. Use a tunnel. |
| Signature invalid | Wrong secret, or body was modified (pretty-print is display-only; raw body is signed). |
| Discord endpoint fails | Install `hookyard[discord]`, pass the **public** key. PINGs without a key are 401 by design. |
| Replay rejected | Target resolved to a public or metadata IP. Point at localhost or pass `--allow-remote-replay`. |
| UI 401 | Open `/?token=…` or send `Authorization: Bearer`. |
| UI empty | Wrong bin name; click **Open bin**. WS needs same origin (and token query if set). |
| History gone | In-memory. Expected after restart unless `--data-file`. |
| `body too large` | Payload > 1 MB. |

## FAQ

**Is this webhook.site?** Same idea, local, with provider HMAC built in.

**Does it persist to disk?** Only with `--data-file` / `HOOKYARD_DATA_FILE`. Default is memory.

**HTTPS?** Terminate TLS on the tunnel / reverse proxy.

## License

Apache-2.0. See [LICENSE](./LICENSE).

Commercial use, modification, and distribution are permitted under the Apache License 2.0. Keep the license text with distributed copies.

<p align="center"><sub>Built by <a href="https://github.com/KodYazicam">KodYazicam</a></sub></p>
