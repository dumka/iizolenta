"""Collect step: fetch feeds, pick new articles, write state/pending.json."""

from __future__ import annotations

from collections import deque
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from izolenta.config import Config, Feed
from izolenta.extract import article_text
from izolenta.feeds import FeedError, FeedItem, parse_feed
from izolenta.http import Fetch, FetchError
from izolenta.state import load_seen, prune_seen, save_json_atomic

FINAL_STATUSES = {"done", "skipped", "failed"}


def iso_z(moment: datetime) -> str:
    return moment.strftime("%Y-%m-%dT%H:%M:%SZ")


@dataclass
class CollectResult:
    feeds_ok: int = 0
    feeds_failed: int = 0
    candidates: int = 0
    items: list[dict[str, Any]] = field(default_factory=list)
    errors: list[dict[str, str]] = field(default_factory=list)

    def summary(self) -> str:
        from_article = sum(1 for i in self.items if i["text_source"] == "article")
        return (
            f"feeds ok={self.feeds_ok} failed={self.feeds_failed} | "
            f"candidates={self.candidates} | selected={len(self.items)} "
            f"(article={from_article}, snippet={len(self.items) - from_article})"
        )


def _fetch_feed(feed: Feed, fetch: Fetch, now: datetime) -> list[FeedItem]:
    return parse_feed(feed.name, fetch(feed.url), feed.default_category, now)


def _round_robin(per_feed: list[list[FeedItem]], limit: int) -> list[FeedItem]:
    queues = [deque(items) for items in per_feed if items]
    picked: list[FeedItem] = []
    while queues and len(picked) < limit:
        for queue in list(queues):
            if len(picked) >= limit:
                break
            picked.append(queue.popleft())
            if not queue:
                queues.remove(queue)
    return picked


def collect(config: Config, state_dir: Path, fetch: Fetch, now: datetime) -> CollectResult:
    settings = config.settings
    state_dir = Path(state_dir)
    seen_path = state_dir / "seen.json"
    seen = load_seen(seen_path)  # fail fast on corrupted state, before any network work

    result = CollectResult()
    with ThreadPoolExecutor(max_workers=settings.fetch_workers) as pool:
        futures = [pool.submit(_fetch_feed, feed, fetch, now) for feed in config.feeds]
        fetched: list[list[FeedItem]] = []
        for feed, future in zip(config.feeds, futures):
            try:
                fetched.append(future.result())
                result.feeds_ok += 1
            except (FetchError, FeedError) as exc:
                result.errors.append({"feed": feed.name, "error": str(exc)})
                result.feeds_failed += 1
                fetched.append([])

    oldest_allowed = now - timedelta(hours=settings.max_age_hours)
    taken_ids: set[str] = set()
    per_feed: list[list[FeedItem]] = []
    for items in fetched:
        fresh: list[FeedItem] = []
        for item in sorted(items, key=lambda i: i.published_at, reverse=True):
            if item.id in taken_ids:
                continue
            taken_ids.add(item.id)
            if seen.get(item.id, {}).get("status") in FINAL_STATUSES:
                continue
            if item.published_at < oldest_allowed:
                continue
            fresh.append(item)
        per_feed.append(fresh)
    result.candidates = sum(len(items) for items in per_feed)

    selected = _round_robin(per_feed, settings.max_items_per_run)
    with ThreadPoolExecutor(max_workers=settings.fetch_workers) as pool:
        texts = list(
            pool.map(lambda item: article_text(item, fetch, settings.article_text_limit), selected)
        )

    for item, (text, text_source) in zip(selected, texts):
        result.items.append(
            {
                "id": item.id,
                "url": item.url,
                "source": item.source,
                "title": item.title,
                "snippet": item.snippet,
                "text": text,
                "text_source": text_source,
                "published_at": iso_z(item.published_at),
                "image": item.image,
                "default_category": item.default_category,
            }
        )
        entry = seen.setdefault(
            item.id, {"first_seen": now.isoformat(), "status": "pending", "attempts": 0}
        )
        entry["status"] = "pending"

    save_json_atomic(
        state_dir / "pending.json",
        {"generated_at": iso_z(now), "items": result.items, "errors": result.errors},
    )
    save_json_atomic(seen_path, prune_seen(seen, now, settings.seen_retention_days))
    return result
