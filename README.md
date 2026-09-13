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
  <img src="https://img.shields.io/badge/license-KYAL--1.0-7C3AED?style=flat-square" alt="License">
  <img src="https://img.shields.io/badge/author-KodYazicam-0D0D0D?style=flat-square" alt="Author">
</p>

---

ngrok shows you a tunnel. hookyard shows you the **payload**.

```bash
pip install hookyard
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
- [Discord Interactions](#discord-interactions)
- [CLI](#cli)
- [HTTP API](#http-api)
- [Library](#library)
- [Security](#security)
- [Troubleshooting](#troubleshooting)
- [FAQ](#faq)
- [License](#license--kyal-10)

## Requirements

- Python **3.10+**
- Optional: [PyNaCl](https://pypi.org/project/PyNaCl/) for Discord Ed25519 (`pip install hookyard[discord]`)
- Optional: Cloudflare Tunnel / ngrok if a vendor must reach your machine

## Install

```bash
pip install hookyard
# or isolated
pipx install hookyard

git clone https://github.com/KodYazicam/hookyard.git
cd hookyard
python -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -e ".[dev]"
pytest
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

GitHub/Stripe/Slack use HMAC compare (timing-safe, equal-length). Stripe timestamps must be within 300 seconds. Slack signs the **raw bytes**, not a UTF-8 round-trip.

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

## Discord Interactions

If the JSON body has `"type": 1` (PING), hookyard answers `{ "type": 1 }` **only when**:

1. `--discord-public-key` is set, and
2. Ed25519 verifies.

Without a key, PING returns `401`. That stops a public bind from being used as a fake Interactions endpoint.

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
--allow-remote-replay
--data-file PATH         persist bins as JSON (or HOOKYARD_DATA_FILE)
--version
```

## HTTP API

| Method | Path | Body / notes |
| --- | --- | --- |
| POST | `/api/bins` | `{ "id": "demo" }` optional; random id if omitted |
| GET | `/api/bins` | list bin ids |
| GET | `/api/bins/{id}` | recent requests |
| GET | `/api/bins/{id}/{req}` | one request + `pretty` JSON |
| DELETE | `/api/bins/{id}` | clear |
| POST | `/api/bins/{id}/{req}/replay` | `{ "target": "http://127.0.0.1:3000/x" }` |
| WS | `/ws` | `{ "type": "request", "record": {…} }` |

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

## License — KYAL-1.0

Free to use and modify. **Attribution is mandatory.** PyPI classifier says “Other/Proprietary” because KYAL is not on the SPDX OSI list; the text is MIT-shaped plus credit.

```
Author : Batuhan (KodYazicam)
Project: hookyard
Source : https://github.com/KodYazicam/hookyard
```

See [LICENSE](./LICENSE).

<p align="center"><sub>Built by <a href="https://github.com/KodYazicam">KodYazicam</a></sub></p>
