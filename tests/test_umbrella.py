from __future__ import annotations

import json
import tomllib
from pathlib import Path

import pytest

from hookyard import __version__, umbrella


def _spec() -> dict:
    return {
        "openapi": "3.1.0",
        "info": {"title": "Local", "version": "1"},
        "servers": [{"url": "http://127.0.0.1:3000"}],
        "paths": {
            "/hooks/stripe": {
                "post": {
                    "operationId": "stripeWebhook",
                    "summary": "Stripe events",
                    "requestBody": {
                        "content": {
                            "application/json": {"example": {"event": "payment"}}
                        }
                    },
                }
            },
            "/health": {"get": {"operationId": "health"}},
        },
    }


def _write_spec(tmp_path) -> Path:
    path = tmp_path / "openapi.json"
    path.write_text(json.dumps(_spec()), encoding="utf-8")
    return path


def test_version_and_help(capsys: pytest.CaptureFixture[str]) -> None:
    assert umbrella.main(["--version"]) == 0
    assert capsys.readouterr().out.strip() == f"kodyaz {__version__}"

    assert umbrella.main([]) == 0
    help_text = capsys.readouterr().out
    assert "hookyard" in help_text
    assert "openapi" in help_text


def test_unknown_command(capsys: pytest.CaptureFixture[str]) -> None:
    assert umbrella.main(["nope"]) == 2
    assert "unknown command" in capsys.readouterr().err


def test_delegates_hookyard_and_mcp(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[list[str]] = []

    def fake_hookyard(argv: list[str] | None = None) -> int:
        calls.append(list(argv or []))
        return 7

    def fake_mcp(argv: list[str] | None = None) -> int:
        calls.append(list(argv or []))
        return 8

    monkeypatch.setattr("hookyard.cli.main", fake_hookyard)
    monkeypatch.setattr("hookyard.mcp.main", fake_mcp)

    assert umbrella.main(["hookyard", "--version"]) == 7
    assert umbrella.main(["mcp", "--help"]) == 8
    assert calls == [["--version"], ["--help"]]


def test_openapi_json_output(
    tmp_path, capsys: pytest.CaptureFixture[str]
) -> None:
    path = _write_spec(tmp_path)
    assert umbrella.main(["openapi", str(path), "--json"]) == 0
    rows = json.loads(capsys.readouterr().out)
    by_id = {row["operation_id"]: row for row in rows}
    assert set(by_id) == {"stripeWebhook", "health"}
    assert by_id["stripeWebhook"]["target"] == (
        "http://127.0.0.1:3000/hooks/stripe"
    )
    assert json.loads(by_id["stripeWebhook"]["body"]) == {"event": "payment"}


def test_openapi_human_output_and_filters(
    tmp_path, capsys: pytest.CaptureFixture[str]
) -> None:
    path = _write_spec(tmp_path)
    assert (
        umbrella.main(
            ["openapi", str(path), "--operation", "stripeWebhook"]
        )
        == 0
    )
    out = capsys.readouterr().out
    assert "POST /hooks/stripe" in out
    assert "target: http://127.0.0.1:3000/hooks/stripe" in out
    assert "body:" in out

    assert (
        umbrella.main(["openapi", str(path), "--operation", "missing"])
        == 1
    )
    assert "no operation with id" in capsys.readouterr().err


def test_openapi_base_url_override(
    tmp_path, capsys: pytest.CaptureFixture[str]
) -> None:
    path = _write_spec(tmp_path)
    assert (
        umbrella.main(
            [
                "openapi",
                str(path),
                "--operation",
                "health",
                "--base-url",
                "http://localhost:4000/api",
                "--json",
            ]
        )
        == 0
    )
    rows = json.loads(capsys.readouterr().out)
    assert rows[0]["target"] == "http://localhost:4000/api/health"


def test_openapi_bad_spec(
    tmp_path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert umbrella.main(["openapi", str(tmp_path / "missing.json")]) == 2
    assert "cannot read OpenAPI file" in capsys.readouterr().err


def test_console_script_entry() -> None:
    root = Path(__file__).resolve().parents[1]
    doc = tomllib.loads((root / "pyproject.toml").read_text(encoding="utf-8"))
    assert doc["project"]["scripts"]["kodyaz"] == "hookyard.umbrella:main"
