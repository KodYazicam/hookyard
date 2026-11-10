from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

from hookyard.app import create_app
from hookyard.cli import build_parser
from hookyard.openapi import (
    _example_from_schema,
    load_spec,
    match_operation,
    operations,
)


def spec() -> dict:
    return {
        "openapi": "3.1.0",
        "info": {"title": "Shop", "version": "1.0.0"},
        "servers": [{"url": "https://api.example.com/v1"}],
        "paths": {
            "/webhooks/stripe": {
                "post": {
                    "operationId": "stripeWebhook",
                    "summary": "Stripe events",
                    "requestBody": {
                        "content": {
                            "application/json": {
                                "schema": {"$ref": "#/components/schemas/Event"}
                            }
                        }
                    },
                }
            },
            "/webhooks/{provider}/events": {
                "post": {
                    "operationId": "providerWebhook",
                    "parameters": [
                        {
                            "name": "provider",
                            "in": "path",
                            "required": True,
                            "schema": {"type": "string", "enum": ["github", "stripe"]},
                        }
                    ],
                    "requestBody": {
                        "content": {
                            "application/json": {"example": {"hello": "world"}}
                        }
                    },
                }
            },
            "/files/{name}": {
                "post": {
                    "operationId": "uploadFile",
                    "parameters": [
                        {
                            "name": "name",
                            "in": "path",
                            "example": "a b/c",
                            "schema": {"type": "string"},
                        }
                    ],
                }
            },
            "/health": {"get": {"operationId": "health"}},
        },
        "components": {
            "schemas": {
                "Event": {
                    "type": "object",
                    "properties": {
                        "id": {"type": "string", "format": "uuid"},
                        "amount": {"type": "integer"},
                        "paid": {"type": "boolean"},
                        "tags": {"type": "array", "items": {"type": "string"}},
                        "customer": {"$ref": "#/components/schemas/Customer"},
                    },
                },
                "Customer": {
                    "type": "object",
                    "properties": {
                        "email": {"type": "string", "format": "email"}
                    },
                },
            }
        },
    }


def test_load_spec_accepts_30_and_31(tmp_path) -> None:
    path = tmp_path / "spec.json"
    path.write_text(json.dumps(spec()), encoding="utf-8")
    assert load_spec(path)["openapi"] == "3.1.0"

    doc = spec()
    doc["openapi"] = "3.0.3"
    path.write_text(json.dumps(doc), encoding="utf-8")
    assert load_spec(path)["openapi"] == "3.0.3"


@pytest.mark.parametrize(
    "payload, message",
    [
        ("not json", "not valid JSON"),
        (json.dumps({"paths": {}}), "missing 'openapi'"),
        (json.dumps({"openapi": "2.0"}), "unsupported OpenAPI version"),
        (json.dumps([]), "not an OpenAPI document"),
    ],
)
def test_load_spec_rejects_bad_documents(tmp_path, payload: str, message: str) -> None:
    path = tmp_path / "spec.json"
    path.write_text(payload, encoding="utf-8")
    with pytest.raises(ValueError, match=message):
        load_spec(path)


def test_load_spec_missing_file(tmp_path) -> None:
    with pytest.raises(ValueError, match="cannot read OpenAPI file"):
        load_spec(tmp_path / "missing.json")


def test_operations_extract_targets_and_example_bodies() -> None:
    found = operations(spec())
    by_id = {operation.operation_id: operation for operation in found}
    assert set(by_id) == {
        "stripeWebhook",
        "providerWebhook",
        "uploadFile",
        "health",
    }

    stripe = by_id["stripeWebhook"]
    assert stripe.method == "POST"
    assert stripe.target == "https://api.example.com/v1/webhooks/stripe"
    assert stripe.body is not None
    body = json.loads(stripe.body)
    assert body["id"] == "00000000-0000-4000-8000-000000000000"
    assert body["amount"] == 0
    assert body["paid"] is False
    assert body["tags"] == ["string"]
    assert body["customer"]["email"] == "user@example.com"

    assert by_id["providerWebhook"].target == (
        "https://api.example.com/v1/webhooks/github/events"
    )
    assert json.loads(by_id["providerWebhook"].body or "{}") == {"hello": "world"}
    assert by_id["uploadFile"].target == "https://api.example.com/v1/files/a%20b%2Fc"
    assert by_id["health"].target == "https://api.example.com/v1/health"


def test_operations_respect_server_precedence_and_base_url() -> None:
    doc = spec()
    doc["paths"]["/health"]["get"]["servers"] = [{"url": "http://127.0.0.1:9000"}]
    doc["paths"]["/webhooks/stripe"]["servers"] = [{"url": "/relative"}]
    found = {operation.operation_id: operation for operation in operations(doc)}
    assert found["health"].target == "http://127.0.0.1:9000/health"
    assert found["stripeWebhook"].target is None

    overridden = {
        operation.operation_id: operation
        for operation in operations(doc, "http://localhost:3000/api")
    }
    assert overridden["stripeWebhook"].target == (
        "http://localhost:3000/api/webhooks/stripe"
    )


def test_operations_expand_server_variables() -> None:
    doc = spec()
    doc["servers"] = [
        {
            "url": "https://{region}.example.com",
            "variables": {"region": {"default": "eu"}},
        }
    ]
    found = {operation.operation_id: operation for operation in operations(doc)}
    assert found["health"].target == "https://eu.example.com/health"


def test_schema_examples_handle_all_of_one_of_and_cycles() -> None:
    doc = spec()
    doc["components"]["schemas"]["Combined"] = {
        "allOf": [
            {"type": "object", "properties": {"a": {"type": "string"}}},
            {"type": "object", "properties": {"b": {"type": "integer"}}},
        ]
    }
    doc["components"]["schemas"]["Choice"] = {"oneOf": [{"type": "boolean"}]}
    doc["components"]["schemas"]["Cycle"] = {"$ref": "#/components/schemas/Cycle"}

    assert _example_from_schema({"$ref": "#/components/schemas/Combined"}, doc) == {
        "a": "string",
        "b": 0,
    }
    assert _example_from_schema({"$ref": "#/components/schemas/Choice"}, doc) is False
    assert _example_from_schema({"$ref": "#/components/schemas/Cycle"}, doc) is None


def test_match_operation_literal_templated_and_method() -> None:
    found = operations(spec())
    assert match_operation(found, "post", "/webhooks/stripe").operation_id == (
        "stripeWebhook"
    )
    assert match_operation(found, "POST", "/webhooks/stripe/").operation_id == (
        "stripeWebhook"
    )
    assert match_operation(found, "post", "/webhooks/github/events").operation_id == (
        "providerWebhook"
    )
    assert match_operation(
        found, "POST", "/webhooks/github/events?attempt=2"
    ).operation_id == ("providerWebhook")
    assert match_operation(found, "get", "/webhooks/stripe") is None
    assert match_operation(found, "post", "/webhooks/stripe/extra") is None
    assert match_operation(found, "post", "/nope") is None


def test_openapi_endpoint_matches_and_reports_misses() -> None:
    client = TestClient(create_app(openapi_spec=spec()))
    created = client.post("/b/hooks/webhooks/stripe", content=b'{"ok":true}').json()

    matched = client.get(f"/api/bins/hooks/{created['id']}/openapi").json()
    assert matched["matched"] is True
    assert matched["operation"]["operation_id"] == "stripeWebhook"
    assert matched["target"] == "https://api.example.com/v1/webhooks/stripe"

    other = client.post("/b/hooks/other", content=b"{}").json()
    miss = client.get(f"/api/bins/hooks/{other['id']}/openapi").json()
    assert miss == {"matched": False, "reason": "no matching operation"}

    assert client.get("/api/bins/hooks/nope/openapi").status_code == 404


def test_openapi_endpoint_without_spec() -> None:
    client = TestClient(create_app())
    created = client.post("/b/hooks/webhooks/stripe", content=b"{}").json()
    data = client.get(f"/api/bins/hooks/{created['id']}/openapi").json()
    assert data == {"matched": False, "reason": "no OpenAPI spec loaded"}


def test_cli_openapi_flags() -> None:
    args = build_parser().parse_args(
        ["--openapi", "spec.json", "--openapi-base-url", "http://127.0.0.1:3000"]
    )
    assert args.openapi == "spec.json"
    assert args.openapi_base_url == "http://127.0.0.1:3000"
