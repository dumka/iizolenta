"""CLI: python -m izolenta collect | merge"""

from __future__ import annotations

import argparse
import sys
from datetime import UTC, datetime
from pathlib import Path

from izolenta.collect import collect
from izolenta.config import ConfigError, load_config
from izolenta.http import make_fetcher
from izolenta.merge import merge
from izolenta.state import StateError

EXIT_FATAL = 2


def run_collect(args: argparse.Namespace) -> None:
    config = load_config(args.config)
    settings = config.settings
    fetch = make_fetcher(
        timeout=settings.http_timeout,
        user_agent=settings.user_agent,
        max_bytes=settings.max_response_bytes,
    )
    result = collect(config, args.state_dir, fetch, datetime.now(UTC))
    print(result.summary())
    for error in result.errors:
        print(f"  feed error: {error['feed']}: {error['error']}")


def run_merge(args: argparse.Namespace) -> None:
    result = merge(args.state_dir, args.news, datetime.now(UTC))
    print(result.summary())
    if result.summaries_error:
        print(f"  summaries error: {result.summaries_error}")
    for item_id, reasons in result.invalid:
        print(f"  invalid {item_id}: {'; '.join(reasons)}")
    for item_id in result.unknown_ids:
        print(f"  unknown id ignored: {item_id}")
    for item_id in result.duplicate_ids:
        print(f"  duplicate id ignored: {item_id}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="izolenta")
    commands = parser.add_subparsers(dest="command", required=True)

    collect_cmd = commands.add_parser("collect", help="fetch feeds and write state/pending.json")
    collect_cmd.add_argument("--config", type=Path, default=Path("feeds.toml"))
    collect_cmd.add_argument("--state-dir", type=Path, default=Path("state"))
    collect_cmd.set_defaults(handler=run_collect)

    merge_cmd = commands.add_parser("merge", help="validate summaries and update news.json")
    merge_cmd.add_argument("--state-dir", type=Path, default=Path("state"))
    merge_cmd.add_argument("--news", type=Path, default=Path("site/data/news.json"))
    merge_cmd.set_defaults(handler=run_merge)

    args = parser.parse_args(argv)
    try:
        args.handler(args)
    except (ConfigError, StateError) as exc:
        print(f"izolenta: fatal: {exc}", file=sys.stderr)
        return EXIT_FATAL
    return 0


if __name__ == "__main__":
    sys.exit(main())
