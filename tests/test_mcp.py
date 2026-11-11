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


def test_server_registers_read_only_tools_by_default(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("HOOKYARD_MCP_ALLOW_REPLAY", raising=False)
    server = mcp.build_server()
    names = {tool.name for tool in asyncio.run(server.list_tools())}
    assert names == {
        "health",
        "list_bins",
        "list_requests",
        "get_request",
        "suggest_replay",
        "list_presets",
    }


def test_replay_tool_is_opt_in(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("HOOKYARD_MCP_ALLOW_REPLAY", "1")
    server = mcp.build_server()
    names = {tool.name for tool in asyncio.run(server.list_tools())}
    assert "replay_request" in names
    assert names == {
        "health",
        "list_bins",
        "list_requests",
        "get_request",
        "suggest_replay",
        "list_presets",
        "replay_request",
    }


def test_list_requests_forwards_encoded_filters(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[str] = []

    def fake_get(path: str) -> dict:
        calls.append(path)
        return {"requests": []}

    monkeypatch.setattr(mcp, "_get", fake_get)
    result = mcp.list_requests("demo", limit=5, q="a b&c", method="post")
    assert calls == ["/api/bins/demo?q=a%20b%26c&method=post"]
    assert result["bin"] == "demo"
    assert result["requests"] == []


def test_suggest_replay_truncates_example_body(monkeypatch: pytest.MonkeyPatch) -> None:
    long_body = "x" * (mcp.MAX_EXAMPLE_CHARS + 10)
    monkeypatch.setattr(
        mcp,
        "_get",
        lambda path: {
            "matched": True,
            "target": "http://127.0.0.1:3000/hook",
            "operation": {"operation_id": "hook", "body": long_body},
        },
    )
    result = mcp.suggest_replay("demo", "abc")
    assert result["operation"]["body_truncated"] is True
    assert len(result["operation"]["body"]) == mcp.MAX_EXAMPLE_CHARS


def test_replay_request_is_disabled_by_default(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("HOOKYARD_MCP_ALLOW_REPLAY", raising=False)
    with pytest.raises(RuntimeError, match="disabled"):
        mcp.replay_request("demo", "abc", target="http://127.0.0.1:9/hook")


def test_replay_request_requires_exactly_one_selector(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("HOOKYARD_MCP_ALLOW_REPLAY", "yes")
    with pytest.raises(RuntimeError, match="exactly one"):
        mcp.replay_request("demo", "abc")
    with pytest.raises(RuntimeError, match="exactly one"):
        mcp.replay_request(
            "demo",
            "abc",
            target="http://127.0.0.1:9/hook",
            preset="local",
        )


def test_replay_request_truncates_and_redacts(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("HOOKYARD_MCP_ALLOW_REPLAY", "true")
    calls: list[tuple[str, dict]] = []

    def fake_post(path: str, payload: dict) -> dict:
        calls.append((path, payload))
        return {
            "ok": True,
            "status": 200,
            "headers": {
                "Set-Cookie": "session=secret",
                "Content-Type": "application/json",
            },
            "body": "y" * 30_000,
        }

    monkeypatch.setattr(mcp, "_post", fake_post)
    result = mcp.replay_request("demo", "abc", preset="local", max_body_chars=10)
    assert calls == [("/api/bins/demo/abc/replay", {"preset": "local"})]
    assert result["body"] == "y" * 10
    assert result["body_truncated"] is True
    assert result["headers"]["Set-Cookie"] == "[redacted]"
    assert result["headers"]["Content-Type"] == "application/json"


def test_replay_request_sends_target(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("HOOKYARD_MCP_ALLOW_REPLAY", "on")
    calls: list[tuple[str, dict]] = []

    def fake_post(path: str, payload: dict) -> dict:
        calls.append((path, payload))
        return {"ok": True, "status": 200, "headers": {}, "body": ""}

    monkeypatch.setattr(mcp, "_post", fake_post)
    result = mcp.replay_request(
        "demo", "abc", target="http://127.0.0.1:3000/hook"
    )
    assert calls == [
        ("/api/bins/demo/abc/replay", {"target": "http://127.0.0.1:3000/hook"})
    ]
    assert result["ok"] is True


def test_list_presets_passthrough(monkeypatch: pytest.MonkeyPatch) -> None:
    payload = {"presets": [{"name": "local", "target": "http://127.0.0.1:1", "sign": None}]}
    monkeypatch.setattr(mcp, "_get", lambda path: payload)
    assert mcp.list_presets() == payload
