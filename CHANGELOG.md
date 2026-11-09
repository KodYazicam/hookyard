# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added

- Local webhook inspector with a browser UI and WebSocket live feed.
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
