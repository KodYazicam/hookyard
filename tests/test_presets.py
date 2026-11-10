from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest
from fastapi.testclient import TestClient

from hookyard.app import create_app
from hookyard.cli import build_parser
from hookyard.presets import ReplayPreset, load_presets
from hookyard.signatures import (
    sign_github,
    sign_hmac,
    sign_replay,
    sign_slack,
    sign_stripe,
    verify_github,
    verify_hmac,
    verify_slack,
    verify_stripe,
)


def test_sign_helpers_round_trip() -> None:
    body = b'{"ok":true}'

    github = sign_github(body, "gh-secret")
    assert verify_github(body, github["X-Hub-Signature-256"], "gh-secret")

    stripe = sign_stripe(body, "whsec_test")
    assert verify_stripe(body, stripe["Stripe-Signature"], "whsec_test")

    slack = sign_slack(body, "slack-secret")
    assert verify_slack(
        body,
        slack["X-Slack-Request-Timestamp"],
        slack["X-Slack-Signature"],
        "slack-secret",
    )

    generic = sign_hmac(body, "shared", "x-shopify-hmac-sha256")
    assert verify_hmac(body, generic["x-shopify-hmac-sha256"], "shared")


def test_sign_helpers_reject_missing_secrets() -> None:
    for provider in ("github", "stripe", "slack", "hmac"):
        with pytest.raises(ValueError, match="not configured"):
            sign_replay(provider, b"{}", "")
    with pytest.raises(ValueError, match="unsupported sign provider"):
        sign_replay("discord", b"{}", "key")


def test_load_presets(tmp_path) -> None:
    path = tmp_path / "presets.json"
    path.write_text(
        json.dumps(
            {
                "presets": [
                    {
                        "name": "local-stripe",
                        "target": "http://127.0.0.1:3000/webhooks/stripe",
                        "sign": "Stripe",
                    },
                    {"name": "plain", "target": "https://example.com/hook"},
                ]
            }
        ),
        encoding="utf-8",
    )
    presets = load_presets(path)
    assert presets == [
        ReplayPreset(
            name="local-stripe",
            target="http://127.0.0.1:3000/webhooks/stripe",
            sign="stripe",
        ),
        ReplayPreset(name="plain", target="https://example.com/hook", sign=None),
    ]


@pytest.mark.parametrize(
    "payload, message",
    [
        ("not json", "not valid JSON"),
        (json.dumps({}), "must contain a 'presets' list"),
        (json.dumps({"presets": [1]}), "must be an object"),
        (json.dumps({"presets": [{"target": "http://x"}]}), "needs a non-empty name"),
        (
            json.dumps({"presets": [{"name": "x", "target": "ftp://x"}]}),
            "must be an http\\(s\\) URL",
        ),
        (
            json.dumps(
                {
                    "presets": [
                        {"name": "x", "target": "http://x"},
                        {"name": "x", "target": "http://y"},
                    ]
                }
            ),
            "duplicate preset name",
        ),
        (
            json.dumps(
                {"presets": [{"name": "x", "target": "http://x", "sign": "discord"}]}
            ),
            "sign must be one of",
        ),
    ],
)
def test_load_presets_rejects_bad_files(tmp_path, payload: str, message: str) -> None:
    path = tmp_path / "presets.json"
    path.write_text(payload, encoding="utf-8")
    with pytest.raises(ValueError, match=message):
        load_presets(path)


def test_load_presets_missing_file(tmp_path) -> None:
    with pytest.raises(ValueError, match="cannot read presets file"):
        load_presets(tmp_path / "missing.json")


def test_presets_endpoint_never_returns_secrets() -> None:
    presets = [
        ReplayPreset("local", "http://127.0.0.1:3000/hook", "github"),
        ReplayPreset("plain", "http://127.0.0.1:3000/plain"),
    ]
    client = TestClient(create_app(secrets={"github": "s3cret"}, replay_presets=presets))
    assert client.get("/api/presets").json() == {
        "presets": [
            {"name": "local", "target": "http://127.0.0.1:3000/hook", "sign": "github"},
            {"name": "plain", "target": "http://127.0.0.1:3000/plain", "sign": None},
        ]
    }


class _CaptureHandler(BaseHTTPRequestHandler):
    received: list[tuple[dict[str, str], bytes]] = []

    def do_POST(self) -> None:
        length = int(self.headers.get("content-length") or 0)
        body = self.rfile.read(length)
        type(self).received.append((dict(self.headers), body))
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b'{"ok":true}')

    def log_message(self, *args: object) -> None:
        return


def _start_capture() -> tuple[ThreadingHTTPServer, list[tuple[dict[str, str], bytes]]]:
    received: list[tuple[dict[str, str], bytes]] = []
    handler = type("Capture", (_CaptureHandler,), {"received": received})
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server, received


def test_signed_preset_replaces_captured_signature() -> None:
    server, received = _start_capture()
    try:
        port = server.server_port
        presets = [
            ReplayPreset("local-stripe", f"http://127.0.0.1:{port}/stripe", "stripe"),
            ReplayPreset("plain", f"http://127.0.0.1:{port}/plain"),
        ]
        app = create_app(secrets={"stripe": "whsec_local"}, replay_presets=presets)
        client = TestClient(app)
        created = client.post(
            "/b/demo/hook",
            content=b'{"id":"evt_1"}',
            headers={
                "content-type": "application/json",
                "stripe-signature": "t=1,v1=dead",
            },
        ).json()

        result = client.post(
            f"/api/bins/demo/{created['id']}/replay",
            json={"preset": "local-stripe"},
        ).json()
        assert result["ok"] is True
        assert result["preset"] == "local-stripe"
        assert result["signed"] == "stripe"
        assert len(received) == 1
        headers, body = received[0]
        lower = {key.lower(): value for key, value in headers.items()}
        assert body == b'{"id":"evt_1"}'
        assert verify_stripe(body, lower["stripe-signature"], "whsec_local")
        assert "dead" not in lower["stripe-signature"]

        plain = client.post(
            f"/api/bins/demo/{created['id']}/replay",
            json={"preset": "plain"},
        ).json()
        assert plain["ok"] is True
        assert plain["signed"] is None
        assert len(received) == 2
        assert received[1][1] == b'{"id":"evt_1"}'
    finally:
        server.shutdown()
        server.server_close()


def test_signed_preset_fails_closed_without_secret() -> None:
    server, received = _start_capture()
    try:
        presets = [
            ReplayPreset(
                "local-github",
                f"http://127.0.0.1:{server.server_port}/hook",
                "github",
            )
        ]
        client = TestClient(create_app(replay_presets=presets))
        created = client.post("/b/demo/hook", content=b"{}").json()
        res = client.post(
            f"/api/bins/demo/{created['id']}/replay",
            json={"preset": "local-github"},
        )
        assert res.status_code == 400
        assert "github secret is not configured" in res.json()["error"]
        assert received == []
    finally:
        server.shutdown()
        server.server_close()


def test_preset_replay_rejects_bad_requests() -> None:
    client = TestClient(create_app(replay_presets=[ReplayPreset("x", "http://127.0.0.1:9/x")]))
    created = client.post("/b/demo/hook", content=b"{}").json()
    url = f"/api/bins/demo/{created['id']}/replay"
    assert client.post(url, json={"preset": "nope"}).status_code == 400
    both = client.post(url, json={"preset": "x", "target": "http://127.0.0.1:9/y"})
    assert both.status_code == 400
    assert "not both" in both.json()["error"]


def test_signed_preset_still_blocks_metadata_hosts() -> None:
    presets = [
        ReplayPreset(
            "metadata",
            "http://169.254.169.254/latest/meta-data/",
            "github",
        )
    ]
    client = TestClient(create_app(secrets={"github": "s3cret"}, replay_presets=presets))
    created = client.post("/b/demo/hook", content=b"{}").json()
    result = client.post(
        f"/api/bins/demo/{created['id']}/replay",
        json={"preset": "metadata"},
    ).json()
    assert result["ok"] is False
    assert result["status"] == 0
    assert "blocked" in result["body"]


def test_cli_replay_presets_flag() -> None:
    args = build_parser().parse_args(["--replay-presets", "presets.json"])
    assert args.replay_presets == "presets.json"
