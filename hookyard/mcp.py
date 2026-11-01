"""Read-only MCP server for a running hookyard inspector.

The server talks to the local hookyard HTTP API. It never starts a second
inspector, never writes to the store, and refuses non-loopback URLs.
"""

from __future__ import annotations

import json
import os
import sys
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlsplit
from urllib.request import Request, urlopen

DEFAULT_URL = "http://127.0.0.1:4242"
LOOPBACK_HOSTS = {"127.0.0.1", "localhost", "::1"}
SENSITIVE_HEADERS = {
    "authorization",
    "proxy-authorization",
    "cookie",
    "set-cookie",
    "x-api-key",
    "x-auth-token",
}
MAX_BODY_CHARS = 200_000


def _base_url() -> str:
    raw = os.environ.get("HOOKYARD_URL", DEFAULT_URL).strip()
    if not raw:
        raise ValueError("HOOKYARD_URL is empty")
    parts = urlsplit(raw)
    if parts.scheme not in {"http", "https"}:
        raise ValueError("HOOKYARD_URL must use http:// or https://")
    if parts.username or parts.password:
        raise ValueError("HOOKYARD_URL must not contain credentials; use HOOKYARD_TOKEN")
    hostname = (parts.hostname or "").lower()
    if hostname not in LOOPBACK_HOSTS:
        raise ValueError("HOOKYARD_URL must point to loopback (127.0.0.1, localhost, or ::1)")
    return raw.rstrip("/")


def _token() -> str:
    return os.environ.get("HOOKYARD_TOKEN", "")


def _get(path: str) -> Any:
    url = f"{_base_url()}{path}"
    headers = {"Accept": "application/json"}
    token = _token()
    if token:
        headers["Authorization"] = f"Bearer {token}"
    request = Request(url, headers=headers, method="GET")
    try:
        with urlopen(request, timeout=10) as response:
            body = response.read().decode("utf-8", "replace")
    except HTTPError as error:
        detail = error.read().decode("utf-8", "replace")[:500]
        raise RuntimeError(f"hookyard API returned HTTP {error.code}: {detail}") from error
    except URLError as error:
        raise RuntimeError(
            f"cannot reach hookyard at {_base_url()} ({error.reason}). "
            "Start it with `hookyard --port 4242`."
        ) from error
    try:
        return json.loads(body)
    except json.JSONDecodeError as error:
        raise RuntimeError("hookyard API returned invalid JSON") from error


def _summary(record: dict[str, Any]) -> dict[str, Any]:
    return {
        key: record.get(key)
        for key in (
            "id",
            "method",
            "path",
            "query",
            "content_type",
            "remote",
            "created_at",
            "size",
            "signatures",
        )
    }


def _redact_headers(headers: dict[str, str]) -> dict[str, str]:
    return {
        key: ("[redacted]" if key.lower() in SENSITIVE_HEADERS else value)
        for key, value in headers.items()
    }


def _truncate(text: str, limit: int) -> tuple[str, bool]:
    if len(text) <= limit:
        return text, False
    return text[:limit], True


def health() -> dict[str, Any]:
    """Return the local hookyard health response."""
    return _get("/health")


def list_bins() -> dict[str, Any]:
    """List bins that have captured at least one webhook."""
    return _get("/api/bins")


def list_requests(bin_id: str, limit: int = 50) -> dict[str, Any]:
    """List recent captured requests in a bin without payload bodies.

    Use get_request with a request id for headers and body. The result is
    newest-first and capped at 500 records.
    """
    limit = max(1, min(int(limit), 500))
    payload = _get(f"/api/bins/{quote(bin_id, safe='')}")
    requests = payload.get("requests", [])
    if not isinstance(requests, list):
        raise RuntimeError("hookyard API returned an unexpected requests payload")
    return {
        "bin": bin_id,
        "count": len(requests),
        "returned": min(len(requests), limit),
        "requests": [_summary(record) for record in requests[:limit]],
    }


def get_request(
    bin_id: str,
    request_id: str,
    include_sensitive_headers: bool = False,
    max_body_chars: int = 20_000,
) -> dict[str, Any]:
    """Return one captured webhook, including headers, body, and signature results.

    Sensitive headers are redacted by default. Bodies are truncated to
    max_body_chars (1..200000) to keep agent context bounded.
    """
    max_body_chars = max(1, min(int(max_body_chars), MAX_BODY_CHARS))
    payload = _get(
        f"/api/bins/{quote(bin_id, safe='')}/{quote(request_id, safe='')}"
    )
    headers = payload.get("headers")
    if isinstance(headers, dict) and not include_sensitive_headers:
        payload["headers"] = _redact_headers({str(k): str(v) for k, v in headers.items()})
    for field in ("body", "pretty"):
        value = payload.get(field)
        if isinstance(value, str):
            payload[field], truncated = _truncate(value, max_body_chars)
            if truncated:
                payload[f"{field}_truncated"] = True
    return payload


def _mcp_help() -> str:
    return """
hookyard mcp — read-only MCP server for a running hookyard inspector

Usage:
  hookyard mcp

Environment:
  HOOKYARD_URL    Loopback URL of a running inspector.
                  Default: http://127.0.0.1:4242
  HOOKYARD_TOKEN  Bearer token when the inspector uses --token.

Tools:
  health          Check the inspector.
  list_bins       List bins.
  list_requests   List captured requests without bodies.
  get_request     Read one request with headers, body, and signatures.

The server is stdio-only, read-only, and refuses non-loopback URLs.
Install the optional dependency with: pip install "hookyard[mcp]"
""".strip()


def build_server():  # type: ignore[no-untyped-def]
    """Create the FastMCP server. Imported lazily so the base CLI stays small."""
    try:
        from mcp.server.mcpserver import MCPServer
    except ImportError as error:
        raise RuntimeError(
            'The MCP server needs the optional dependency: pip install "hookyard[mcp]"'
        ) from error

    from . import __version__

    server = MCPServer("hookyard", version=__version__)

    @server.tool(name="health")
    def health_tool() -> dict[str, Any]:
        """Check whether the local hookyard inspector is reachable."""
        return health()

    @server.tool(name="list_bins")
    def list_bins_tool() -> dict[str, Any]:
        """List bins that have captured webhooks."""
        return list_bins()

    @server.tool(name="list_requests")
    def list_requests_tool(bin_id: str, limit: int = 50) -> dict[str, Any]:
        """List recent captured requests in a bin without payload bodies.

        Use get_request for headers and body. Results are newest-first.
        """
        return list_requests(bin_id, limit)

    @server.tool(name="get_request")
    def get_request_tool(
        bin_id: str,
        request_id: str,
        include_sensitive_headers: bool = False,
        max_body_chars: int = 20_000,
    ) -> dict[str, Any]:
        """Read one captured webhook with headers, body, and signature results.

        Authorization, cookie, and API-key headers are redacted unless
        include_sensitive_headers is true. Bodies are truncated to keep agent
        context bounded.
        """
        return get_request(bin_id, request_id, include_sensitive_headers, max_body_chars)

    return server


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if any(arg in {"-h", "--help"} for arg in argv):
        print(_mcp_help())
        return 0
    if argv:
        print(f"hookyard mcp: unexpected argument(s): {' '.join(argv)}", file=sys.stderr)
        return 2
    try:
        _base_url()
        server = build_server()
    except (ValueError, RuntimeError) as error:
        print(f"hookyard mcp: {error}", file=sys.stderr)
        return 1
    server.run(transport="stdio")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
