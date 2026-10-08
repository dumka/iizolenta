"""CLI: python -m izolenta collect | check | merge"""

from __future__ import annotations

import argparse
import sys
from datetime import UTC, datetime
from pathlib import Path

from izolenta.collect import collect
from izolenta.config import ConfigError, load_config
from izolenta.http import make_fetcher
from izolenta.merge import check, merge
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


def run_check(args: argparse.Namespace) -> int:
    result = check(args.state_dir)
    if result.nothing_to_check:
        print("nothing to check (no state/pending.json)")
        return 0
    for problem in result.problems:
        print(f"  {problem}")
    print("ok: every pending item has a valid summary" if result.ok else f"{len(result.problems)} problem(s)")
    return 0 if result.ok else 1


def run_merge(args: argparse.Namespace) -> None:
    result = merge(args.state_dir, args.news, datetime.now(UTC), posts_path=args.posts)
    print(result.summary())
    if result.summaries_error:
        print(f"  summaries error: {result.summaries_error}")
    for label, kind in (("", result), ("post ", result.posts)):
        if kind is None:
            continue
        for item_id, reasons in kind.invalid:
            print(f"  invalid {label}{item_id}: {'; '.join(reasons)}")
        for item_id in kind.unknown_ids:
            print(f"  unknown {label}id ignored: {item_id}")
        for item_id in kind.duplicate_ids:
            print(f"  duplicate {label}id ignored: {item_id}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="izolenta")
    commands = parser.add_subparsers(dest="command", required=True)

    collect_cmd = commands.add_parser("collect", help="fetch feeds and write state/pending.json")
    collect_cmd.add_argument("--config", type=Path, default=Path("feeds.toml"))
    collect_cmd.add_argument("--state-dir", type=Path, default=Path("state"))
    collect_cmd.set_defaults(handler=run_collect)

    check_cmd = commands.add_parser("check", help="validate state/summaries.json without merging")
    check_cmd.add_argument("--state-dir", type=Path, default=Path("state"))
    check_cmd.set_defaults(handler=run_check)

    merge_cmd = commands.add_parser("merge", help="validate summaries and update news.json")
    merge_cmd.add_argument("--state-dir", type=Path, default=Path("state"))
    merge_cmd.add_argument("--news", type=Path, default=Path("site/data/news.json"))
    merge_cmd.add_argument("--posts", type=Path, default=Path("site/data/posts.json"))
    merge_cmd.set_defaults(handler=run_merge)

    args = parser.parse_args(argv)
    try:
        code = args.handler(args)
    except (ConfigError, StateError) as exc:
        print(f"izolenta: fatal: {exc}", file=sys.stderr)
        return EXIT_FATAL
    return code or 0


if __name__ == "__main__":
    sys.exit(main())
