from __future__ import annotations

import argparse
import os
import sys


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="hookyard",
        description="Local webhook inspector. Catch, inspect, verify, replay.",
    )
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=4242)
    parser.add_argument("--github-secret", default=os.environ.get("HOOKYARD_GITHUB_SECRET", ""))
    parser.add_argument("--stripe-secret", default=os.environ.get("HOOKYARD_STRIPE_SECRET", ""))
    parser.add_argument("--slack-secret", default=os.environ.get("HOOKYARD_SLACK_SECRET", ""))
    parser.add_argument("--discord-public-key", default=os.environ.get("HOOKYARD_DISCORD_PUBLIC_KEY", ""))
    parser.add_argument(
        "--allow-remote-replay",
        action="store_true",
        help="Allow replaying captured requests to non-local hosts (SSRF risk).",
    )
    parser.add_argument(
        "--data-file",
        default=os.environ.get("HOOKYARD_DATA_FILE", ""),
        help="JSON file to persist captured requests (default: memory only).",
    )
    parser.add_argument("--version", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
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
        }.items()
        if v
    }

    from .app import create_app
    from .persist import JsonFileStore
    from .store import MemoryStore

    store = JsonFileStore(args.data_file) if args.data_file else MemoryStore()
    app = create_app(store=store, secrets=secrets, allow_remote_replay=args.allow_remote_replay)
    try:
        import uvicorn
    except ImportError:
        print("uvicorn is required to run the server: pip install hookyard", file=sys.stderr)
        return 1

    print(f"hookyard  http://{args.host}:{args.port}")
    print(f"catch at  http://{args.host}:{args.port}/b/demo")
    if args.data_file:
        print(f"persist   {args.data_file}")
    if args.host not in {"127.0.0.1", "localhost", "::1"}:
        print("warning: bound on a public interface; replay is still localhost-only unless --allow-remote-replay")
    print("built by  KodYazicam  https://github.com/KodYazicam/hookyard")
    uvicorn.run(app, host=args.host, port=args.port, log_level="info")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
