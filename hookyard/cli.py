from __future__ import annotations

import argparse
import os
import sys

from .retention import describe_retention, prune_data_file, resolve_retention


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="hookyard",
        description="Local webhook inspector. Catch, inspect, verify, replay.",
        epilog=(
            "Commands: hookyard mcp, export, import, prune. "
            "MCP server: hookyard mcp (install with: pip install \"hookyard[mcp]\")"
        ),
    )
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=4242)
    parser.add_argument("--github-secret", default=os.environ.get("HOOKYARD_GITHUB_SECRET", ""))
    parser.add_argument("--stripe-secret", default=os.environ.get("HOOKYARD_STRIPE_SECRET", ""))
    parser.add_argument("--slack-secret", default=os.environ.get("HOOKYARD_SLACK_SECRET", ""))
    parser.add_argument("--discord-public-key", default=os.environ.get("HOOKYARD_DISCORD_PUBLIC_KEY", ""))
    parser.add_argument(
        "--hmac-secret",
        default=os.environ.get("HOOKYARD_HMAC_SECRET", ""),
        help="Verify a raw HMAC-SHA256 signature (hex or base64) on any service.",
    )
    parser.add_argument(
        "--hmac-header",
        default=os.environ.get("HOOKYARD_HMAC_HEADER", "x-signature"),
        help="Header carrying the raw HMAC signature (default: x-signature; Shopify: x-shopify-hmac-sha256).",
    )
    parser.add_argument(
        "--token",
        default=os.environ.get("HOOKYARD_TOKEN", ""),
        help="Protect the UI and /api with a bearer token (catch URLs /b/... stay public).",
    )
    parser.add_argument(
        "--allow-remote-replay",
        action="store_true",
        help="Allow replaying captured requests to public hosts. Metadata IPs stay blocked.",
    )
    parser.add_argument(
        "--data-file",
        default=os.environ.get("HOOKYARD_DATA_FILE", ""),
        help="JSON file to persist captured requests (default: memory only).",
    )
    parser.add_argument(
        "--openapi",
        default=os.environ.get("HOOKYARD_OPENAPI", ""),
        help="OpenAPI 3 JSON file used to suggest replay targets for captured requests.",
    )
    parser.add_argument(
        "--openapi-base-url",
        default=os.environ.get("HOOKYARD_OPENAPI_BASE_URL", ""),
        help="Override the OpenAPI server URL when suggesting replay targets (for example, a localhost service).",
    )
    parser.add_argument(
        "--replay-presets",
        default=os.environ.get("HOOKYARD_REPLAY_PRESETS", ""),
        help="JSON file with named replay targets and optional signing providers.",
    )
    parser.add_argument(
        "--max-bins",
        type=int,
        default=None,
        help="Keep at most N bins, removing the oldest first (or HOOKYARD_MAX_BINS).",
    )
    parser.add_argument(
        "--max-age-days",
        type=float,
        default=None,
        help="Remove bins older than N days by last capture (or HOOKYARD_MAX_AGE_DAYS).",
    )
    parser.add_argument("--version", action="store_true")
    return parser


def _retention_settings(args: argparse.Namespace) -> tuple[int | None, float | None]:
    return resolve_retention(args.max_bins, args.max_age_days)


def _bin_count(count: int) -> str:
    return f"{count} bin" if count == 1 else f"{count} bins"


def _archive_parser(command: str) -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog=f"hookyard {command}",
        description=(
            "Export one bin to a portable JSON archive."
            if command == "export"
            else "Import a portable JSON archive into the data file."
        ),
    )
    parser.add_argument(
        "--data-file",
        default=os.environ.get("HOOKYARD_DATA_FILE", ""),
        help="data file to read or write (or HOOKYARD_DATA_FILE)",
    )
    if command == "export":
        parser.add_argument("bin", help="bin id to export")
        parser.add_argument(
            "-o",
            "--output",
            required=True,
            help="path of the JSON archive to write",
        )
    else:
        parser.add_argument("archive", help="JSON archive to import")
        parser.add_argument(
            "--rename",
            action="store_true",
            help="import under a free bin name if this one already exists",
        )
    return parser


def _archive_command(command: str, argv: list[str]) -> int:
    args = _archive_parser(command).parse_args(argv)
    if not args.data_file:
        print(
            "error: a data file is required; pass --data-file or HOOKYARD_DATA_FILE",
            file=sys.stderr,
        )
        return 2

    from .archive import (
        ArchiveError,
        import_archive,
        load_archive,
        write_archive,
    )
    from .persist import JsonFileStore

    if command == "export":
        store = JsonFileStore(args.data_file)
        if args.bin not in store.bins():
            print(
                f"error: bin {args.bin!r} not found in {args.data_file}",
                file=sys.stderr,
            )
            return 1
        records = store.list(args.bin, limit=store.limit)
        try:
            write_archive(args.output, args.bin, records)
        except ArchiveError as error:
            print(f"error: {error}", file=sys.stderr)
            return 2
        print(
            f"exported {args.bin} ({len(records)} requests) -> {args.output}"
        )
        return 0

    # Validate the whole archive before opening or creating the data file.
    try:
        loaded = load_archive(args.archive)
    except ArchiveError as error:
        print(f"error: {error}", file=sys.stderr)
        return 2
    store = JsonFileStore(args.data_file)
    try:
        imported = import_archive(store, loaded, rename=args.rename)
    except (ArchiveError, ValueError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 1
    print(f"imported {imported} ({len(loaded.records)} requests)")
    return 0


def _prune_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="hookyard prune",
        description=(
            "Apply the configured retention policy to a hookyard data file."
        ),
    )
    parser.add_argument(
        "--data-file",
        default=os.environ.get("HOOKYARD_DATA_FILE", ""),
        help="data file to prune (or HOOKYARD_DATA_FILE)",
    )
    parser.add_argument(
        "--max-bins",
        type=int,
        default=None,
        help="keep at most N bins (or HOOKYARD_MAX_BINS)",
    )
    parser.add_argument(
        "--max-age-days",
        type=float,
        default=None,
        help="remove bins idle for N days (or HOOKYARD_MAX_AGE_DAYS)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="list bins that would be removed without writing",
    )
    return parser


def _prune_command(argv: list[str]) -> int:
    args = _prune_parser().parse_args(argv)
    if not args.data_file:
        print(
            "error: a data file is required; pass --data-file or HOOKYARD_DATA_FILE",
            file=sys.stderr,
        )
        return 2
    try:
        max_bins, max_age_days = _retention_settings(args)
        result = prune_data_file(
            args.data_file,
            max_bins=max_bins,
            max_age_days=max_age_days,
            dry_run=args.dry_run,
        )
    except (OSError, ValueError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 2

    if not result["configured"]:
        print("retention is not configured; nothing to prune")
        return 0

    action = "would remove" if args.dry_run else "removed"
    removed = result["bins"]
    if removed:
        print(f"{action} {_bin_count(len(removed))}: {', '.join(removed)}")
    else:
        print(f"{action} 0 bins")
    return 0


def main(argv: list[str] | None = None) -> int:
    raw = list(sys.argv[1:] if argv is None else argv)
    if raw and raw[0] == "mcp":
        from .mcp import main as mcp_main

        return mcp_main(raw[1:])
    if raw and raw[0] in {"export", "import"}:
        return _archive_command(raw[0], raw[1:])
    if raw and raw[0] == "prune":
        return _prune_command(raw[1:])

    parser = build_parser()
    args = parser.parse_args(argv)
    if args.version:
        from . import __version__

        print(__version__)
        return 0

    try:
        max_bins, max_age_days = _retention_settings(args)
    except ValueError as error:
        print(f"error: {error}", file=sys.stderr)
        return 2

    secrets = {
        k: v
        for k, v in {
            "github": args.github_secret,
            "stripe": args.stripe_secret,
            "slack": args.slack_secret,
            "discord": args.discord_public_key,
            "hmac": args.hmac_secret,
        }.items()
        if v
    }

    from .app import create_app
    from .openapi import load_spec
    from .persist import JsonFileStore
    from .presets import load_presets
    from .store import MemoryStore

    openapi_spec = None
    if args.openapi:
        try:
            openapi_spec = load_spec(args.openapi)
        except ValueError as error:
            print(f"error: {error}", file=sys.stderr)
            return 2

    replay_presets = []
    if args.replay_presets:
        try:
            replay_presets = load_presets(args.replay_presets)
        except ValueError as error:
            print(f"error: {error}", file=sys.stderr)
            return 2

    store = (
        JsonFileStore(
            args.data_file,
            max_bins=max_bins,
            max_age_days=max_age_days,
        )
        if args.data_file
        else MemoryStore(max_bins=max_bins, max_age_days=max_age_days)
    )
    token = args.token or None
    app = create_app(
        store=store,
        secrets=secrets,
        allow_remote_replay=args.allow_remote_replay,
        token=token,
        hmac_header=args.hmac_header,
        openapi_spec=openapi_spec,
        openapi_base_url=args.openapi_base_url or None,
        replay_presets=replay_presets,
    )
    try:
        import uvicorn
    except ImportError:
        print("uvicorn is required to run the server: pip install -e .  (from the hookyard clone)", file=sys.stderr)
        return 1

    print(f"hookyard  http://{args.host}:{args.port}")
    print(f"catch at  http://{args.host}:{args.port}/b/demo")
    if args.data_file:
        print(f"persist   {args.data_file}")
    if max_bins is not None or max_age_days is not None:
        print(f"retention {describe_retention(max_bins, max_age_days)}")
    if openapi_spec is not None:
        print(
            f"openapi   {args.openapi} "
            f"({len(app.state.openapi_operations)} operations)"
        )
    if replay_presets:
        print(f"presets   {args.replay_presets} ({len(replay_presets)} presets)")
    if token:
        print("ui auth   token required (Authorization: Bearer … or ?token=)")
    if args.host not in {"127.0.0.1", "localhost", "::1"}:
        print(
            "warning: bound on a public interface. "
            "Set --token so the UI cannot be read by the LAN. "
            "Replay still blocks metadata IPs.",
            file=sys.stderr,
        )
        if not token:
            print("warning: no --token; anyone who can reach this port can inspect payloads.", file=sys.stderr)
    if args.discord_public_key:
        try:
            import nacl.signing  # noqa: F401
        except ImportError:
            print(
                "warning: Discord public key set but PyNaCl is missing. "
                "Install hookyard[discord] or PINGs will not verify.",
                file=sys.stderr,
            )
    print("built by  KodYazicam  https://github.com/KodYazicam/hookyard")
    uvicorn.run(app, host=args.host, port=args.port, log_level="info")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
