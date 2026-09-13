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
    token = args.token or None
    app = create_app(
        store=store,
        secrets=secrets,
        allow_remote_replay=args.allow_remote_replay,
        token=token,
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
