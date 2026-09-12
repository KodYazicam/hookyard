from __future__ import annotations

import hashlib
import hmac
import time


def _eq(left: str, right: str) -> bool:
    return hmac.compare_digest(left, right)


def verify_github(body: bytes, signature_header: str | None, secret: str) -> bool:
    if not signature_header or not secret:
        return False
    digest = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    expected = f"sha256={digest}"
    return _eq(expected, signature_header)


def verify_stripe(body: bytes, signature_header: str | None, secret: str, tolerance: int = 300) -> bool:
    if not signature_header or not secret:
        return False
    timestamp = None
    signatures: list[str] = []
    for item in signature_header.split(","):
        if "=" not in item:
            continue
        key, value = item.strip().split("=", 1)
        if key == "t":
            timestamp = value
        elif key == "v1":
            signatures.append(value)
    if not timestamp or not signatures:
        return False
    try:
        ts = int(timestamp)
    except ValueError:
        return False
    if abs(time.time() - ts) > tolerance:
        return False
    signed = f"{timestamp}.".encode() + body
    digest = hmac.new(secret.encode(), signed, hashlib.sha256).hexdigest()
    return any(_eq(digest, signature) for signature in signatures)


def verify_slack(body: bytes, timestamp: str | None, signature: str | None, secret: str, tolerance: int = 300) -> bool:
    if not timestamp or not signature or not secret:
        return False
    try:
        ts = int(timestamp)
    except ValueError:
        return False
    if abs(time.time() - ts) > tolerance:
        return False
    basestring = f"v0:{timestamp}:{body.decode('utf-8')}".encode()
    digest = "v0=" + hmac.new(secret.encode(), basestring, hashlib.sha256).hexdigest()
    return _eq(digest, signature)


def verify_discord(body: bytes, signature: str | None, timestamp: str | None, public_key_hex: str) -> bool:
    """Ed25519 verification without extra deps.

    Returns False when cryptography/nacl is unavailable or the key is invalid.
    Tests cover the failure path; production installs can add pynacl.
    """
    if not signature or not timestamp or not public_key_hex:
        return False
    try:
        from nacl.signing import VerifyKey  # type: ignore
        from nacl.exceptions import BadSignatureError  # type: ignore
    except ImportError:
        return False
    try:
        key = VerifyKey(bytes.fromhex(public_key_hex))
        key.verify(timestamp.encode() + body, bytes.fromhex(signature))
        return True
    except (ValueError, BadSignatureError):
        return False


def inspect_headers(
    body: bytes,
    headers: dict[str, str],
    secrets: dict[str, str],
) -> dict[str, bool]:
    lower = {k.lower(): v for k, v in headers.items()}
    result: dict[str, bool] = {}
    if "github" in secrets:
        result["github"] = verify_github(body, lower.get("x-hub-signature-256"), secrets["github"])
    if "stripe" in secrets:
        result["stripe"] = verify_stripe(body, lower.get("stripe-signature"), secrets["stripe"])
    if "slack" in secrets:
        result["slack"] = verify_slack(
            body,
            lower.get("x-slack-request-timestamp"),
            lower.get("x-slack-signature"),
            secrets["slack"],
        )
    if "discord" in secrets:
        result["discord"] = verify_discord(
            body,
            lower.get("x-signature-ed25519"),
            lower.get("x-signature-timestamp"),
            secrets["discord"],
        )
    return result
