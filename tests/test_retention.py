from __future__ import annotations

import json
import time

import pytest

from hookyard.cli import build_parser
from hookyard.cli import main as cli_main
from hookyard.persist import JsonFileStore
from hookyard.store import MemoryStore, new_record

DAY = 86_400.0


def _record(
    bin_id: str,
    created_at: float | None = None,
    *,
    path: str = "/hook",
):
    record = new_record(
        bin_id,
        "POST",
        path,
        "",
        {"content-type": "application/json"},
        '{"ok":true}',
        "127.0.0.1",
    )
    if created_at is not None:
        record.created_at = created_at
    return record


def test_default_retention_is_off() -> None:
    now = time.time()
    store = MemoryStore()
    store.add(_record("old", now - 10 * DAY))
    store.add(_record("middle", now - 5 * DAY))
    store.add(_record("fresh", now))

    assert store.max_bins is None
    assert store.max_age_days is None
    assert set(store.bins()) == {"old", "middle", "fresh"}


def test_max_bins_removes_the_oldest_bins() -> None:
    now = time.time()
    store = MemoryStore(max_bins=2)
    for offset, bin_id in enumerate(("oldest", "middle", "newest")):
        store.add(_record(bin_id, now + offset))

    assert set(store.bins()) == {"middle", "newest"}
    assert store.list("oldest") == []


def test_max_age_removes_stale_bins() -> None:
    now = time.time()
    store = MemoryStore(max_age_days=1)
    store.add(_record("stale", now - 2 * DAY))
    assert store.bins() == []

    store.add(_record("fresh", now))
    assert store.bins() == ["fresh"]


def test_max_bins_and_max_age_work_together() -> None:
    now = time.time()
    store = MemoryStore()
    for bin_id, age in (
        ("ancient", 3 * DAY),
        ("two-hours", 2 * 3_600),
        ("one-hour", 3_600),
        ("fresh", 60),
    ):
        store.add(_record(bin_id, now - age))

    store.max_bins = 2
    store.max_age_days = 1
    removed = store.prune(now=now)

    assert set(removed) == {"ancient", "two-hours"}
    assert set(store.bins()) == {"one-hour", "fresh"}


def test_empty_bins_are_removed_before_data_bearing_bins() -> None:
    now = time.time()
    store = MemoryStore(max_bins=1)
    store.create_bin("empty")
    store.add(_record("kept", now))

    assert store.bins() == ["kept"]


def test_startup_prunes_by_age_and_persists(tmp_path) -> None:
    path = tmp_path / "store.json"
    now = time.time()
    seed = JsonFileStore(path)
    seed.add(_record("ancient", now - 10 * DAY))
    seed.add(_record("recent", now))

    pruned = JsonFileStore(path, max_age_days=1)

    assert pruned.bins() == ["recent"]
    raw = json.loads(path.read_text(encoding="utf-8"))
    assert set(raw["bins"]) == {"recent"}
    assert JsonFileStore(path).bins() == ["recent"]
    assert not path.with_suffix(".json.tmp").exists()


def test_startup_prunes_by_bin_count(tmp_path) -> None:
    path = tmp_path / "store.json"
    now = time.time()
    seed = JsonFileStore(path)
    for offset, bin_id in enumerate(("oldest", "middle", "newest")):
        seed.add(_record(bin_id, now + offset))

    pruned = JsonFileStore(path, max_bins=2)

    assert set(pruned.bins()) == {"middle", "newest"}
    assert set(json.loads(path.read_text(encoding="utf-8"))["bins"]) == {
        "middle",
        "newest",
    }


def test_prune_rewrites_a_valid_data_file(tmp_path) -> None:
    path = tmp_path / "store.json"
    now = time.time()
    store = JsonFileStore(path)
    store.add(_record("old", now - 100))
    store.add(_record("new", now))

    store.max_bins = 1
    removed = store.prune(now=now)

    assert set(removed) == {"old"}
    raw = json.loads(path.read_text(encoding="utf-8"))
    assert set(raw["bins"]) == {"new"}
    assert raw["bins"]["new"][0]["body"] == '{"ok":true}'
    assert JsonFileStore(path).bins() == ["new"]
    assert not path.with_suffix(".json.tmp").exists()


def test_retention_keeps_the_per_bin_request_limit() -> None:
    now = time.time()
    store = MemoryStore(limit=1, max_bins=2)
    store.add(_record("demo", now))
    store.add(_record("demo", now + 1))
    store.add(_record("other", now + 2))

    assert set(store.bins()) == {"demo", "other"}
    assert len(store.list("demo")) == 1


@pytest.mark.parametrize(
    "kwargs",
    [
        {"max_bins": 0},
        {"max_bins": -1},
        {"max_bins": True},
        {"max_age_days": 0},
        {"max_age_days": -1},
        {"max_age_days": True},
        {"max_age_days": float("nan")},
        {"max_age_days": float("inf")},
    ],
)
def test_store_rejects_invalid_retention_values(kwargs) -> None:
    with pytest.raises(ValueError):
        MemoryStore(**kwargs)


def test_json_store_rejects_invalid_retention_before_creating_a_file(tmp_path) -> None:
    path = tmp_path / "store.json"
    with pytest.raises(ValueError):
        JsonFileStore(path, max_bins=0)
    assert not path.exists()


def test_cli_parser_accepts_retention_flags() -> None:
    args = build_parser().parse_args(
        ["--max-bins", "3", "--max-age-days", "1.5"]
    )
    assert args.max_bins == 3
    assert args.max_age_days == 1.5

    defaults = build_parser().parse_args([])
    assert defaults.max_bins is None
    assert defaults.max_age_days is None


@pytest.mark.parametrize(
    "argv",
    [
        ["--max-bins", "0"],
        ["--max-bins", "-2"],
        ["--max-age-days", "0"],
        ["--max-age-days", "-1"],
    ],
)
def test_cli_rejects_invalid_retention_flags(argv, capsys) -> None:
    assert cli_main(argv) == 2
    assert "max-" in capsys.readouterr().err


def test_cli_rejects_invalid_retention_env(monkeypatch, capsys) -> None:
    monkeypatch.setenv("HOOKYARD_MAX_BINS", "0")
    assert cli_main(["--max-age-days", "1"]) == 2
    assert "HOOKYARD_MAX_BINS" in capsys.readouterr().err

    monkeypatch.delenv("HOOKYARD_MAX_BINS")
    monkeypatch.setenv("HOOKYARD_MAX_AGE_DAYS", "-3")
    assert cli_main(["--max-bins", "2"]) == 2
    assert "HOOKYARD_MAX_AGE_DAYS" in capsys.readouterr().err


def test_cli_rejects_unparseable_retention_env(monkeypatch, capsys) -> None:
    monkeypatch.setenv("HOOKYARD_MAX_BINS", "lots")
    assert cli_main(["--max-age-days", "1"]) == 2
    assert "HOOKYARD_MAX_BINS" in capsys.readouterr().err


def test_cli_wires_flags_and_env_into_the_store(tmp_path, monkeypatch) -> None:
    captured = {}

    def fake_create_app(**kwargs):
        captured["store"] = kwargs["store"]
        return object()

    monkeypatch.setattr("hookyard.app.create_app", fake_create_app)
    monkeypatch.setattr("uvicorn.run", lambda *args, **kwargs: None)

    path = tmp_path / "store.json"
    assert cli_main(
        [
            "--data-file",
            str(path),
            "--max-bins",
            "3",
            "--max-age-days",
            "2.5",
        ]
    ) == 0
    store = captured["store"]
    assert store.max_bins == 3
    assert store.max_age_days == 2.5

    captured.clear()
    monkeypatch.setenv("HOOKYARD_MAX_BINS", "4")
    monkeypatch.setenv("HOOKYARD_MAX_AGE_DAYS", "7")
    assert cli_main(["--data-file", str(path)]) == 0
    store = captured["store"]
    assert store.max_bins == 4
    assert store.max_age_days == 7.0
