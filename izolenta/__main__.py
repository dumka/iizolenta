"""CLI: python -m izolenta collect"""

from __future__ import annotations

import argparse
import sys
from datetime import UTC, datetime
from pathlib import Path

from izolenta.collect import collect
from izolenta.config import ConfigError, load_config
from izolenta.http import make_fetcher
from izolenta.state import StateError

EXIT_FATAL = 2


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="izolenta")
    commands = parser.add_subparsers(dest="command", required=True)
    collect_cmd = commands.add_parser("collect", help="fetch feeds and write state/pending.json")
    collect_cmd.add_argument("--config", type=Path, default=Path("feeds.toml"))
    collect_cmd.add_argument("--state-dir", type=Path, default=Path("state"))
    args = parser.parse_args(argv)

    try:
        config = load_config(args.config)
        settings = config.settings
        fetch = make_fetcher(
            timeout=settings.http_timeout,
            user_agent=settings.user_agent,
            max_bytes=settings.max_response_bytes,
        )
        result = collect(config, args.state_dir, fetch, datetime.now(UTC))
    except (ConfigError, StateError) as exc:
        print(f"izolenta: fatal: {exc}", file=sys.stderr)
        return EXIT_FATAL

    print(result.summary())
    for error in result.errors:
        print(f"  feed error: {error['feed']}: {error['error']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
