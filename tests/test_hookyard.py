from __future__ import annotations

import base64
import hashlib
import hmac
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from fastapi.testclient import TestClient

from hookyard.app import create_app
from hookyard.signatures import verify_github, verify_stripe, verify_slack, verify_discord, verify_hmac
from hookyard.persist import JsonFileStore
from hookyard.store import MemoryStore, new_record
from hookyard.replay import pretty_json, replay, host_allowed
from hookyard.cli import build_parser


def test_github_signature() -> None:
    body = b'{"ok":true}'
    secret = "s3cret"
    digest = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    assert verify_github(body, f"sha256={digest}", secret)
    assert not verify_github(body, "sha256=dead", secret)
    assert not verify_github(body, "sha256=short", secret)


def test_stripe_signature() -> None:
    body = b'{"id":"evt"}'
    secret = "whsec_test"
    ts = str(int(time.time()))
    digest = hmac.new(secret.encode(), f"{ts}.".encode() + body, hashlib.sha256).hexdigest()
    header = f"t={ts},v1={digest}"
    assert verify_stripe(body, header, secret)
    assert verify_stripe(body, f"t={ts},v1=nope,v1={digest}", secret)
    assert not verify_stripe(body, f"t={ts},v1=nope", secret)


def test_slack_signature() -> None:
    body = b"payload=ok"
    secret = "slack-secret"
    ts = str(int(time.time()))
    basestring = b"v0:" + ts.encode() + b":" + body
    sig = "v0=" + hmac.new(secret.encode(), basestring, hashlib.sha256).hexdigest()
    assert verify_slack(body, ts, sig, secret)
    assert not verify_slack(body, ts, "v0=nope", secret)


def test_discord_without_nacl() -> None:
    assert verify_discord(b"{}", "ab", "1", "00") is False


def test_hmac_signature_hex_and_base64() -> None:
    body = b'{"shopify":true}'
    secret = "shop-shared-secret"
    digest = hmac.new(secret.encode(), body, hashlib.sha256).digest()
    assert verify_hmac(body, digest.hex(), secret)
    assert verify_hmac(body, base64.b64encode(digest).decode(), secret)
    assert verify_hmac(body, f"  {digest.hex()} ", secret)
    assert not verify_hmac(body, "deadbeef", secret)
    assert not verify_hmac(body, None, secret)
    assert not verify_hmac(body, digest.hex(), "")
    assert not verify_hmac(body, "é", secret)


def test_app_verifies_generic_hmac_with_custom_header() -> None:
    secret = "shop-shared-secret"
    body = b'{"id":1}'
    digest = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    app = create_app(secrets={"hmac": secret}, hmac_header="x-shopify-hmac-sha256")
    client = TestClient(app)
    client.post(
        "/b/shop",
        content=body,
        headers={"content-type": "application/json", "x-shopify-hmac-sha256": digest},
    )
    listed = client.get("/api/bins/shop").json()
    assert listed["requests"][0]["signatures"]["hmac"] is True

    client.post(
        "/b/shop2",
        content=body,
        headers={"content-type": "application/json", "x-shopify-hmac-sha256": "nope"},
    )
    listed = client.get("/api/bins/shop2").json()
    assert listed["requests"][0]["signatures"]["hmac"] is False


def test_store_and_pretty() -> None:
    store = MemoryStore(limit=2)
    bin_id = store.create_bin("demo")
    a = new_record(bin_id, "POST", "/", "", {}, '{"a":1}', "1.1.1.1")
    b = new_record(bin_id, "POST", "/", "", {}, '{"b":2}', "1.1.1.1")
    c = new_record(bin_id, "POST", "/", "", {}, '{"c":3}', "1.1.1.1")
    store.add(a)
    store.add(b)
    store.add(c)
    assert len(store.list(bin_id)) == 2
    assert pretty_json('{"a":1}') == '{\n  "a": 1\n}'
    assert replay(a, "not-a-url")["ok"] is False
    assert replay(a, "http://example.com/hook")["ok"] is False


def test_host_allowed_blocks_public_and_metadata() -> None:
    ok, _ = host_allowed("127.0.0.1", False)
    assert ok
    ok, _ = host_allowed("10.0.0.5", False)
    assert ok
    ok, reason = host_allowed("172.32.0.1", False)
    assert not ok
    ok, _ = host_allowed("172.16.0.1", False)
    assert ok
    ok, _ = host_allowed("169.254.169.254", True)
    assert not ok
    ok, _ = host_allowed("0.0.0.0", False)
    assert not ok
    ok, _ = host_allowed("8.8.8.8", False)
    assert not ok
    ok, _ = host_allowed("8.8.8.8", True)
    assert ok


def test_replay_blocks_redirect_to_metadata() -> None:
    class RedirectToMetadata(BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            self.send_response(302)
            self.send_header("Location", "http://169.254.169.254/latest/meta-data/")
            self.end_headers()

        def log_message(self, *args: object) -> None:
            return

    server = ThreadingHTTPServer(("127.0.0.1", 0), RedirectToMetadata)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        record = new_record("demo", "GET", "/", "", {}, "", "127.0.0.1")
        result = replay(record, f"http://127.0.0.1:{server.server_port}/redirect")
        assert result["ok"] is False
        assert result["status"] == 0
        assert result["body"] == "replay failed"
    finally:
        server.shutdown()
        server.server_close()


def test_app_catch_and_api() -> None:
    secret = "gh"
    app = create_app(secrets={"github": secret})
    client = TestClient(app)
    assert client.get("/health").json()["name"] == "hookyard"
    body = b'{"hello":"world"}'
    digest = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    res = client.post(
        "/b/demo/stripe",
        content=body,
        headers={"content-type": "application/json", "x-hub-signature-256": f"sha256={digest}"},
    )
    assert res.status_code == 200
    data = res.json()
    listed = client.get("/api/bins/demo").json()
    assert listed["requests"][0]["id"] == data["id"]
    assert listed["requests"][0]["signatures"]["github"] is True
    one = client.get(f"/api/bins/demo/{data['id']}").json()
    assert "hello" in one["pretty"]
    assert client.get("/").status_code == 200


def test_token_protects_ui_not_catch() -> None:
    app = create_app(token="s3cret")
    client = TestClient(app)
    assert client.get("/api/bins").status_code == 401
    assert client.get("/api/bins", headers={"Authorization": "Bearer s3cret"}).status_code == 200
    caught = client.post("/b/demo", content=b"{}")
    assert caught.status_code == 200


def test_discord_ping_requires_key() -> None:
    app = create_app()
    client = TestClient(app)
    res = client.post("/b/demo", content=b'{"type":1}', headers={"content-type": "application/json"})
    assert res.status_code == 401


def test_json_file_store(tmp_path) -> None:
    path = tmp_path / "store.json"
    store = JsonFileStore(path, limit=10)
    bin_id = store.create_bin("demo")
    store.add(new_record(bin_id, "POST", "/hook", "", {"x": "1"}, '{"ok":true}', "127.0.0.1"))
    again = JsonFileStore(path, limit=10)
    rows = again.list("demo")
    assert len(rows) == 1
    assert rows[0].body == '{"ok":true}'
    again.clear("demo")
    assert JsonFileStore(path).list("demo") == []


def test_cli_parser() -> None:
    args = build_parser().parse_args(["--port", "9999", "--version", "--token", "abc"])
    assert args.port == 9999
    assert args.version
    assert args.token == "abc"


def test_invalid_bin_id() -> None:
    app = create_app()
    client = TestClient(app)
    assert client.post("/b/no spaces", content=b"x").status_code in {400, 404}
