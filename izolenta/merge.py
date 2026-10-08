"""Merge step: validate Claude's summaries and fold them into site/data/news.json and posts.json."""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from izolenta.collect import iso_z
from izolenta.schema import (
    PostSummary,
    Skip,
    Summary,
    ValidationError,
    validate_post,
    validate_summary,
)
from izolenta.state import StateError, load_seen, read_json_object, save_json_atomic

RETENTION_DAYS = 7
POST_RETENTION_DAYS = 3
MAX_ATTEMPTS = 3


def _news_record(item: dict[str, Any], summary: Summary) -> dict[str, Any]:
    # url, source, date and image come from the collector, never from Claude's output
    return {
        "id": item["id"],
        "url": item["url"],
        "source": item["source"],
        "published_at": item["published_at"],
        "category": summary.category,
        "importance": summary.importance,
        "title": summary.title,
        "lead": summary.lead,
        "body": list(summary.body),
        "image": item.get("image"),
    }


def _post_record(post: dict[str, Any], summary: PostSummary) -> dict[str, Any]:
    # everything except the translation comes from the collector
    return {
        "id": post["id"],
        "url": post["url"],
        "author_handle": post["author_handle"],
        "author_name": post["author_name"],
        "published_at": post["published_at"],
        "text": summary.text,
    }


@dataclass(frozen=True)
class Kind:
    key: str  # list name in pending.json and summaries.json
    label: str  # prefix for check messages
    validate: Callable[[Any], Any]
    record: Callable[[dict[str, Any], Any], dict[str, Any]]
    describe: Callable[[dict[str, Any]], str]


ARTICLES = Kind("items", "", validate_summary, _news_record, lambda item: item.get("title", ""))
POSTS = Kind(
    "posts",
    "post ",
    validate_post,
    _post_record,
    lambda post: f"@{post.get('author_handle', '')}: {post.get('text', '')[:60]}",
)


@dataclass
class KindResult:
    merged: int = 0
    skipped: int = 0
    missing: int = 0
    failed: int = 0
    invalid: list[tuple[str, list[str]]] = field(default_factory=list)
    unknown_ids: list[str] = field(default_factory=list)
    duplicate_ids: list[str] = field(default_factory=list)
    total: int = 0

    def counts(self) -> str:
        return (
            f"merged={self.merged} skipped={self.skipped} invalid={len(self.invalid)} "
            f"missing={self.missing} failed={self.failed}"
        )


@dataclass
class MergeResult(KindResult):
    nothing_to_merge: bool = False
    summaries_error: str | None = None
    posts: KindResult | None = None  # None when pending.json has no posts list

    @property
    def news_total(self) -> int:
        return self.total

    def summary(self) -> str:
        if self.nothing_to_merge:
            return "nothing to merge (no state/pending.json)"
        line = f"{self.counts()} | news total={self.total}"
        if self.posts is not None:
            line += f" | posts: {self.posts.counts()} | total={self.posts.total}"
        return line


def _load_summaries(path: Path) -> tuple[dict[str, list[Any]], str | None]:
    """Claude's output is untrusted: problems are reported, never fatal.
    A bare list means article summaries only."""
    empty: dict[str, list[Any]] = {"items": [], "posts": []}
    if not path.exists():
        return empty, f"{path.name} not found"
    try:
        data = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError) as exc:
        return empty, f"{path.name} is not valid JSON: {exc}"
    if isinstance(data, list):
        return {"items": data, "posts": []}, None
    if not isinstance(data, dict):
        return empty, f'{path.name}: expected {{"items": [...], "posts": [...]}} or a list'
    lists = {key: data.get(key) or [] for key in ("items", "posts")}
    bad = [key for key, value in lists.items() if not isinstance(value, list)]
    if bad:
        return empty, f"{path.name}: {', '.join(bad)} must be a list"
    return lists, None


def _load_pending(path: Path) -> tuple[list[dict[str, Any]], list[dict[str, Any]] | None]:
    data = read_json_object(path)
    items, posts = data.get("items"), data.get("posts")
    if not isinstance(items, list):
        raise StateError(f"{path}: 'items' must be a list")
    if posts is not None and not isinstance(posts, list):
        raise StateError(f"{path}: 'posts' must be a list")
    return items, posts


def _load_store(path: Path) -> dict[str, dict[str, Any]]:
    if not path.exists():
        return {}
    items = read_json_object(path).get("items")
    if not isinstance(items, list):
        raise StateError(f"{path}: 'items' must be a list")
    return {record["id"]: record for record in items}


@dataclass
class SummaryIndex:
    by_id: dict[str, Any] = field(default_factory=dict)
    unknown_ids: list[str] = field(default_factory=list)
    duplicate_ids: list[str] = field(default_factory=list)
    without_id: int = 0


def _index_summaries(raw_summaries: list[Any], pending_ids: set[str]) -> SummaryIndex:
    index = SummaryIndex()
    for raw in raw_summaries:
        raw_id = raw.get("id") if isinstance(raw, dict) else None
        if not isinstance(raw_id, str):
            index.without_id += 1
        elif raw_id not in pending_ids:
            index.unknown_ids.append(raw_id)
        elif raw_id in index.by_id:
            index.duplicate_ids.append(raw_id)
        else:
            index.by_id[raw_id] = raw
    return index


def _apply(
    kind: Kind,
    pending: list[dict[str, Any]],
    raw_summaries: list[Any],
    store: dict[str, dict[str, Any]],
    seen: dict[str, dict[str, Any]],
    now: datetime,
    max_attempts: int,
    result: KindResult,
) -> None:
    index = _index_summaries(raw_summaries, {entry["id"] for entry in pending})
    result.unknown_ids = index.unknown_ids
    result.duplicate_ids = index.duplicate_ids
    result.invalid.extend(("?", ["entry without a string id"]) for _ in range(index.without_id))

    for entry in pending:
        state = seen.setdefault(
            entry["id"], {"first_seen": now.isoformat(), "status": "pending", "attempts": 0}
        )
        state["attempts"] = state.get("attempts", 0) + 1
        raw = index.by_id.get(entry["id"])
        if raw is None:
            result.missing += 1
        else:
            try:
                outcome = kind.validate(raw)
            except ValidationError as exc:
                result.invalid.append((entry["id"], exc.reasons))
            else:
                if isinstance(outcome, Skip):
                    state["status"] = "skipped"
                    result.skipped += 1
                else:
                    store[entry["id"]] = kind.record(entry, outcome)
                    state["status"] = "done"
                    result.merged += 1
                continue
        if state["attempts"] >= max_attempts:
            state["status"] = "failed"
            result.failed += 1
        else:
            state["status"] = "pending"


def _kept(store: dict[str, dict[str, Any]], now: datetime, days: int) -> list[dict[str, Any]]:
    cutoff = now - timedelta(days=days)
    kept = [r for r in store.values() if datetime.fromisoformat(r["published_at"]) >= cutoff]
    kept.sort(key=lambda r: r["id"])
    kept.sort(key=lambda r: r["published_at"], reverse=True)
    return kept


def merge(
    state_dir: Path,
    news_path: Path,
    now: datetime,
    retention_days: int = RETENTION_DAYS,
    max_attempts: int = MAX_ATTEMPTS,
    posts_path: Path | None = None,
) -> MergeResult:
    state_dir, news_path = Path(state_dir), Path(news_path)
    posts_path = Path(posts_path) if posts_path else news_path.parent / "posts.json"
    pending_path = state_dir / "pending.json"
    summaries_path = state_dir / "summaries.json"
    seen_path = state_dir / "seen.json"
    result = MergeResult()

    if not pending_path.exists():
        result.nothing_to_merge = True
        return result

    # Read everything that must be intact before writing anything.
    pending_items, pending_posts = _load_pending(pending_path)
    seen = load_seen(seen_path)
    news = _load_store(news_path)
    posts = _load_store(posts_path)

    summaries, result.summaries_error = _load_summaries(summaries_path)
    _apply(ARTICLES, pending_items, summaries["items"], news, seen, now, max_attempts, result)
    if pending_posts is not None:
        result.posts = KindResult()
        _apply(POSTS, pending_posts, summaries["posts"], posts, seen, now, max_attempts, result.posts)

    kept_news = _kept(news, now, retention_days)
    result.total = len(kept_news)
    save_json_atomic(news_path, {"generated_at": iso_z(now), "items": kept_news})
    if result.posts is not None or posts_path.exists():
        kept_posts = _kept(posts, now, POST_RETENTION_DAYS)
        if result.posts is not None:
            result.posts.total = len(kept_posts)
        save_json_atomic(posts_path, {"generated_at": iso_z(now), "items": kept_posts})
    save_json_atomic(seen_path, seen)
    pending_path.unlink()
    summaries_path.unlink(missing_ok=True)
    return result


@dataclass
class CheckResult:
    nothing_to_check: bool = False
    problems: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.problems


def _check_kind(kind: Kind, pending: list[dict[str, Any]], raw_summaries: list[Any]) -> list[str]:
    problems: list[str] = []
    index = _index_summaries(raw_summaries, {entry["id"] for entry in pending})
    label = kind.label
    problems.extend(f"{label}entry without a string id" for _ in range(index.without_id))
    problems.extend(f"unknown {label}id {i} (not in pending.json)" for i in index.unknown_ids)
    problems.extend(f"duplicate {label}id {i} (only the first is used)" for i in index.duplicate_ids)
    for entry in pending:
        raw = index.by_id.get(entry["id"])
        if raw is None:
            problems.append(f"missing {label}{entry['id']}: no summary for \"{kind.describe(entry)}\"")
            continue
        try:
            kind.validate(raw)
        except ValidationError as exc:
            problems.append(f"invalid {label}{entry['id']}: {'; '.join(exc.reasons)}")
    return problems


def check(state_dir: Path) -> CheckResult:
    """Validate state/summaries.json against state/pending.json without changing anything."""
    state_dir = Path(state_dir)
    pending_path = state_dir / "pending.json"
    result = CheckResult()
    if not pending_path.exists():
        result.nothing_to_check = True
        return result

    pending_items, pending_posts = _load_pending(pending_path)
    summaries, summaries_error = _load_summaries(state_dir / "summaries.json")
    if summaries_error:
        result.problems.append(f"cannot read summaries: {summaries_error}")
    result.problems.extend(_check_kind(ARTICLES, pending_items, summaries["items"]))
    if pending_posts:
        result.problems.extend(_check_kind(POSTS, pending_posts, summaries["posts"]))
    return result
