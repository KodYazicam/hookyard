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

Point Stripe / GitHub / any SaaS webhook URL at a bin. The UI lists every request, pretty-prints JSON, verifies HMAC signatures, and replays the same headers+body at your local API.

## Features

- Zero-config FastAPI server + live UI (WebSocket)
- Catch-all bins: `POST /b/{bin}/any/path`
- Signature checks: GitHub SHA-256, Stripe `t,v1` (multiple `v1` signatures), Slack `v0=`, Discord Ed25519 (`pip install hookyard[discord]`)
- Replay to localhost/private hosts only (opt in to remote with `--allow-remote-replay`)
- Discord PING (`type: 1`) auto-ack so the Interactions endpoint validates
- In-memory store (no database)

## CLI

```bash
hookyard --host 127.0.0.1 --port 4242 \
  --github-secret $GH_SECRET \
  --stripe-secret $STRIPE_WHSEC \
  --slack-secret $SLACK_SIGNING \
  --discord-public-key $DISCORD_PUBLIC_KEY
```

Environment aliases: `HOOKYARD_GITHUB_SECRET`, `HOOKYARD_STRIPE_SECRET`, `HOOKYARD_SLACK_SECRET`, `HOOKYARD_DISCORD_PUBLIC_KEY`.

## Library

```python
from hookyard.signatures import verify_github, verify_stripe

assert verify_github(body, header, secret)
```

```python
from hookyard.app import create_app
app = create_app(secrets={"github": "..."})
```

## Why this and not webhook.site

webhook.site is hosted. hookyard runs on your machine, keeps payloads off the internet, and knows provider signatures. Pair it with Cloudflare Tunnel / ngrok when a vendor must reach you.

## License — KYAL-1.0

Free to use and modify. **Attribution is mandatory.**

```
Author : Batuhan (KodYazicam)
Project: hookyard
Source : https://github.com/KodYazicam/hookyard
```

See [LICENSE](./LICENSE).

<p align="center"><sub>Built by <a href="https://github.com/KodYazicam">KodYazicam</a></sub></p>
