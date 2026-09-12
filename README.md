<p align="center">
  <img src="assets/banner.svg" alt="hookyard" width="100%">
</p>

<p align="center">
  <strong>Local webhook inspector.</strong><br/>
  Catch GitHub, Stripe, Slack, and Discord callbacks. Inspect, verify signatures, replay.
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

## Table of contents

- [Requirements](#requirements)
- [Install](#install)
- [Quick start](#quick-start)
- [Bins and URLs](#bins-and-urls)
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
```

Then:

1. Browser: http://127.0.0.1:4242
2. Bin name in the header (default `demo`) → **Open bin**
3. Point a webhook at `http://127.0.0.1:4242/b/demo` (or `/b/demo/stripe`, any subpath)
4. Send a test event. It appears live (WebSocket). Click a row for headers + pretty JSON.
5. Replay to `http://127.0.0.1:3000/webhook` (localhost only by default)

## Bins and URLs

| URL | Purpose |
| --- | --- |
| `GET /` | UI |
| `ANY /b/{bin}` | Catch root of a bin |
| `ANY /b/{bin}/{path}` | Catch with extra path (kept on the record) |
| `GET /health` | `{ "status": "ok", "name": "hookyard" }` |

Methods: GET, POST, PUT, PATCH, DELETE, HEAD, OPTIONS. Bodies are stored as UTF-8 (replacement on binary).

Store is **in-memory**, cap 500 requests per bin. Restarting the process clears history. Fine for debugging; not an archive.

## Expose it to the internet

Vendors cannot POST to `127.0.0.1`. Tunnel it:

```bash
# terminal 1
hookyard --host 127.0.0.1 --port 4242 --github-secret "$GH_SECRET"

# terminal 2
cloudflared tunnel --url http://127.0.0.1:4242
# or: ngrok http 4242
```

Put the public URL + `/b/demo` in the vendor dashboard.

`--host 0.0.0.0` binds all interfaces. hookyard **warns** on stderr. Replay is still localhost-only unless you pass `--allow-remote-replay`.

## Signature verification

Pass secrets on the CLI or via env. Each captured request gets `signatures: { github: true/false, ... }` for secrets you configured.

| Provider | Header(s) | Flag / env |
| --- | --- | --- |
| GitHub | `X-Hub-Signature-256` (`sha256=hex`) | `--github-secret` / `HOOKYARD_GITHUB_SECRET` |
| Stripe | `Stripe-Signature` (`t=…,v1=…`, multiple `v1` allowed) | `--stripe-secret` / `HOOKYARD_STRIPE_SECRET` |
| Slack | `X-Slack-Request-Timestamp` + `X-Slack-Signature` | `--slack-secret` / `HOOKYARD_SLACK_SECRET` |
| Discord | `X-Signature-Ed25519` + `X-Signature-Timestamp` | `--discord-public-key` / `HOOKYARD_DISCORD_PUBLIC_KEY` (needs `hookyard[discord]`) |

GitHub/Stripe/Slack use HMAC compare (timing-safe). Stripe timestamps must be within 300 seconds.

## Replay (SSRF-safe)

`POST /api/bins/{bin}/{id}/replay` `{ "target": "http://127.0.0.1:3000/hook" }`

Allowed targets by default:

- `localhost`, `127.0.0.1`, `::1`
- private ranges `10.*`, `192.168.*`, `172.*`

Blocked: public hosts, `169.254.169.254`, GCP metadata hostnames.

Override with `--allow-remote-replay` (SSRF risk if the UI is exposed). Hop-by-hop headers (`Host`, `Content-Length`, `Connection`, …) are stripped.

## Discord Interactions

If the JSON body has `"type": 1` (PING), hookyard answers `{ "type": 1 }` so Discord can validate the endpoint.

When a Discord public key is configured, the PING is only ACKed if the Ed25519 signature verifies.

## CLI

```bash
hookyard --host 127.0.0.1 --port 4242 \
  --github-secret "$GH_SECRET" \
  --stripe-secret "$STRIPE_WHSEC" \
  --slack-secret "$SLACK_SIGNING" \
  --discord-public-key "$DISCORD_PUBLIC_KEY" \
  --allow-remote-replay   # optional, dangerous
```

```text
--host                  default 127.0.0.1
--port                  default 4242
--github-secret
--stripe-secret
--slack-secret
--discord-public-key
--allow-remote-replay
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
from hookyard.replay import replay

assert verify_github(body, header, secret)

app = create_app(secrets={"github": "..."}, allow_remote_replay=False)
```

`create_app` is a FastAPI app. Mount it behind your own process if you want.

## Security

- Default bind is loopback.
- Replay defaults to private hosts only.
- Do not commit captured payloads; they can contain live secrets.
- Treat `--allow-remote-replay` + `--host 0.0.0.0` as “anyone can make my machine POST anywhere.”

## Troubleshooting

| Symptom | Fix |
| --- | --- |
| Vendor timeout | You are still on 127.0.0.1. Use a tunnel. |
| Signature invalid | Wrong secret, or body was modified (pretty-print is display-only; raw body is signed). |
| Discord endpoint fails | Install `hookyard[discord]`, pass the **public** key, and allow the PING through. |
| Replay rejected | Target is public. Point at localhost or pass `--allow-remote-replay`. |
| UI empty | Wrong bin name; click **Open bin**. WS needs same origin. |
| History gone | In-memory. Expected after restart. |

## FAQ

**Is this webhook.site?** Same idea, local, with provider HMAC built in.

**Does it persist to disk?** No.

**HTTPS?** Terminate TLS on the tunnel / reverse proxy.

## License — KYAL-1.0

Free to use and modify. **Attribution is mandatory.**

```
Author : Batuhan (KodYazicam)
Project: hookyard
Source : https://github.com/KodYazicam/hookyard
```

See [LICENSE](./LICENSE).

<p align="center"><sub>Built by <a href="https://github.com/KodYazicam">KodYazicam</a></sub></p>
