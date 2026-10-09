"""Merge step: validate Claude's summaries and fold them into site/data/news.json, posts.json, hn.json;
record what happened to every collected material in status.json."""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from izolenta.collect import iso_z
from izolenta.hn import ERROR_SOURCE as HN_SOURCE
from izolenta.schema import (
    DiscussionSummary,
    HabrSummary,
    PostSummary,
    Skip,
    Summary,
    ValidationError,
    validate_discussion,
    validate_habr,
    validate_post,
    validate_summary,
)
from izolenta.state import StateError, load_seen, read_json_object, save_json_atomic

RETENTION_DAYS = 7
POST_RETENTION_DAYS = 3
DISCUSSION_RETENTION_DAYS = 3
HABR_RETENTION_DAYS = 7
MAX_ATTEMPTS = 3
STATUS_HOURS = 48
PREVIEW_CHARS = 120


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


def _discussion_record(discussion: dict[str, Any], summary: DiscussionSummary) -> dict[str, Any]:
    # links and counters come from the collector; Claude writes only the title and the summary
    return {
        "id": discussion["id"],
        "hn_url": discussion["hn_url"],
        "url": discussion.get("url"),
        "points": discussion["points"],
        "comments": discussion["comments"],
        "published_at": discussion["published_at"],
        "title": summary.title,
        "summary": summary.summary,
    }


def _habr_record(article: dict[str, Any], summary: HabrSummary) -> dict[str, Any]:
    # link, hub, author and date come from the collector; Claude writes only the title and the retelling
    return {
        "id": article["id"],
        "url": article["url"],
        "source": article["source"],
        "author": article.get("author"),
        "published_at": article["published_at"],
        "title": summary.title,
        "summary": summary.summary,
    }


def _article_material(item: dict[str, Any]) -> dict[str, Any]:
    return {"source": item.get("source"), "title": item.get("title"), "url": item.get("url"),
            "text_source": item.get("text_source")}


def _post_material(post: dict[str, Any]) -> dict[str, Any]:
    preview = " ".join(str(post.get("text") or "").split())[:PREVIEW_CHARS]
    return {"source": f"@{post.get('author_handle', '')}", "title": preview, "url": post.get("url"),
            "text_source": None}


def _discussion_material(discussion: dict[str, Any]) -> dict[str, Any]:
    return {"source": HN_SOURCE, "title": discussion.get("title"), "url": discussion.get("hn_url"),
            "text_source": None}


@dataclass(frozen=True)
class Kind:
    key: str  # list name in pending.json and summaries.json
    label: str  # prefix for check messages
    validate: Callable[[Any], Any]
    record: Callable[[dict[str, Any], Any], dict[str, Any]]
    describe: Callable[[dict[str, Any]], str]
    name: str  # material kind on the status page
    material: Callable[[dict[str, Any]], dict[str, Any]]  # source, original title and link for the status page


ARTICLES = Kind(
    "items", "", validate_summary, _news_record, lambda item: item.get("title", ""), "article", _article_material
)
POSTS = Kind(
    "posts",
    "post ",
    validate_post,
    _post_record,
    lambda post: f"@{post.get('author_handle', '')}: {post.get('text', '')[:60]}",
    "post",
    _post_material,
)
DISCUSSIONS = Kind(
    "discussions",
    "discussion ",
    validate_discussion,
    _discussion_record,
    lambda discussion: discussion.get("title", ""),
    "discussion",
    _discussion_material,
)
HABR = Kind(
    "habr",
    "habr ",
    validate_habr,
    _habr_record,
    lambda article: article.get("title", ""),
    "habr",
    _article_material,
)
OPTIONAL_KINDS = (POSTS, DISCUSSIONS, HABR)


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
    # (id, outcome, reason, attempts); outcome: published | skipped | invalid | missing | failed
    outcomes: list[tuple[str, str, str | None, int]] = field(default_factory=list)

    def count_map(self) -> dict[str, int]:
        return {"merged": self.merged, "skipped": self.skipped, "invalid": len(self.invalid),
                "missing": self.missing, "failed": self.failed}

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
    discussions: KindResult | None = None  # None when pending.json has no discussions list
    habr: KindResult | None = None  # None when pending.json has no habr list

    @property
    def news_total(self) -> int:
        return self.total

    def summary(self) -> str:
        if self.nothing_to_merge:
            return "nothing to merge (no state/pending.json)"
        line = f"{self.counts()} | news total={self.total}"
        if self.posts is not None:
            line += f" | posts: {self.posts.counts()} | total={self.posts.total}"
        if self.discussions is not None:
            line += f" | hn: {self.discussions.counts()} | total={self.discussions.total}"
        if self.habr is not None:
            line += f" | habr: {self.habr.counts()} | total={self.habr.total}"
        return line


SUMMARY_KEYS = ("items", "posts", "discussions", "habr")


def _summary_files(state_dir: Path) -> list[Path]:
    """summaries.json plus parts summaries.<n>.json (big runs are written in portions)."""
    main = state_dir / "summaries.json"
    parts = sorted(
        (p for p in state_dir.glob("summaries.*.json") if p.name != main.name),
        key=lambda p: (len(p.name), p.name),
    )
    return ([main] if main.exists() else []) + parts


def _load_summaries(state_dir: Path) -> tuple[dict[str, list[Any]], str | None]:
    """All summary files combined; problems with any file are reported, never fatal."""
    combined: dict[str, list[Any]] = {key: [] for key in SUMMARY_KEYS}
    files = _summary_files(state_dir)
    if not files:
        return combined, "summaries.json not found"
    errors = []
    for path in files:
        lists, error = _load_summary_file(path)
        if error:
            errors.append(error)
        for key in SUMMARY_KEYS:
            combined[key].extend(lists[key])
    return combined, "; ".join(errors) or None


def _load_summary_file(path: Path) -> tuple[dict[str, list[Any]], str | None]:
    """Claude's output is untrusted: problems are reported, never fatal.
    A bare list means article summaries only."""
    empty: dict[str, list[Any]] = {key: [] for key in SUMMARY_KEYS}
    try:
        data = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError) as exc:
        return empty, f"{path.name} is not valid JSON: {exc}"
    if isinstance(data, list):
        return {**empty, "items": data}, None
    if not isinstance(data, dict):
        return empty, f'{path.name}: expected {{"items": [...], "posts": [...]}} or a list'
    lists = {key: data.get(key) or [] for key in SUMMARY_KEYS}
    bad = [key for key, value in lists.items() if not isinstance(value, list)]
    if bad:
        return empty, f"{path.name}: {', '.join(bad)} must be a list"
    return lists, None


def _load_pending(path: Path) -> dict[str, list[dict[str, Any]] | None]:
    return _pending_lists(read_json_object(path), path)


def _pending_lists(data: dict[str, Any], path: Path) -> dict[str, list[dict[str, Any]] | None]:
    """Lists of pending.json by key; optional kinds are None when absent."""
    lists: dict[str, list[dict[str, Any]] | None] = {}
    for key in SUMMARY_KEYS:
        value = data.get(key)
        if value is None and key != "items":
            lists[key] = None
        elif not isinstance(value, list):
            raise StateError(f"{path}: '{key}' must be a list")
        else:
            lists[key] = value
    return lists


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
        state["attempts"] = attempts = state.get("attempts", 0) + 1
        raw = index.by_id.get(entry["id"])
        if raw is None:
            result.missing += 1
            problem, reason = "missing", "нет выжимки"
        else:
            try:
                outcome = kind.validate(raw)
            except ValidationError as exc:
                result.invalid.append((entry["id"], exc.reasons))
                problem, reason = "invalid", "; ".join(exc.reasons)
            else:
                if isinstance(outcome, Skip):
                    state["status"] = "skipped"
                    result.skipped += 1
                    result.outcomes.append((entry["id"], "skipped", outcome.reason, attempts))
                else:
                    store[entry["id"]] = kind.record(entry, outcome)
                    state["status"] = "done"
                    result.merged += 1
                    result.outcomes.append((entry["id"], "published", None, attempts))
                continue
        if attempts >= max_attempts:
            state["status"] = "failed"
            result.failed += 1
            result.outcomes.append((entry["id"], "failed", reason, attempts))
        else:
            state["status"] = "pending"
            result.outcomes.append((entry["id"], problem, reason, attempts))


def _kept(store: dict[str, dict[str, Any]], now: datetime, days: int) -> list[dict[str, Any]]:
    cutoff = now - timedelta(days=days)
    kept = [r for r in store.values() if datetime.fromisoformat(r["published_at"]) >= cutoff]
    kept.sort(key=lambda r: r["id"])
    kept.sort(key=lambda r: r["published_at"], reverse=True)
    return kept


def _is_recent(moment: Any, since: datetime) -> bool:
    try:
        return datetime.fromisoformat(moment) >= since
    except (TypeError, ValueError):
        return False


def _load_status(path: Path) -> dict[str, list[dict[str, Any]]]:
    """status.json only feeds the hidden status page: a broken file is started afresh, never fatal."""
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        data = {}
    if not isinstance(data, dict):
        data = {}
    lists = {}
    for key in ("runs", "materials"):
        value = data.get(key)
        lists[key] = [entry for entry in value if isinstance(entry, dict)] if isinstance(value, list) else []
    return lists


def _update_status(
    path: Path,
    pending_data: dict[str, Any],
    pending: dict[str, list[dict[str, Any]] | None],
    result: MergeResult,
    now: datetime,
) -> None:
    status = _load_status(path)
    since = now - timedelta(hours=STATUS_HOURS)
    collected_at = pending_data.get("generated_at")
    stats = pending_data.get("stats")
    sources = stats.get("sources") if isinstance(stats, dict) else None
    kinds = [(ARTICLES, result)] + [(kind, getattr(result, kind.key)) for kind in OPTIONAL_KINDS]
    run = {
        "collected_at": collected_at,
        "merged_at": iso_z(now),
        "sources": sources if isinstance(sources, list) else [],
        "result": {kind.key: kind_result.count_map() if kind_result else None for kind, kind_result in kinds},
    }

    materials = {m["id"]: m for m in status["materials"] if isinstance(m.get("id"), str)}
    for kind, kind_result in kinds:
        if kind_result is None:
            continue
        entries = {entry["id"]: entry for entry in pending[kind.key] or []}
        for item_id, outcome, reason, attempts in kind_result.outcomes:
            entry = entries[item_id]
            previous = materials.get(item_id, {})
            materials[item_id] = {
                "id": item_id,
                "kind": kind.name,
                **kind.material(entry),
                "published_at": entry.get("published_at"),
                "collected_at": previous.get("collected_at") or collected_at,
                "processed_at": iso_z(now),
                "outcome": outcome,
                "reason": reason,
                "attempts": attempts,
            }

    runs = [run] + [r for r in status["runs"] if _is_recent(r.get("merged_at"), since)]
    kept = [m for m in materials.values() if _is_recent(m.get("processed_at"), since)]
    kept.sort(key=lambda m: str(m.get("published_at") or ""), reverse=True)
    kept.sort(key=lambda m: str(m.get("processed_at") or ""), reverse=True)
    save_json_atomic(path, {"generated_at": iso_z(now), "runs": runs, "materials": kept})


def merge(
    state_dir: Path,
    news_path: Path,
    now: datetime,
    retention_days: int = RETENTION_DAYS,
    max_attempts: int = MAX_ATTEMPTS,
    posts_path: Path | None = None,
    hn_path: Path | None = None,
    status_path: Path | None = None,
    habr_path: Path | None = None,
) -> MergeResult:
    state_dir, news_path = Path(state_dir), Path(news_path)
    store_paths = {
        POSTS.key: Path(posts_path) if posts_path else news_path.parent / "posts.json",
        DISCUSSIONS.key: Path(hn_path) if hn_path else news_path.parent / "hn.json",
        HABR.key: Path(habr_path) if habr_path else news_path.parent / "habr.json",
    }
    retention = {
        POSTS.key: POST_RETENTION_DAYS,
        DISCUSSIONS.key: DISCUSSION_RETENTION_DAYS,
        HABR.key: HABR_RETENTION_DAYS,
    }
    pending_path = state_dir / "pending.json"
    seen_path = state_dir / "seen.json"
    result = MergeResult()

    if not pending_path.exists():
        result.nothing_to_merge = True
        return result

    # Read everything that must be intact before writing anything.
    pending_data = read_json_object(pending_path)
    pending = _pending_lists(pending_data, pending_path)
    seen = load_seen(seen_path)
    news = _load_store(news_path)
    stores = {kind.key: _load_store(store_paths[kind.key]) for kind in OPTIONAL_KINDS}

    summaries, result.summaries_error = _load_summaries(state_dir)
    _apply(ARTICLES, pending["items"], summaries["items"], news, seen, now, max_attempts, result)
    for kind in OPTIONAL_KINDS:
        if pending[kind.key] is not None:
            kind_result = KindResult()
            setattr(result, kind.key, kind_result)
            _apply(kind, pending[kind.key], summaries[kind.key], stores[kind.key], seen, now, max_attempts, kind_result)

    kept_news = _kept(news, now, retention_days)
    result.total = len(kept_news)
    save_json_atomic(news_path, {"generated_at": iso_z(now), "items": kept_news})
    for kind in OPTIONAL_KINDS:
        kind_result = getattr(result, kind.key)
        path = store_paths[kind.key]
        if kind_result is None and not path.exists():
            continue
        kept = _kept(stores[kind.key], now, retention[kind.key])
        if kind_result is not None:
            kind_result.total = len(kept)
        save_json_atomic(path, {"generated_at": iso_z(now), "items": kept})
    status = Path(status_path) if status_path else news_path.parent / "status.json"
    _update_status(status, pending_data, pending, result, now)
    save_json_atomic(seen_path, seen)
    pending_path.unlink()
    for path in _summary_files(state_dir):
        path.unlink(missing_ok=True)
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

    pending = _load_pending(pending_path)
    summaries, summaries_error = _load_summaries(state_dir)
    if summaries_error:
        result.problems.append(f"cannot read summaries: {summaries_error}")
    result.problems.extend(_check_kind(ARTICLES, pending["items"], summaries["items"]))
    for kind in OPTIONAL_KINDS:
        if pending[kind.key]:
            result.problems.extend(_check_kind(kind, pending[kind.key], summaries[kind.key]))
    return result
