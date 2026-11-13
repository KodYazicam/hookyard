from __future__ import annotations

import json
from pathlib import Path

from .store import MemoryStore, RequestRecord, record_from_dict


class JsonFileStore(MemoryStore):
    """MemoryStore that snapshots bins to a JSON file after every mutation."""

    def __init__(self, path: str | Path, limit: int = 500) -> None:
        super().__init__(limit=limit)
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._load()

    def _load(self) -> None:
        if not self.path.exists():
            return
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return
        bins = raw.get("bins") if isinstance(raw, dict) else None
        if not isinstance(bins, dict):
            return
        with self._lock:
            loaded: dict[str, list[RequestRecord]] = {}
            for bin_id, records in bins.items():
                bucket: list[RequestRecord] = []
                if not isinstance(records, list):
                    continue
                for item in records:
                    try:
                        bucket.append(record_from_dict(str(bin_id), item))
                    except (KeyError, TypeError, ValueError):
                        continue
                loaded[str(bin_id)] = bucket[: self.limit]
            self._bins = loaded

    def _snapshot(self) -> dict[str, list[RequestRecord]]:
        with self._lock:
            return {bin_id: list(records) for bin_id, records in self._bins.items()}

    def _save(self) -> None:
        snapshot = self._snapshot()
        payload = {
            "bins": {
                bin_id: [record.to_dict() for record in records]
                for bin_id, records in snapshot.items()
            }
        }
        tmp = self.path.with_suffix(self.path.suffix + ".tmp")
        tmp.write_text(json.dumps(payload), encoding="utf-8")
        tmp.replace(self.path)

    def create_bin(self, bin_id: str | None = None) -> str:
        ident = super().create_bin(bin_id)
        self._save()
        return ident

    def add(self, record: RequestRecord) -> RequestRecord:
        result = super().add(record)
        self._save()
        return result

    def clear(self, bin_id: str) -> int:
        n = super().clear(bin_id)
        self._save()
        return n

    def import_bin(self, bin_id: str, records: list[RequestRecord]) -> None:
        super().import_bin(bin_id, records)
        self._save()
