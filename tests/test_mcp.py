from __future__ import annotations

import asyncio
import json

import pytest

from hookyard import archive, mcp
from hookyard.persist import JsonFileStore
from hookyard.store import new_record


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


def test_server_registers_default_tools(
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
        "export_bin",
        "import_bin",
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
        "export_bin",
        "import_bin",
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


def _seed_store(path) -> JsonFileStore:
    store = JsonFileStore(path)
    store.create_bin("demo")
    store.add(
        new_record(
            "demo",
            "POST",
            "/hook",
            "a=1",
            {"content-type": "application/json", "x-test": "1"},
            '{"ok":true}',
            "127.0.0.1",
            {"github": True},
        )
    )
    return store


def test_archive_tools_are_registered_with_a_clear_schema(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("HOOKYARD_MCP_ALLOW_REPLAY", raising=False)
    server = mcp.build_server()
    tools = {tool.name: tool for tool in asyncio.run(server.list_tools())}

    assert {"export_bin", "import_bin"} <= set(tools)
    export_schema = tools["export_bin"].input_schema
    assert export_schema["type"] == "object"
    assert set(export_schema["properties"]) == {"bin_id", "output"}
    assert set(export_schema["required"]) == {"bin_id", "output"}
    assert "HOOKYARD_DATA_FILE" in tools["export_bin"].description

    import_schema = tools["import_bin"].input_schema
    assert import_schema["type"] == "object"
    assert set(import_schema["properties"]) == {"archive_path", "rename"}
    assert set(import_schema["required"]) == {"archive_path"}
    assert import_schema["properties"]["rename"]["default"] is False
    assert "rename" in tools["import_bin"].description.lower()


def test_mcp_export_and_import_round_trip(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = tmp_path / "source.json"
    _seed_store(source)
    monkeypatch.setenv("HOOKYARD_DATA_FILE", str(source))

    archive_path = tmp_path / "demo.json"
    exported = mcp.export_bin("demo", str(archive_path))
    assert exported["bin"] == "demo"
    assert exported["requests"] == 1
    assert exported["version"] == archive.ARCHIVE_VERSION
    assert archive_path.exists()

    payload = json.loads(archive_path.read_text(encoding="utf-8"))
    assert payload["version"] == archive.ARCHIVE_VERSION
    assert payload["bin"] == "demo"

    target = tmp_path / "target.json"
    imported = mcp.import_bin(str(archive_path), data_file=str(target))
    assert imported["bin"] == "demo"
    assert imported["archive_bin"] == "demo"
    assert imported["renamed"] is False
    assert imported["requests"] == 1

    rows = JsonFileStore(target).list("demo")
    assert [(row.method, row.path, row.query, row.body) for row in rows] == [
        ("POST", "/hook", "a=1", '{"ok":true}')
    ]
    assert rows[0].signatures == {"github": True}


def test_mcp_import_conflict_refuses_then_renames(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    target = tmp_path / "target.json"
    _seed_store(target)
    archive_path = tmp_path / "demo.json"
    archive.write_archive(
        archive_path,
        "demo",
        [
            new_record(
                "demo",
                "PUT",
                "/imported",
                "",
                {"content-type": "application/json"},
                '{"imported":true}',
                "127.0.0.1",
            )
        ],
    )
    monkeypatch.setenv("HOOKYARD_DATA_FILE", str(target))

    with pytest.raises(RuntimeError, match="already exists"):
        mcp.import_bin(str(archive_path))
    assert JsonFileStore(target).bins() == ["demo"]

    imported = mcp.import_bin(str(archive_path), rename=True)
    assert imported["bin"] == "demo-2"
    assert imported["archive_bin"] == "demo"
    assert imported["renamed"] is True

    store = JsonFileStore(target)
    assert store.bins() == ["demo", "demo-2"]
    assert [row.path for row in store.list("demo")] == ["/hook"]
    assert [row.path for row in store.list("demo-2")] == ["/imported"]


def test_mcp_import_rejects_corrupt_archive_without_writing(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    target = tmp_path / "target.json"
    _seed_store(target)
    before = target.read_bytes()
    bad = tmp_path / "bad.json"
    bad.write_text("not json", encoding="utf-8")
    monkeypatch.setenv("HOOKYARD_DATA_FILE", str(target))

    with pytest.raises(RuntimeError, match="not valid JSON"):
        mcp.import_bin(str(bad))
    assert target.read_bytes() == before

    new_target = tmp_path / "nested" / "new.json"
    with pytest.raises(RuntimeError, match="not valid JSON"):
        mcp.import_bin(str(bad), data_file=str(new_target))
    assert not new_target.exists()
    assert not new_target.parent.exists()


def test_mcp_import_rejects_unsupported_archive_version(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    target = tmp_path / "target.json"
    _seed_store(target)
    before = target.read_bytes()
    bad = tmp_path / "bad.json"
    bad.write_text(
        json.dumps({"version": 99, "bin": "demo", "requests": []}),
        encoding="utf-8",
    )
    monkeypatch.setenv("HOOKYARD_DATA_FILE", str(target))

    with pytest.raises(RuntimeError, match="unsupported archive version"):
        mcp.import_bin(str(bad))
    assert target.read_bytes() == before


def test_mcp_export_unknown_bin_leaves_no_file(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = tmp_path / "source.json"
    _seed_store(source)
    monkeypatch.setenv("HOOKYARD_DATA_FILE", str(source))
    output = tmp_path / "missing.json"

    with pytest.raises(RuntimeError, match="not found"):
        mcp.export_bin("missing", str(output))
    assert not output.exists()


def test_mcp_export_reports_unwritable_output(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = tmp_path / "source.json"
    _seed_store(source)
    monkeypatch.setenv("HOOKYARD_DATA_FILE", str(source))
    output = tmp_path / "missing-dir" / "demo.json"

    with pytest.raises(RuntimeError, match="cannot write archive"):
        mcp.export_bin("demo", str(output))
    assert not output.exists()


def test_mcp_archive_tools_require_data_file(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("HOOKYARD_DATA_FILE", raising=False)

    with pytest.raises(RuntimeError, match="HOOKYARD_DATA_FILE"):
        mcp.export_bin("demo", str(tmp_path / "demo.json"))
    with pytest.raises(RuntimeError, match="HOOKYARD_DATA_FILE"):
        mcp.import_bin(str(tmp_path / "demo.json"))
