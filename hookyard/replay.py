from __future__ import annotations

import json
import urllib.error
import urllib.request
from typing import Any
from urllib.parse import urlparse

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


BLOCKED_HOSTS = {
    "169.254.169.254",
    "metadata.google.internal",
    "metadata.goog",
}

def _host_allowed(hostname: str, allow_remote: bool) -> bool:
    host = hostname.lower().rstrip(".")
    if host in BLOCKED_HOSTS:
        return False
    if allow_remote:
        return True
    if host in {"localhost", "127.0.0.1", "::1", "0.0.0.0"}:
        return True
    if host.startswith("10.") or host.startswith("192.168.") or host.startswith("172."):
        return True
    return False


def replay(record: RequestRecord, target: str, timeout: float = 10.0, allow_remote: bool = False) -> dict[str, Any]:
    parsed = urlparse(target)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        return {"ok": False, "status": 0, "headers": {}, "body": "target must be http(s)"}
    hostname = parsed.hostname or ""
    if not _host_allowed(hostname, allow_remote):
        return {
            "ok": False,
            "status": 0,
            "headers": {},
            "body": "replay is limited to localhost/private hosts (pass allow_remote to override)",
        }
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
