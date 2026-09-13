from __future__ import annotations

import ipaddress
import json
import socket
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
    except OSError as error:
        return False, f"dns failed: {error}"
    if not ips:
        return False, "dns returned no addresses"
    for ip in ips:
        if _ip_is_blocked(ip, allow_remote):
            return False, f"{host} resolved to blocked address {ip}"
    return True, ""


def replay(record: RequestRecord, target: str, timeout: float = 10.0, allow_remote: bool = False) -> dict[str, Any]:
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
    data = record.body.encode("utf-8") if record.body else None
    request = urllib.request.Request(target, data=data, method=record.method, headers=headers)
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
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
        return {"ok": False, "status": 0, "headers": {}, "body": str(error.reason)}


def pretty_json(text: str) -> str:
    try:
        return json.dumps(json.loads(text), indent=2)
    except Exception:
        return text
