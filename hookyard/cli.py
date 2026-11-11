from __future__ import annotations

import argparse
import os
import sys


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="hookyard",
        description="Local webhook inspector. Catch, inspect, verify, replay.",
        epilog="MCP server: hookyard mcp (install with: pip install \"hookyard[mcp]\")",
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
    parser.add_argument("--version", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    raw = list(sys.argv[1:] if argv is None else argv)
    if raw and raw[0] == "mcp":
        from .mcp import main as mcp_main

        return mcp_main(raw[1:])

    parser = build_parser()
    args = parser.parse_args(argv)
    if args.version:
        from . import __version__

        print(__version__)
        return 0

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

    store = JsonFileStore(args.data_file) if args.data_file else MemoryStore()
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
