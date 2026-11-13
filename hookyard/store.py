from __future__ import annotations

import math
import secrets
import threading
import time
from dataclasses import dataclass, field, asdict, replace
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


def _validate_max_bins(value: int | None) -> int | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise ValueError("max_bins must be a positive integer")
    return value


def _validate_max_age_days(value: float | None) -> float | None:
    if value is None:
        return None
    if (
        isinstance(value, bool)
        or not isinstance(value, (int, float))
        or not math.isfinite(float(value))
        or value <= 0
    ):
        raise ValueError("max_age_days must be a positive number")
    return float(value)


def _last_activity(records: list[RequestRecord]) -> float | None:
    if not records:
        return None
    return max(record.created_at for record in records)


class MemoryStore:
    def __init__(
        self,
        limit: int = 500,
        *,
        max_bins: int | None = None,
        max_age_days: float | None = None,
    ) -> None:
        self.limit = limit
        self.max_bins = _validate_max_bins(max_bins)
        self.max_age_days = _validate_max_age_days(max_age_days)
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
            self._prune_locked()
        for listener in list(self._listeners):
            listener(record)
        return record

    def list(
        self,
        bin_id: str,
        limit: int = 100,
        q: str | None = None,
        method: str | None = None,
    ) -> list[RequestRecord]:
        needle = q.casefold() if q else ""
        method_filter = method.upper() if method else ""
        with self._lock:
            items = self._bins.get(bin_id, [])
            if not needle and not method_filter:
                return list(items)[:limit]
            found: list[RequestRecord] = []
            for item in items:
                if method_filter and item.method.upper() != method_filter:
                    continue
                if needle and not _matches(item, needle):
                    continue
                found.append(item)
                if len(found) >= limit:
                    break
            return found

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

    def _prune_locked(self, now: float | None = None) -> list[str]:
        if self.max_bins is None and self.max_age_days is None:
            return []

        current = time.time() if now is None else float(now)
        removed: list[str] = []

        if self.max_age_days is not None:
            cutoff = current - self.max_age_days * 86_400.0
            for bin_id, records in list(self._bins.items()):
                activity = _last_activity(records)
                if activity is not None and activity < cutoff:
                    removed.append(bin_id)
                    del self._bins[bin_id]

        if self.max_bins is not None and len(self._bins) > self.max_bins:
            # Empty bins have no activity; drop them before data-bearing bins,
            # then remove the least recently active data bins.
            candidates = sorted(
                self._bins.items(),
                key=lambda item: (
                    _last_activity(item[1]) is not None,
                    _last_activity(item[1]) or 0.0,
                    item[0],
                ),
            )
            for bin_id, _records in candidates:
                if len(self._bins) <= self.max_bins:
                    break
                removed.append(bin_id)
                del self._bins[bin_id]

        return removed

    def prune(self, now: float | None = None) -> list[str]:
        """Apply the configured retention policy and return removed bin ids."""
        with self._lock:
            return self._prune_locked(now)

    def import_bin(self, bin_id: str, records: list[RequestRecord]) -> None:
        """Insert a whole bin in one step, refusing to overwrite an existing one."""
        with self._lock:
            if bin_id in self._bins:
                raise ValueError(f"bin {bin_id!r} already exists")
            self._bins[bin_id] = [
                replace(record, bin_id=bin_id) for record in records
            ][: self.limit]
            self._prune_locked()

    def subscribe(self, listener: Listener) -> Callable[[], None]:
        self._listeners.append(listener)

        def unsub() -> None:
            if listener in self._listeners:
                self._listeners.remove(listener)

        return unsub


def _matches(record: RequestRecord, needle: str) -> bool:
    if needle in record.path.casefold() or needle in record.body.casefold():
        return True
    return any(
        needle in f"{key}: {value}".casefold()
        for key, value in record.headers.items()
    )


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


def record_from_dict(
    bin_id: str, item: Any, *, strict: bool = False
) -> RequestRecord:
    """Build a record from persisted JSON.

    Non-strict mode keeps the old data-file behaviour (missing method/path get
    defaults). Strict mode is used for archives and requires the core fields.
    """
    if not isinstance(item, dict):
        raise ValueError("must be an object")
    if strict:
        for field_name in (
            "id",
            "method",
            "path",
            "headers",
            "body",
            "created_at",
            "size",
        ):
            if field_name not in item:
                raise ValueError(f"missing {field_name!r}")

    ident = item.get("id")
    if not isinstance(ident, str) or not ident:
        raise ValueError("needs a non-empty 'id'")

    method = item.get("method", "POST")
    if not isinstance(method, str) or not method.strip():
        raise ValueError("needs a non-empty 'method'")

    path = item.get("path", "/")
    if not isinstance(path, str) or not path:
        raise ValueError("needs a non-empty 'path'")
    if not path.startswith("/"):
        raise ValueError("'path' must start with '/'")

    query = item.get("query", "")
    if not isinstance(query, str):
        raise ValueError("'query' must be a string")

    headers = item.get("headers", {})
    if not isinstance(headers, dict) or not all(
        isinstance(key, str) and isinstance(value, str)
        for key, value in headers.items()
    ):
        raise ValueError("'headers' must be an object of string keys and values")

    body = item.get("body", "")
    if not isinstance(body, str):
        raise ValueError("'body' must be a string")

    content_type = item.get("content_type", headers.get("content-type", ""))
    if not isinstance(content_type, str):
        raise ValueError("'content_type' must be a string")

    remote = item.get("remote", "")
    if not isinstance(remote, str):
        raise ValueError("'remote' must be a string")

    created_at = item.get("created_at", 0)
    if (
        isinstance(created_at, bool)
        or not isinstance(created_at, (int, float))
        or not math.isfinite(float(created_at))
        or created_at < 0
    ):
        raise ValueError("'created_at' must be a non-negative number")

    size = item.get("size", len(body.encode("utf-8")))
    if isinstance(size, bool) or not isinstance(size, int) or size < 0:
        raise ValueError("'size' must be a non-negative integer")

    signatures = item.get("signatures", {})
    if not isinstance(signatures, dict) or not all(
        isinstance(key, str) and isinstance(value, bool)
        for key, value in signatures.items()
    ):
        raise ValueError(
            "'signatures' must be an object of string keys and boolean values"
        )

    return RequestRecord(
        id=ident,
        bin_id=bin_id,
        method=method.upper(),
        path=path,
        query=query,
        headers=dict(headers),
        body=body,
        content_type=content_type,
        remote=remote,
        created_at=float(created_at),
        size=size,
        signatures=dict(signatures),
    )
