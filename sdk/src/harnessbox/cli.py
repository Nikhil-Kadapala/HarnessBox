"""CLI entry point for HarnessBox server.

Usage:
    harnessbox serve [--port PORT] [--db PATH]

Environment variables:
    HARNESSBOX_PORT     Server port (default: 8000)
    HARNESSBOX_DB_PATH  SQLite database path (default: ~/.harnessbox/sessions.db)
    HARNESSBOX_STORAGE  Storage backend: "sqlite" or "memory" (default: sqlite)
"""

from __future__ import annotations

import argparse
import os
import sys


def main() -> None:  # noqa: D103
    """CLI entry point."""
    parser = argparse.ArgumentParser(
        prog="harnessbox",
        description="HarnessBox — run AI coding agents in secure sandboxes",
    )
    subparsers = parser.add_subparsers(dest="command")

    serve_parser = subparsers.add_parser("serve", help="Start the HarnessBox server")
    serve_parser.add_argument(
        "--port",
        type=int,
        default=int(os.environ.get("HARNESSBOX_PORT", "8000")),
        help="Port to listen on (default: 8000, env: HARNESSBOX_PORT)",
    )
    serve_parser.add_argument(
        "--db",
        type=str,
        default=os.environ.get("HARNESSBOX_DB_PATH"),
        help="SQLite database path (default: ~/.harnessbox/sessions.db, env: HARNESSBOX_DB_PATH)",
    )
    serve_parser.add_argument(
        "--storage",
        type=str,
        default=os.environ.get("HARNESSBOX_STORAGE", "sqlite"),
        choices=["sqlite", "memory"],
        help="Storage backend (default: sqlite, env: HARNESSBOX_STORAGE)",
    )
    serve_parser.add_argument(
        "--host",
        type=str,
        default="0.0.0.0",
        help="Host to bind to (default: 0.0.0.0)",
    )

    args = parser.parse_args()

    if args.command is None:
        parser.print_help()
        sys.exit(1)

    if args.command == "serve":
        _serve(args)


def _serve(args: argparse.Namespace) -> None:
    try:
        import uvicorn
    except ImportError:
        print(
            "Server dependencies not installed. Run: pip install harnessbox[server]",
            file=sys.stderr,
        )
        sys.exit(1)

    storage_arg: str | None = args.storage

    print(f"Starting HarnessBox server on {args.host}:{args.port}")
    print(f"Storage: {storage_arg}")
    if storage_arg == "sqlite":
        from pathlib import Path

        db_path = args.db or str(Path.home() / ".harnessbox" / "sessions.db")
        print(f"Database: {db_path}")

    os.environ.setdefault("HARNESSBOX_STORAGE", storage_arg or "sqlite")
    if args.db:
        os.environ.setdefault("HARNESSBOX_DB_PATH", args.db)

    uvicorn.run(
        "harnessbox.server:create_app",
        factory=True,
        host=args.host,
        port=args.port,
        log_level="info",
    )


if __name__ == "__main__":
    main()
