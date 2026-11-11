"""kodyaz — umbrella CLI for the local tools in this package."""

from __future__ import annotations

import argparse
import json
import sys

from . import __version__
from .openapi import load_spec, operations

HELP = """
kodyaz — local developer tools

Usage:
  kodyaz <command> [args...]

Commands:
  hookyard   Run the local webhook inspector.
  mcp        Run the hookyard MCP server.
  openapi    List replay targets from an OpenAPI 3 JSON document.

Options:
  -h, --help     Show this help.
  -V, --version  Show the package version.
""".strip()


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if not args or args[0] in {"help", "-h", "--help"}:
        print(HELP)
        return 0
    if args[0] in {"-V", "--version", "version"}:
        print(f"kodyaz {__version__}")
        return 0

    command, rest = args[0], args[1:]
    if command == "hookyard":
        from .cli import main as hookyard_main

        return hookyard_main(rest)
    if command == "mcp":
        from .mcp import main as mcp_main

        return mcp_main(rest)
    if command == "openapi":
        return _openapi(rest)

    print(f"kodyaz: unknown command {command!r}", file=sys.stderr)
    print(HELP, file=sys.stderr)
    return 2


def _openapi(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(
        prog="kodyaz openapi",
        description="List replay targets and example bodies from an OpenAPI 3 JSON document.",
    )
    parser.add_argument("spec", help="path to an OpenAPI 3 JSON document")
    parser.add_argument(
        "--base-url",
        default="",
        help="override the spec servers, for example http://127.0.0.1:3000",
    )
    parser.add_argument(
        "--operation",
        default="",
        help="only show this operationId",
    )
    parser.add_argument("--json", action="store_true", help="machine-readable output")
    args = parser.parse_args(argv)

    try:
        document = load_spec(args.spec)
    except ValueError as error:
        print(f"kodyaz openapi: {error}", file=sys.stderr)
        return 2

    found = operations(document, args.base_url or None)
    if args.operation:
        found = [
            operation
            for operation in found
            if operation.operation_id == args.operation
        ]
        if not found:
            print(
                f"kodyaz openapi: no operation with id {args.operation!r}",
                file=sys.stderr,
            )
            return 1
    if not found:
        print("kodyaz openapi: no operations found", file=sys.stderr)
        return 1

    if args.json:
        print(json.dumps([operation.to_dict() for operation in found], indent=2))
        return 0

    for operation in found:
        label = f"{operation.method} {operation.path}"
        if operation.operation_id:
            label += f"  [{operation.operation_id}]"
        print(label)
        if operation.summary:
            print(f"  summary: {operation.summary}")
        print(f"  target: {operation.target or '(no absolute server URL)'}")
        if operation.body:
            print("  body:")
            for line in operation.body.splitlines():
                print(f"    {line}")
        print()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
