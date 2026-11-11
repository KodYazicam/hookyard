from __future__ import annotations

import ipaddress
import json
import logging
import socket
import urllib.error
import urllib.request
from typing import Any
from urllib.parse import urlparse

from .store import RequestRecord

logger = logging.getLogger(__name__)

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
    "metadata.google.internal.",
    "kubernetes.default",
    "kubernetes.default.svc",
}


def _ip_is_blocked(ip: ipaddress.IPv4Address | ipaddress.IPv6Address, allow_remote: bool) -> bool:
    if ip.is_unspecified or ip.is_multicast or ip.is_reserved or ip.is_link_local:
        return True
    if ip.is_loopback:
        return False
    mapped = getattr(ip, "ipv4_mapped", None)
    if mapped is not None:
        return _ip_is_blocked(mapped, allow_remote)
    if ip.is_private:
        return False
    return not allow_remote


def _resolve_ips(hostname: str) -> list[ipaddress.IPv4Address | ipaddress.IPv6Address]:
    infos = socket.getaddrinfo(hostname, None, type=socket.SOCK_STREAM)
    ips: list[ipaddress.IPv4Address | ipaddress.IPv6Address] = []
    for info in infos:
        sockaddr = info[4]
        if not sockaddr:
            continue
        ips.append(ipaddress.ip_address(sockaddr[0]))
    return ips


def host_allowed(hostname: str, allow_remote: bool) -> tuple[bool, str]:
    host = (hostname or "").strip().lower().rstrip(".")
    if not host:
        return False, "missing hostname"
    if host in BLOCKED_HOSTS:
        return False, "metadata hosts are blocked"
    if host in {"0.0.0.0", "::", "[::]"}:
        return False, "unspecified address is blocked"
    try:
        ip = ipaddress.ip_address(host.strip("[]"))
        if _ip_is_blocked(ip, allow_remote):
            return False, f"blocked address {ip}"
        return True, ""
    except ValueError:
        pass
    try:
        ips = _resolve_ips(host)
    except OSError:
        return False, "dns failed"
    if not ips:
        return False, "dns returned no addresses"
    for ip in ips:
        if _ip_is_blocked(ip, allow_remote):
            return False, f"{host} resolved to blocked address {ip}"
    return True, ""


class _SafeRedirectHandler(urllib.request.HTTPRedirectHandler):
    """Re-run the SSRF host checks for every redirect target."""

    def __init__(self, allow_remote: bool) -> None:
        self.allow_remote = allow_remote
        super().__init__()

    def redirect_request(self, req, fp, code, msg, headers, newurl):  # type: ignore[no-untyped-def]
        parsed = urlparse(newurl)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            raise urllib.error.URLError("redirect target must be http(s)")
        allowed, reason = host_allowed(parsed.hostname or "", self.allow_remote)
        if not allowed:
            raise urllib.error.URLError(f"redirect blocked: {reason}")
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def replay(
    record: RequestRecord,
    target: str,
    timeout: float = 10.0,
    allow_remote: bool = False,
    extra_headers: dict[str, str] | None = None,
) -> dict[str, Any]:
    parsed = urlparse(target)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        return {"ok": False, "status": 0, "headers": {}, "body": "target must be http(s)"}
    hostname = parsed.hostname or ""
    allowed, reason = host_allowed(hostname, allow_remote)
    if not allowed:
        return {
            "ok": False,
            "status": 0,
            "headers": {},
            "body": reason or "replay is limited to localhost/private hosts (pass allow_remote to override public IPs; metadata stays blocked)",
        }
    headers = {
        k: v
        for k, v in record.headers.items()
        if k.lower() not in HOP_BY_HOP and not k.lower().startswith(":")
    }
    if extra_headers:
        replaced = {key.lower() for key in extra_headers}
        headers = {
            key: value
            for key, value in headers.items()
            if key.lower() not in replaced
        }
        headers.update(extra_headers)
    data = record.body.encode("utf-8") if record.body else None
    request = urllib.request.Request(target, data=data, method=record.method, headers=headers)
    opener = urllib.request.build_opener(_SafeRedirectHandler(allow_remote))
    try:
        with opener.open(request, timeout=timeout) as response:
            payload = response.read()[:64_000]
            return {
                "ok": True,
                "status": response.status,
                "headers": dict(response.headers.items()),
                "body": payload.decode("utf-8", errors="replace"),
            }
    except urllib.error.HTTPError as error:
        payload = error.read()[:64_000]
        return {
            "ok": False,
            "status": error.code,
            "headers": dict(error.headers.items()) if error.headers else {},
            "body": payload.decode("utf-8", errors="replace"),
        }
    except urllib.error.URLError as error:
        logger.warning("replay failed for %s: %s", hostname, error.reason)
        return {"ok": False, "status": 0, "headers": {}, "body": "replay failed"}


def pretty_json(text: str) -> str:
    try:
        return json.dumps(json.loads(text), indent=2)
    except Exception:
        return text
