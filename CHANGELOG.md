# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added

- Local webhook inspector with a browser UI and WebSocket live feed.
- Search and method filters on `GET /api/bins/{id}`, with a debounced search
  box, method picker, and empty state in the UI.
- OpenAPI 3 JSON import (`--openapi`) that matches captured requests to
  operations, pre-fills replay targets in the UI, and exposes the match at
  `GET /api/bins/{id}/{req}/openapi`.
- Signed replay presets (`--replay-presets`) with GitHub, Stripe, Slack, and
  generic HMAC signing, a UI preset picker, and `GET /api/presets`.
- MCP tools `suggest_replay` and `list_presets`, `q`/`method` filters on
  `list_requests`, and opt-in `replay_request` via
  `HOOKYARD_MCP_ALLOW_REPLAY=1`.
- MCP `export_bin` and `import_bin` tools that share the CLI archive
  validation, atomic writes, and `rename` conflict handling; both require
  `HOOKYARD_DATA_FILE`.
- `kodyaz` umbrella CLI with `hookyard`, `mcp`, and `openapi` subcommands.
- Request diffing via `GET /api/bins/{id}/diff?left=…&right=…` and a compare
  picker in the detail pane (header and unified body diffs).
- Portable, versioned bin archives: `hookyard export <bin> -o file.json` and
  `hookyard import file.json [--rename]`, with schema validation, atomic
  writes, and conflict handling.
- Opt-in retention for captured bins: `--max-bins` / `HOOKYARD_MAX_BINS` and
  `--max-age-days` / `HOOKYARD_MAX_AGE_DAYS`, with atomic pruning at startup
  and after captures.
- GitHub, Stripe, Slack, Discord, and generic HMAC-SHA256 verification.
- SSRF-safe replay with loopback/RFC1918 allow-list and metadata blocking.
- JSON file persistence, token auth for the UI and API, and Docker support.
- Read-only `hookyard mcp` server for MCP clients.
- MCP tools: `health`, `list_bins`, `list_requests`, and `get_request`.
- Optional `mcp` and `discord` extras for editable installs.

### Security

- Replay now re-validates every redirect target with the SSRF host checks before following it.
- Replay failures return a generic message instead of exposing internal exception details.

### Notes

- The MCP server is stdio-only, loopback-only, and never writes to the store.
- Sensitive headers are redacted by default; request bodies are truncated for
  agent context safety.
- No cloud service and no API keys are required.
