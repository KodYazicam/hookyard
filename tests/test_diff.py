from __future__ import annotations

from fastapi.testclient import TestClient

from hookyard.app import create_app
from hookyard.diff import diff_requests
from hookyard.store import new_record


def _record(
    method: str = "POST",
    path: str = "/hook",
    query: str = "",
    headers: dict[str, str] | None = None,
    body: str = '{"a":1}',
    remote: str = "127.0.0.1",
):
    return new_record(
        "demo",
        method,
        path,
        query,
        headers or {"content-type": "application/json"},
        body,
        remote,
    )


def test_identical_requests_are_same() -> None:
    left = _record()
    right = _record()
    result = diff_requests(left, right)
    assert result["same"] is True
    assert result["changes"] == {}
    assert result["left"]["id"] == left.id
    assert result["right"]["id"] == right.id


def test_scalar_and_header_changes() -> None:
    left = _record(
        method="POST",
        path="/hook",
        query="a=1",
        headers={
            "content-type": "application/json",
            "x-tag": "one",
            "x-old": "gone",
        },
    )
    right = _record(
        method="PUT",
        path="/hook2",
        query="a=2",
        headers={
            "content-type": "application/json",
            "x-tag": "two",
            "x-new": "yes",
        },
    )
    result = diff_requests(left, right)
    changes = result["changes"]
    assert result["same"] is False
    assert changes["method"] == {"left": "POST", "right": "PUT"}
    assert changes["path"] == {"left": "/hook", "right": "/hook2"}
    assert changes["query"] == {"left": "a=1", "right": "a=2"}
    assert changes["headers"]["added"] == {"x-new": "yes"}
    assert changes["headers"]["removed"] == {"x-old": "gone"}
    assert changes["headers"]["changed"]["x-tag"] == {
        "left": "one",
        "right": "two",
    }
    assert "content-type" not in changes["headers"].get("changed", {})


def test_header_names_are_case_insensitive() -> None:
    left = _record(headers={"X-Tag": "one"})
    right = _record(headers={"x-tag": "one"})
    result = diff_requests(left, right)
    assert "headers" not in result["changes"]
    assert result["same"] is True


def test_json_body_diff_is_pretty_printed() -> None:
    left = _record(body='{"b":2,"a":1}')
    right = _record(body='{"a":1,"b":3}')
    body = diff_requests(left, right)["changes"]["body"]
    assert body["left_format"] == "json"
    assert body["right_format"] == "json"
    assert '-  "b": 2' in body["unified"]
    assert '+  "b": 3' in body["unified"]


def test_text_body_diff_uses_lines() -> None:
    left = _record(body="line one\nline two")
    right = _record(body="line one\nline three")
    body = diff_requests(left, right)["changes"]["body"]
    assert body["left_format"] == "text"
    assert "-line two" in body["unified"]
    assert "+line three" in body["unified"]


def test_whitespace_only_json_change_falls_back_to_raw() -> None:
    left = _record(body='{"a":1}')
    right = _record(body='{"a": 1}')
    body = diff_requests(left, right)["changes"]["body"]
    assert body["left_format"] == "text"
    assert body["unified"]


def test_diff_endpoint() -> None:
    client = TestClient(create_app())
    one = client.post(
        "/b/demo/hook",
        content=b'{"a":1}',
        headers={"content-type": "application/json"},
    ).json()
    two = client.post(
        "/b/demo/hook",
        content=b'{"a":2}',
        headers={"content-type": "application/json"},
    ).json()

    result = client.get(
        "/api/bins/demo/diff",
        params={"left": one["id"], "right": two["id"]},
    ).json()
    assert result["bin"] == "demo"
    assert result["same"] is False
    assert "body" in result["changes"]

    same = client.get(
        "/api/bins/demo/diff",
        params={"left": one["id"], "right": one["id"]},
    ).json()
    assert same["same"] is True
    assert same["changes"] == {}

    assert (
        client.get("/api/bins/demo/diff", params={"left": one["id"]}).status_code
        == 400
    )
    assert (
        client.get(
            "/api/bins/demo/diff",
            params={"left": one["id"], "right": "nope"},
        ).status_code
        == 404
    )
    assert (
        client.get(
            "/api/bins/demo/diff",
            params={"left": "nope", "right": two["id"]},
        ).status_code
        == 404
    )


def test_diff_endpoint_does_not_cross_bins() -> None:
    client = TestClient(create_app())
    demo = client.post("/b/demo/hook", content=b"{}").json()
    other = client.post("/b/other/hook", content=b"{}").json()
    res = client.get(
        "/api/bins/demo/diff",
        params={"left": demo["id"], "right": other["id"]},
    )
    assert res.status_code == 404
