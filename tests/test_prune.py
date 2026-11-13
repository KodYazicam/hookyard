from __future__ import annotations

import json
import time

import pytest

from hookyard.cli import main as cli_main
from hookyard.persist import JsonFileStore
from hookyard.store import MemoryStore, new_record

DAY = 86_400.0


def _record(bin_id: str, created_at: float):
    record = new_record(
        bin_id,
        "POST",
        "/hook",
        "",
        {"content-type": "application/json"},
        '{"ok":true}',
        "127.0.0.1",
    )
    record.created_at = created_at
    return record


def _seed(path, rows: list[tuple[str, float]]) -> None:
    store = JsonFileStore(path)
    for bin_id, created_at in rows:
        store.add(_record(bin_id, created_at))


def test_preview_prune_does_not_mutate_the_store() -> None:
    now = time.time()
    store = MemoryStore()
    store.add(_record("oldest", now))
    store.add(_record("newest", now + 1))
    store.configure_retention(max_bins=1)

    preview = store.preview_prune(now=now + 2)
    assert preview == ["oldest"]
    assert set(store.bins()) == {"oldest", "newest"}

    removed = store.prune(now=now + 2)
    assert removed == preview
    assert store.bins() == ["newest"]


def test_prune_dry_run_lists_without_writing(tmp_path, capsys) -> None:
    now = time.time()
    path = tmp_path / "store.json"
    _seed(
        path,
        [("oldest", now), ("middle", now + 1), ("newest", now + 2)],
    )
    before = path.read_bytes()

    assert (
        cli_main(
            [
                "prune",
                "--dry-run",
                "--data-file",
                str(path),
                "--max-bins",
                "1",
            ]
        )
        == 0
    )

    out = capsys.readouterr().out
    assert "would remove 2 bins" in out
    assert "oldest" in out
    assert "middle" in out
    assert path.read_bytes() == before
    assert set(JsonFileStore(path).bins()) == {"oldest", "middle", "newest"}
    assert not path.with_suffix(".json.tmp").exists()


def test_prune_removes_bins_and_reports_the_count(tmp_path, capsys) -> None:
    now = time.time()
    path = tmp_path / "store.json"
    _seed(
        path,
        [("oldest", now), ("middle", now + 1), ("newest", now + 2)],
    )

    assert (
        cli_main(
            ["prune", "--data-file", str(path), "--max-bins", "1"]
        )
        == 0
    )

    out = capsys.readouterr().out
    assert "removed 2 bins" in out
    assert "oldest" in out
    assert "middle" in out

    raw = json.loads(path.read_text(encoding="utf-8"))
    assert set(raw["bins"]) == {"newest"}
    assert raw["bins"]["newest"][0]["body"] == '{"ok":true}'
    assert JsonFileStore(path).bins() == ["newest"]
    assert not path.with_suffix(".json.tmp").exists()


def test_prune_uses_env_limits(tmp_path, monkeypatch, capsys) -> None:
    now = time.time()
    path = tmp_path / "store.json"
    _seed(path, [("stale", now - 10 * DAY), ("fresh", now)])
    monkeypatch.setenv("HOOKYARD_DATA_FILE", str(path))
    monkeypatch.setenv("HOOKYARD_MAX_AGE_DAYS", "1")
    monkeypatch.delenv("HOOKYARD_MAX_BINS", raising=False)

    assert cli_main(["prune"]) == 0

    out = capsys.readouterr().out
    assert "removed 1 bin" in out
    assert "stale" in out
    assert JsonFileStore(path).bins() == ["fresh"]


def test_prune_with_retention_off_removes_nothing(
    tmp_path, monkeypatch, capsys
) -> None:
    now = time.time()
    path = tmp_path / "store.json"
    _seed(path, [("oldest", now), ("newest", now + 1)])
    monkeypatch.delenv("HOOKYARD_DATA_FILE", raising=False)
    monkeypatch.delenv("HOOKYARD_MAX_BINS", raising=False)
    monkeypatch.delenv("HOOKYARD_MAX_AGE_DAYS", raising=False)
    before = path.read_bytes()

    assert cli_main(["prune", "--data-file", str(path)]) == 0

    assert "retention is not configured" in capsys.readouterr().out
    assert path.read_bytes() == before
    assert set(JsonFileStore(path).bins()) == {"oldest", "newest"}


def test_prune_requires_a_data_file(monkeypatch, capsys) -> None:
    monkeypatch.delenv("HOOKYARD_DATA_FILE", raising=False)
    assert cli_main(["prune", "--dry-run"]) == 2
    assert "data file is required" in capsys.readouterr().err


@pytest.mark.parametrize(
    "argv",
    [
        ["--max-bins", "0"],
        ["--max-bins", "-1"],
        ["--max-age-days", "0"],
        ["--max-age-days", "-1"],
    ],
)
def test_prune_rejects_invalid_limits(tmp_path, argv, capsys) -> None:
    path = tmp_path / "store.json"
    _seed(path, [("demo", time.time())])
    before = path.read_bytes()

    assert cli_main(["prune", "--data-file", str(path), *argv]) == 2
    assert "max-" in capsys.readouterr().err
    assert path.read_bytes() == before


def test_prune_dry_run_does_not_create_a_missing_file(tmp_path) -> None:
    path = tmp_path / "missing" / "store.json"

    assert (
        cli_main(
            [
                "prune",
                "--dry-run",
                "--data-file",
                str(path),
                "--max-bins",
                "1",
            ]
        )
        == 0
    )

    assert not path.exists()
    assert not path.parent.exists()


def test_failed_prune_write_leaves_the_data_file_intact(
    tmp_path, monkeypatch
) -> None:
    now = time.time()
    path = tmp_path / "store.json"
    _seed(path, [("oldest", now), ("newest", now + 1)])
    before = path.read_bytes()
    store = JsonFileStore(path)
    store.configure_retention(max_bins=1)

    def fail_save() -> None:
        raise OSError("disk full")

    monkeypatch.setattr(store, "_save", fail_save)
    with pytest.raises(OSError, match="disk full"):
        store.prune()

    assert path.read_bytes() == before
    assert set(JsonFileStore(path).bins()) == {"oldest", "newest"}
