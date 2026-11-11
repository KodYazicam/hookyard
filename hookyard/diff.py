"""Read-only diffs between two captured requests."""

from __future__ import annotations

import difflib
import json
from typing import Any

from .store import RequestRecord

SCALAR_FIELDS = ("method", "path", "query", "content_type", "remote")


def diff_requests(left: RequestRecord, right: RequestRecord) -> dict[str, Any]:
    changes: dict[str, Any] = {}
    for field in SCALAR_FIELDS:
        left_value = getattr(left, field)
        right_value = getattr(right, field)
        if left_value != right_value:
            changes[field] = {"left": left_value, "right": right_value}

    headers = _diff_headers(left.headers, right.headers)
    if headers:
        changes["headers"] = headers
    if left.body != right.body:
        changes["body"] = _body_diff(left.body, right.body)

    return {
        "left": _summary(left),
        "right": _summary(right),
        "same": not changes,
        "changes": changes,
    }


def _summary(record: RequestRecord) -> dict[str, Any]:
    return {
        "id": record.id,
        "method": record.method,
        "path": record.path,
        "created_at": record.created_at,
        "size": record.size,
    }


def _diff_headers(
    left: dict[str, str], right: dict[str, str]
) -> dict[str, Any]:
    left_headers = {str(key).lower(): str(value) for key, value in left.items()}
    right_headers = {str(key).lower(): str(value) for key, value in right.items()}
    added = {
        key: right_headers[key]
        for key in sorted(right_headers.keys() - left_headers.keys())
    }
    removed = {
        key: left_headers[key]
        for key in sorted(left_headers.keys() - right_headers.keys())
    }
    changed = {
        key: {"left": left_headers[key], "right": right_headers[key]}
        for key in sorted(left_headers.keys() & right_headers.keys())
        if left_headers[key] != right_headers[key]
    }
    result: dict[str, Any] = {}
    if added:
        result["added"] = added
    if removed:
        result["removed"] = removed
    if changed:
        result["changed"] = changed
    return result


def _body_diff(left: str, right: str) -> dict[str, Any]:
    left_text, left_format = _pretty(left)
    right_text, right_format = _pretty(right)
    if left_text == right_text and left != right:
        left_text, right_text = left, right
        left_format = right_format = "text"
    unified = "\n".join(
        difflib.unified_diff(
            left_text.splitlines(),
            right_text.splitlines(),
            fromfile=f"left ({left_format})",
            tofile=f"right ({right_format})",
            lineterm="",
        )
    )
    return {
        "left_size": len(left.encode("utf-8")),
        "right_size": len(right.encode("utf-8")),
        "left_format": left_format,
        "right_format": right_format,
        "unified": unified,
    }


def _pretty(text: str) -> tuple[str, str]:
    try:
        return json.dumps(json.loads(text), indent=2, sort_keys=True), "json"
    except (json.JSONDecodeError, TypeError):
        return text, "text"
