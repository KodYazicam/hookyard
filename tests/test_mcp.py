from __future__ import annotations

import asyncio

import pytest

from hookyard import mcp


def test_base_url_accepts_loopback(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("HOOKYARD_URL", "http://127.0.0.1:4242")
    assert mcp._base_url() == "http://127.0.0.1:4242"
    monkeypatch.setenv("HOOKYARD_URL", "http://localhost:4242/")
    assert mcp._base_url() == "http://localhost:4242"
    monkeypatch.setenv("HOOKYARD_URL", "http://[::1]:4242")
    assert mcp._base_url() == "http://[::1]:4242"


@pytest.mark.parametrize(
    "url",
    [
        "http://example.com:4242",
        "http://10.0.0.5:4242",
        "ftp://127.0.0.1:4242",
        "http://user:pass@127.0.0.1:4242",
        "",
    ],
)
def test_base_url_rejects_non_loopback_or_credentials(
    monkeypatch: pytest.MonkeyPatch, url: str
) -> None:
    monkeypatch.setenv("HOOKYARD_URL", url)
    with pytest.raises(ValueError):
        mcp._base_url()


def test_summary_omits_body_and_headers() -> None:
    summary = mcp._summary(
        {
            "id": "abc",
            "method": "POST",
            "path": "/hook",
            "query": "",
            "headers": {"authorization": "Bearer secret"},
            "body": '{"secret":"value"}',
            "content_type": "application/json",
            "remote": "127.0.0.1",
            "created_at": 1.0,
            "size": 10,
            "signatures": {"github": True},
        }
    )
    assert summary["id"] == "abc"
    assert "body" not in summary
    assert "headers" not in summary
    assert summary["signatures"] == {"github": True}


def test_redact_headers_is_case_insensitive() -> None:
    redacted = mcp._redact_headers(
        {
            "Authorization": "Bearer secret",
            "X-API-Key": "key",
            "Content-Type": "application/json",
        }
    )
    assert redacted["Authorization"] == "[redacted]"
    assert redacted["X-API-Key"] == "[redacted]"
    assert redacted["Content-Type"] == "application/json"


def test_truncate() -> None:
    assert mcp._truncate("abcd", 10) == ("abcd", False)
    assert mcp._truncate("abcdef", 3) == ("abc", True)


def test_server_registers_read_only_tools() -> None:
    server = mcp.build_server()
    names = {tool.name for tool in asyncio.run(server.list_tools())}
    assert names == {"health", "list_bins", "list_requests", "get_request"}
