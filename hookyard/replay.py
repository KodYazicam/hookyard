from __future__ import annotations

import json
import urllib.error
import urllib.request
from typing import Any

from .store import RequestRecord

HOP_BY_HOP = {
    "connection",
    "keep-alive",
    "proxy-authenticate",
    "proxy-authorization",
    "te",
    "trailers",
    "transfer-encoding",
    "upgrade",
    "host",
    "content-length",
}


def replay(record: RequestRecord, target: str, timeout: float = 10.0) -> dict[str, Any]:
    headers = {
        k: v
        for k, v in record.headers.items()
        if k.lower() not in HOP_BY_HOP and not k.lower().startswith(":")
    }
    data = record.body.encode("utf-8") if record.body else None
    request = urllib.request.Request(target, data=data, method=record.method, headers=headers)
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            payload = response.read()[: 64_000]
            return {
                "ok": True,
                "status": response.status,
                "headers": dict(response.headers.items()),
                "body": payload.decode("utf-8", errors="replace"),
            }
    except urllib.error.HTTPError as error:
        payload = error.read()[: 64_000]
        return {
            "ok": False,
            "status": error.code,
            "headers": dict(error.headers.items()) if error.headers else {},
            "body": payload.decode("utf-8", errors="replace"),
        }
    except urllib.error.URLError as error:
        return {"ok": False, "status": 0, "headers": {}, "body": str(error.reason)}


def pretty_json(text: str) -> str:
    try:
        return json.dumps(json.loads(text), indent=2)
    except Exception:
        return text
