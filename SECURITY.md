# Security Policy

hookyard is a **local** webhook inspector. The catch URL `/b/{bin}` is intentionally unauthenticated so vendors can POST. The UI and `/api/*` can be locked with `--token`.

## Safe defaults

- Bind: `127.0.0.1`
- Replay: loopback + RFC1918 only, after **DNS resolution**. `172.16/12` is private; `172.32/8` is not. Link-local and cloud metadata IPs stay blocked even with `--allow-remote-replay`. Every redirect target is re-validated with the same checks before it is followed.
- Discord Interactions PING (`type: 1`) is ACKed only when a Discord public key is configured **and** Ed25519 verifies.
- `hookyard mcp` is stdio-only and refuses non-loopback `HOOKYARD_URL` values. It is read-only by default and redacts `Authorization`, `Cookie`, and API-key headers. `replay_request` is registered only when `HOOKYARD_MCP_ALLOW_REPLAY=1`; it still goes through the replay SSRF checks.

## Dangerous combinations

`--host 0.0.0.0` without `--token` means anyone on the network can read captured payloads (often live HMAC secrets) and trigger replay.

Docker Compose publishes `127.0.0.1:4242` on purpose. Do not change that to `0.0.0.0` on a VPS.

## Reporting

Open a private advisory on [KodYazicam/hookyard](https://github.com/KodYazicam/hookyard/security/advisories/new).
