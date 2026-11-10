"""Turn OpenAPI 3 operations into replay target suggestions.

JSON documents only for now: hookyard has no YAML dependency, and adding one
just to read a spec would be a bigger change than this feature needs.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import quote, urlsplit, urlunsplit

HTTP_METHODS = ("get", "post", "put", "patch", "delete", "head", "options")
MAX_SCHEMA_DEPTH = 8
_PATH_PARAM_RE = re.compile(r"\{([^{}]+)\}")
_FORMAT_EXAMPLES = {
    "date": "2024-01-01",
    "date-time": "2024-01-01T00:00:00Z",
    "email": "user@example.com",
    "hostname": "example.com",
    "ipv4": "127.0.0.1",
    "uri": "https://example.com",
    "url": "https://example.com",
    "uuid": "00000000-0000-4000-8000-000000000000",
}
_TYPE_EXAMPLES: dict[str, Any] = {
    "string": "string",
    "integer": 0,
    "number": 0,
    "boolean": False,
}


@dataclass(frozen=True)
class Operation:
    method: str
    path: str
    operation_id: str
    summary: str
    target: str | None
    body: str | None
    content_type: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "method": self.method,
            "path": self.path,
            "operation_id": self.operation_id,
            "summary": self.summary,
            "target": self.target,
            "body": self.body,
            "content_type": self.content_type,
        }


def load_spec(path: str | Path) -> dict[str, Any]:
    """Read and validate an OpenAPI 3.0/3.1 JSON document."""
    file = Path(path)
    try:
        text = file.read_text(encoding="utf-8")
    except OSError as error:
        raise ValueError(f"cannot read OpenAPI file {file}: {error.strerror or error}") from error
    try:
        doc = json.loads(text)
    except json.JSONDecodeError as error:
        raise ValueError(
            f"{file} is not valid JSON: {error.msg} (line {error.lineno})"
        ) from error
    if not isinstance(doc, dict):
        raise ValueError(f"{file} is not an OpenAPI document")
    version = doc.get("openapi")
    if not isinstance(version, str):
        raise ValueError(f"{file} is not an OpenAPI 3 document (missing 'openapi')")
    if not version.startswith(("3.0", "3.1")):
        raise ValueError(
            f"unsupported OpenAPI version {version}; only 3.0 and 3.1 are supported"
        )
    return doc


def operations(doc: dict[str, Any], base_url: str | None = None) -> list[Operation]:
    """Extract operations with a replay target and an example JSON body."""
    paths = doc.get("paths")
    if not isinstance(paths, dict):
        return []
    found: list[Operation] = []
    for path, item in paths.items():
        if not isinstance(path, str) or not isinstance(item, dict):
            continue
        for method in HTTP_METHODS:
            operation = item.get(method)
            if not isinstance(operation, dict):
                continue
            body, content_type = _example_body(operation, doc)
            found.append(
                Operation(
                    method=method.upper(),
                    path=path,
                    operation_id=str(operation.get("operationId") or ""),
                    summary=str(operation.get("summary") or ""),
                    target=_target(doc, item, operation, path, base_url),
                    body=body,
                    content_type=content_type,
                )
            )
    return found


def match_operation(
    found: list[Operation], method: str, path: str
) -> Operation | None:
    """Find the first operation matching a captured method and path."""
    wanted = method.upper()
    actual = path.split("?", 1)[0]
    for operation in found:
        if operation.method != wanted:
            continue
        if _path_matches(operation.path, actual):
            return operation
    return None


def _target(
    doc: dict[str, Any],
    item: dict[str, Any],
    operation: dict[str, Any],
    path: str,
    base_url: str | None,
) -> str | None:
    filled = _fill_path(path, _path_values(doc, item, operation))
    if base_url:
        return _join(base_url, filled)
    server = _server_url(doc, item, operation)
    if not server:
        return None
    return _join(server, filled)


def _join(base: str, path: str) -> str | None:
    parts = urlsplit(base)
    if parts.scheme not in {"http", "https"} or not parts.netloc:
        return None
    base_path = parts.path.rstrip("/")
    joined = f"{base_path}/{path.lstrip('/')}"
    return urlunsplit((parts.scheme, parts.netloc, joined, "", ""))


def _server_url(
    doc: dict[str, Any], item: dict[str, Any], operation: dict[str, Any]
) -> str | None:
    for source in (
        operation.get("servers"),
        item.get("servers"),
        doc.get("servers"),
    ):
        if not isinstance(source, list) or not source:
            continue
        for server in source:
            if not isinstance(server, dict):
                continue
            url = server.get("url")
            if not isinstance(url, str) or not url:
                continue
            variables = server.get("variables")
            if isinstance(variables, dict):
                url = _PATH_PARAM_RE.sub(
                    lambda match: _server_variable(variables, match.group(1)), url
                )
            parts = urlsplit(url)
            if parts.scheme in {"http", "https"} and parts.netloc:
                return url
        return None
    return None


def _server_variable(variables: dict[str, Any], name: str) -> str:
    variable = variables.get(name)
    if isinstance(variable, dict) and variable.get("default") is not None:
        return str(variable["default"])
    return "{" + name + "}"


def _path_values(
    doc: dict[str, Any], item: dict[str, Any], operation: dict[str, Any]
) -> dict[str, Any]:
    values: dict[str, Any] = {}
    for source in (item.get("parameters"), operation.get("parameters")):
        if not isinstance(source, list):
            continue
        for parameter in source:
            parameter = _resolve(doc, parameter)
            if not isinstance(parameter, dict) or parameter.get("in") != "path":
                continue
            name = parameter.get("name")
            if not isinstance(name, str) or not name:
                continue
            value = _parameter_example(parameter)
            if value is not None:
                values[name] = value
    return values


def _parameter_example(parameter: dict[str, Any]) -> Any:
    if "example" in parameter and parameter["example"] is not None:
        return parameter["example"]
    schema = parameter.get("schema")
    if not isinstance(schema, dict):
        return None
    if schema.get("example") is not None:
        return schema["example"]
    if schema.get("default") is not None:
        return schema["default"]
    enum = schema.get("enum")
    if isinstance(enum, list) and enum:
        return enum[0]
    return _TYPE_EXAMPLES.get(str(schema.get("type")))


def _fill_path(path: str, values: dict[str, Any]) -> str:
    def replace(match: re.Match[str]) -> str:
        name = match.group(1)
        if name not in values:
            return match.group(0)
        return quote(str(values[name]), safe="")

    return _PATH_PARAM_RE.sub(replace, path)


def _path_matches(template: str, actual: str) -> bool:
    expected_segments = [seg for seg in template.strip("/").split("/") if seg]
    actual_segments = [seg for seg in actual.strip("/").split("/") if seg]
    if len(expected_segments) != len(actual_segments):
        return False
    return all(
        _segment_matches(expected, got)
        for expected, got in zip(expected_segments, actual_segments)
    )


def _segment_matches(template: str, actual: str) -> bool:
    pattern = ""
    for index, part in enumerate(_PATH_PARAM_RE.split(template)):
        if index % 2:
            pattern += "[^/]+"
        else:
            pattern += re.escape(part)
    return re.fullmatch(pattern, actual) is not None


def _example_body(
    operation: dict[str, Any], doc: dict[str, Any]
) -> tuple[str | None, str]:
    request_body = _resolve(doc, operation.get("requestBody"))
    if not isinstance(request_body, dict):
        return None, "application/json"
    content = request_body.get("content")
    if not isinstance(content, dict) or not content:
        return None, "application/json"
    content_type = (
        "application/json" if "application/json" in content else next(iter(content))
    )
    media = _resolve(doc, content.get(content_type))
    if not isinstance(media, dict):
        return None, content_type

    value: Any = None
    if "example" in media:
        value = media["example"]
    else:
        examples = media.get("examples")
        if isinstance(examples, dict):
            for entry in examples.values():
                entry = _resolve(doc, entry)
                if isinstance(entry, dict) and "value" in entry:
                    value = entry["value"]
                    break
    if value is None and "schema" in media:
        value = _example_from_schema(media["schema"], doc)
    if value is None:
        return None, content_type
    try:
        return json.dumps(value, indent=2), content_type
    except (TypeError, ValueError):
        return None, content_type


def _example_from_schema(
    schema: Any, doc: dict[str, Any], depth: int = 0, seen: set[str] | None = None
) -> Any:
    if depth > MAX_SCHEMA_DEPTH:
        return None
    if seen is None:
        seen = set()
    schema = _resolve(doc, schema, seen)
    if not isinstance(schema, dict):
        return None
    for key in ("example", "default", "const"):
        if key in schema and schema[key] is not None:
            return schema[key]
    enum = schema.get("enum")
    if isinstance(enum, list) and enum:
        return enum[0]

    all_of = schema.get("allOf")
    if isinstance(all_of, list) and all_of:
        merged: dict[str, Any] = {}
        for part in all_of:
            value = _example_from_schema(part, doc, depth + 1, seen)
            if isinstance(value, dict):
                merged.update(value)
        return merged or None
    one_of = schema.get("oneOf") or schema.get("anyOf")
    if isinstance(one_of, list) and one_of:
        return _example_from_schema(one_of[0], doc, depth + 1, seen)

    kind = schema.get("type")
    if kind == "object" or "properties" in schema:
        properties = schema.get("properties")
        if not isinstance(properties, dict):
            return {}
        return {
            name: _example_from_schema(prop, doc, depth + 1, seen)
            for name, prop in properties.items()
        }
    if kind == "array":
        item = _example_from_schema(schema.get("items"), doc, depth + 1, seen)
        return [item] if item is not None else []
    if kind == "string":
        return _FORMAT_EXAMPLES.get(str(schema.get("format")), "string")
    if kind in _TYPE_EXAMPLES:
        return _TYPE_EXAMPLES[kind]
    if kind == "null":
        return None
    return None


def _resolve(
    doc: dict[str, Any], node: Any, seen: set[str] | None = None
) -> Any:
    """Resolve a local ``#/...`` reference; external references return None."""
    if not isinstance(node, dict):
        return node
    ref = node.get("$ref")
    if not isinstance(ref, str):
        return node
    if not ref.startswith("#/"):
        return None
    if seen is not None:
        if ref in seen:
            return None
        seen.add(ref)
    target: Any = doc
    for part in ref[2:].split("/"):
        part = part.replace("~1", "/").replace("~0", "~")
        if not isinstance(target, dict) or part not in target:
            return None
        target = target[part]
    return target
