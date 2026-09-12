from __future__ import annotations

import secrets
import threading
import time
from dataclasses import dataclass, field, asdict
from typing import Any, Callable


@dataclass
class RequestRecord:
    id: str
    bin_id: str
    method: str
    path: str
    query: str
    headers: dict[str, str]
    body: str
    content_type: str
    remote: str
    created_at: float
    size: int
    signatures: dict[str, bool] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["created_at"] = self.created_at
        return data


Listener = Callable[[RequestRecord], None]


class MemoryStore:
    def __init__(self, limit: int = 500) -> None:
        self.limit = limit
        self._lock = threading.Lock()
        self._bins: dict[str, list[RequestRecord]] = {}
        self._listeners: list[Listener] = []

    def create_bin(self, bin_id: str | None = None) -> str:
        ident = bin_id or secrets.token_urlsafe(8)
        with self._lock:
            self._bins.setdefault(ident, [])
        return ident

    def bins(self) -> list[str]:
        with self._lock:
            return sorted(self._bins)

    def add(self, record: RequestRecord) -> RequestRecord:
        with self._lock:
            bucket = self._bins.setdefault(record.bin_id, [])
            bucket.insert(0, record)
            del bucket[self.limit :]
        for listener in list(self._listeners):
            listener(record)
        return record

    def list(self, bin_id: str, limit: int = 100) -> list[RequestRecord]:
        with self._lock:
            return list(self._bins.get(bin_id, []))[:limit]

    def get(self, bin_id: str, request_id: str) -> RequestRecord | None:
        with self._lock:
            for item in self._bins.get(bin_id, []):
                if item.id == request_id:
                    return item
        return None

    def clear(self, bin_id: str) -> int:
        with self._lock:
            n = len(self._bins.get(bin_id, []))
            self._bins[bin_id] = []
            return n

    def subscribe(self, listener: Listener) -> Callable[[], None]:
        self._listeners.append(listener)

        def unsub() -> None:
            if listener in self._listeners:
                self._listeners.remove(listener)

        return unsub


def new_record(
    bin_id: str,
    method: str,
    path: str,
    query: str,
    headers: dict[str, str],
    body: str,
    remote: str,
    signatures: dict[str, bool] | None = None,
) -> RequestRecord:
    return RequestRecord(
        id=secrets.token_hex(8),
        bin_id=bin_id,
        method=method.upper(),
        path=path,
        query=query,
        headers=headers,
        body=body,
        content_type=headers.get("content-type", ""),
        remote=remote,
        created_at=time.time(),
        size=len(body.encode("utf-8")),
        signatures=signatures or {},
    )
