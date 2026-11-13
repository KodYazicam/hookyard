from __future__ import annotations

import json

import pytest

from hookyard import archive
from hookyard.cli import main as cli_main
from hookyard.persist import JsonFileStore
from hookyard.store import new_record


def _record(
    bin_id: str,
    path: str = "/hook",
    body: str = '{"ok":true}',
    *,
    method: str = "POST",
    query: str = "",
    headers: dict[str, str] | None = None,
    signatures: dict[str, bool] | None = None,
):
    return new_record(
        bin_id,
        method,
        path,
        query,
        headers or {"content-type": "application/json", "x-test": "1"},
        body,
        "127.0.0.1",
        signatures or {"github": True},
    )


def _seed(path) -> JsonFileStore:
    store = JsonFileStore(path)
    store.create_bin("demo")
    store.add(_record("demo", "/first", '{"n":1}', query="a=1"))
    store.add(
        _record(
            "demo",
            "/second",
            '{"n":2}',
            method="PUT",
            headers={"content-type": "text/plain"},
            signatures={"hmac": False},
        )
    )
    return store


def _dicts(store: JsonFileStore, bin_id: str) -> list[dict]:
    return [record.to_dict() for record in store.list(bin_id, limit=store.limit)]


def test_export_payload_has_version_and_records() -> None:
    records = [_record("demo")]
    payload = archive.export_payload("demo", records, exported_at="2026-01-01T00:00:00Z")
    assert payload["format"] == "hookyard-bin"
    assert payload["version"] == archive.ARCHIVE_VERSION == 1
    assert payload["bin"] == "demo"
    assert payload["exported_at"] == "2026-01-01T00:00:00Z"
    assert payload["requests"] == [records[0].to_dict()]


def test_export_import_round_trip(tmp_path) -> None:
    source_path = tmp_path / "source.json"
    source = _seed(source_path)
    expected = _dicts(source, "demo")
    target_archive = tmp_path / "demo.json"
    archive.write_archive(
        target_archive, "demo", source.list("demo", limit=source.limit)
    )
    loaded = archive.load_archive(target_archive)
    assert loaded.bin_id == "demo"
    assert [record.to_dict() for record in loaded.records] == expected

    target_path = tmp_path / "target.json"
    target = JsonFileStore(target_path)
    imported = archive.import_archive(target, loaded)
    assert imported == "demo"
    reloaded = JsonFileStore(target_path)
    assert _dicts(reloaded, "demo") == expected


def test_export_writes_atomically(tmp_path) -> None:
    path = tmp_path / "demo.json"
    archive.write_archive(path, "demo", [_record("demo")])
    assert path.exists()
    assert json.loads(path.read_text(encoding="utf-8"))["version"] == 1
    assert not path.with_suffix(".json.tmp").exists()


def test_write_archive_reports_unwritable_path(tmp_path) -> None:
    missing_parent = tmp_path / "missing" / "demo.json"
    with pytest.raises(archive.ArchiveError, match="cannot write archive"):
        archive.write_archive(missing_parent, "demo", [])
    assert not missing_parent.exists()


@pytest.mark.parametrize(
    "payload, message",
    [
        ([], "not a JSON object"),
        ({}, "missing 'version'"),
        ({"version": "1"}, "'version' must be an integer"),
        ({"version": True}, "'version' must be an integer"),
        ({"version": 2}, "unsupported archive version 2"),
        ({"version": 1, "format": "other"}, "'format' must be"),
        ({"version": 1}, "missing 'bin'"),
        ({"version": 1, "bin": "bad name"}, "invalid 'bin'"),
        ({"version": 1, "bin": "demo"}, "missing 'requests'"),
        ({"version": 1, "bin": "demo", "requests": {}}, "'requests' must be a list"),
        ({"version": 1, "bin": "demo", "requests": [1]}, "request #1 must be an object"),
        (
            {"version": 1, "bin": "demo", "requests": [{}]},
            "request #1: missing 'id'",
        ),
        (
            {
                "version": 1,
                "bin": "demo",
                "requests": [{"id": "a", "method": "POST"}],
            },
            "request #1: missing 'path'",
        ),
        (
            {
                "version": 1,
                "bin": "demo",
                "requests": [
                    dict(_record("demo").to_dict(), id="same"),
                    dict(_record("demo").to_dict(), id="same"),
                ],
            },
            "duplicate request id",
        ),
    ],
)
def test_parse_archive_rejects_bad_schema(payload, message: str) -> None:
    with pytest.raises(archive.ArchiveError, match=message):
        archive.parse_archive(payload)


def test_load_archive_rejects_invalid_json(tmp_path) -> None:
    path = tmp_path / "bad.json"
    path.write_text("not json", encoding="utf-8")
    with pytest.raises(archive.ArchiveError, match="not valid JSON"):
        archive.load_archive(path)


def test_load_archive_rejects_invalid_utf8(tmp_path) -> None:
    path = tmp_path / "bad.json"
    path.write_bytes(b"\xff\xfe")
    with pytest.raises(archive.ArchiveError, match="not valid UTF-8"):
        archive.load_archive(path)


def test_load_archive_rejects_missing_file(tmp_path) -> None:
    with pytest.raises(archive.ArchiveError, match="cannot read archive"):
        archive.load_archive(tmp_path / "missing.json")


def test_export_rejects_invalid_bin() -> None:
    with pytest.raises(archive.ArchiveError, match="invalid 'bin'"):
        archive.export_payload("bad name", [])


def test_invalid_archive_writes_nothing(tmp_path) -> None:
    data_path = tmp_path / "store.json"
    _seed(data_path)
    before = data_path.read_bytes()

    bad = tmp_path / "bad.json"
    bad.write_text(
        json.dumps({"version": 1, "bin": "demo", "requests": [{"id": "x"}]}),
        encoding="utf-8",
    )
    assert cli_main(["import", str(bad), "--data-file", str(data_path)]) == 2
    assert data_path.read_bytes() == before


def test_invalid_archive_does_not_create_data_file(tmp_path) -> None:
    bad = tmp_path / "bad.json"
    bad.write_text("not json", encoding="utf-8")
    data_path = tmp_path / "nested" / "store.json"
    assert cli_main(["import", str(bad), "--data-file", str(data_path)]) == 2
    assert not data_path.exists()
    assert not data_path.parent.exists()


def test_conflicting_bin_is_refused_then_renamed(tmp_path) -> None:
    data_path = tmp_path / "store.json"
    store = _seed(data_path)
    original = _dicts(store, "demo")

    records = [_record("demo", "/imported", '{"imported":true}')]
    archive_path = tmp_path / "demo.json"
    archive.write_archive(archive_path, "demo", records)

    assert (
        cli_main(["import", str(archive_path), "--data-file", str(data_path)])
        == 1
    )
    assert _dicts(JsonFileStore(data_path), "demo") == original

    assert (
        cli_main(
            [
                "import",
                str(archive_path),
                "--data-file",
                str(data_path),
                "--rename",
            ]
        )
        == 0
    )
    reloaded = JsonFileStore(data_path)
    assert reloaded.bins() == ["demo", "demo-2"]
    assert _dicts(reloaded, "demo") == original
    expected_import = [
        dict(record.to_dict(), bin_id="demo-2") for record in records
    ]
    assert _dicts(reloaded, "demo-2") == expected_import


def test_export_unknown_bin_leaves_no_file(tmp_path) -> None:
    data_path = tmp_path / "store.json"
    _seed(data_path)
    output = tmp_path / "missing.json"
    assert (
        cli_main(
            [
                "export",
                "missing",
                "-o",
                str(output),
                "--data-file",
                str(data_path),
            ]
        )
        == 1
    )
    assert not output.exists()


def test_cli_round_trip(tmp_path) -> None:
    source_path = tmp_path / "source.json"
    source = _seed(source_path)
    expected = _dicts(source, "demo")

    archive_path = tmp_path / "demo.json"
    assert (
        cli_main(
            [
                "export",
                "demo",
                "-o",
                str(archive_path),
                "--data-file",
                str(source_path),
            ]
        )
        == 0
    )
    assert archive_path.exists()

    target_path = tmp_path / "target.json"
    assert (
        cli_main(["import", str(archive_path), "--data-file", str(target_path)])
        == 0
    )
    assert _dicts(JsonFileStore(target_path), "demo") == expected


def test_archive_commands_require_data_file(tmp_path, monkeypatch) -> None:
    monkeypatch.delenv("HOOKYARD_DATA_FILE", raising=False)
    archive_path = tmp_path / "demo.json"
    archive.write_archive(archive_path, "demo", [])
    assert cli_main(["export", "demo", "-o", str(archive_path)]) == 2
    assert cli_main(["import", str(archive_path)]) == 2


def test_unique_bin_id_keeps_names_short() -> None:
    base = "a" * 64
    existing = {base, base[:62] + "-2"}
    assert archive.unique_bin_id(existing, base) == base[:62] + "-3"
