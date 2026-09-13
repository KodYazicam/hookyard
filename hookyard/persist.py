from __future__ import annotations

import json
from pathlib import Path

from .store import MemoryStore, RequestRecord


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
                    if not isinstance(item, dict):
                        continue
                    try:
                        bucket.append(
                            RequestRecord(
                                id=str(item["id"]),
                                bin_id=str(item.get("bin_id") or bin_id),
                                method=str(item.get("method") or "POST"),
                                path=str(item.get("path") or "/"),
                                query=str(item.get("query") or ""),
                                headers=dict(item.get("headers") or {}),
                                body=str(item.get("body") or ""),
                                content_type=str(item.get("content_type") or ""),
                                remote=str(item.get("remote") or ""),
                                created_at=float(item.get("created_at") or 0),
                                size=int(item.get("size") or 0),
                                signatures=dict(item.get("signatures") or {}),
                            )
                        )
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
