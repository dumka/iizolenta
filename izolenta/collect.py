"""Collect step: fetch feeds, pick new articles, write state/pending.json."""

from __future__ import annotations

import time
from collections import deque
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from izolenta.config import Config, Feed, XAccount
from izolenta.extract import article_text
from izolenta.feeds import FeedError, FeedItem, parse_feed
from izolenta.http import Fetch, FetchError
from izolenta.state import load_seen, prune_seen, save_json_atomic
from izolenta.xposts import XError, XPost, fetch_posts

FINAL_STATUSES = {"done", "skipped", "failed"}
ACCOUNT_RETRY_DELAY = 2  # seconds before retrying a failed X account


def iso_z(moment: datetime) -> str:
    return moment.strftime("%Y-%m-%dT%H:%M:%SZ")


@dataclass
class CollectResult:
    feeds_ok: int = 0
    feeds_failed: int = 0
    candidates: int = 0
    items: list[dict[str, Any]] = field(default_factory=list)
    errors: list[dict[str, str]] = field(default_factory=list)
    accounts_ok: int = 0
    accounts_failed: int = 0
    post_candidates: int = 0
    posts: list[dict[str, Any]] | None = None  # None when no X accounts are configured

    def summary(self) -> str:
        from_article = sum(1 for i in self.items if i["text_source"] == "article")
        return (
            f"feeds ok={self.feeds_ok} failed={self.feeds_failed} | "
            f"candidates={self.candidates} | selected={len(self.items)} "
            f"(article={from_article}, snippet={len(self.items) - from_article})"
        ) + self._posts_summary()

    def _posts_summary(self) -> str:
        if self.posts is None:
            return ""
        return (
            f" | posts: accounts ok={self.accounts_ok} failed={self.accounts_failed} | "
            f"candidates={self.post_candidates} | selected={len(self.posts)}"
        )


def _fetch_feed(feed: Feed, fetch: Fetch, now: datetime) -> list[FeedItem]:
    return parse_feed(feed.name, fetch(feed.url), feed.default_category, now)


def _fetch_account(account: XAccount, fetch: Fetch, now: datetime) -> list[XPost]:
    # FxTwitter sometimes answers 404 for an existing profile from cloud IPs; one retry
    try:
        return fetch_posts(account.handle, fetch, now)
    except (FetchError, XError):
        time.sleep(ACCOUNT_RETRY_DELAY)
        return fetch_posts(account.handle, fetch, now)


def _round_robin(per_feed: list[list[Any]], limit: int) -> list[Any]:
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
        account_futures = [
            pool.submit(_fetch_account, account, fetch, now) for account in config.x_accounts
        ]
        fetched: list[list[FeedItem]] = []
        for feed, future in zip(config.feeds, futures):
            try:
                fetched.append(future.result())
                result.feeds_ok += 1
            except (FetchError, FeedError) as exc:
                result.errors.append({"feed": feed.name, "error": str(exc)})
                result.feeds_failed += 1
                fetched.append([])
        fetched_posts: list[list[XPost]] = []
        for account, future in zip(config.x_accounts, account_futures):
            try:
                fetched_posts.append(future.result())
                result.accounts_ok += 1
            except (FetchError, XError) as exc:
                result.errors.append({"feed": f"@{account.handle}", "error": str(exc)})
                result.accounts_failed += 1
                fetched_posts.append([])

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
        articles = list(
            pool.map(lambda item: article_text(item, fetch, settings.article_text_limit), selected)
        )

    for item, article in zip(selected, articles):
        result.items.append(
            {
                "id": item.id,
                "url": item.url,
                "source": item.source,
                "title": item.title,
                "snippet": item.snippet,
                "text": article.text,
                "text_source": article.text_source,
                "published_at": iso_z(item.published_at),
                "image": item.image or article.image,
                "default_category": item.default_category,
            }
        )
        entry = seen.setdefault(
            item.id, {"first_seen": now.isoformat(), "status": "pending", "attempts": 0}
        )
        entry["status"] = "pending"

    if config.x_accounts:
        result.posts = _select_posts(result, fetched_posts, seen, now, settings)

    save_json_atomic(
        state_dir / "pending.json",
        {
            "generated_at": iso_z(now),
            "items": result.items,
            "posts": result.posts or [],
            "errors": result.errors,
        },
    )
    save_json_atomic(seen_path, prune_seen(seen, now, settings.seen_retention_days))
    return result


def _select_posts(
    result: CollectResult,
    fetched_posts: list[list[XPost]],
    seen: dict[str, dict[str, Any]],
    now: datetime,
    settings: Any,
) -> list[dict[str, Any]]:
    oldest_allowed = now - timedelta(hours=settings.post_max_age_hours)
    taken: set[str] = set()
    per_author: list[list[XPost]] = []
    for posts in fetched_posts:
        fresh = []
        for post in sorted(posts, key=lambda p: p.published_at, reverse=True):
            if post.id in taken:
                continue
            taken.add(post.id)
            if seen.get(post.id, {}).get("status") in FINAL_STATUSES:
                continue
            if post.published_at < oldest_allowed:
                continue
            fresh.append(post)
        per_author.append(fresh)
    result.post_candidates = sum(len(posts) for posts in per_author)

    selected = []
    for post in _round_robin(per_author, settings.max_posts_per_run):
        selected.append(
            {
                "id": post.id,
                "url": post.url,
                "author_handle": post.author_handle,
                "author_name": post.author_name,
                "published_at": iso_z(post.published_at),
                "text": post.text,
                "quote": post.quote,
                "lang": post.lang,
            }
        )
        entry = seen.setdefault(
            post.id, {"first_seen": now.isoformat(), "status": "pending", "attempts": 0}
        )
        entry["status"] = "pending"
    return selected
