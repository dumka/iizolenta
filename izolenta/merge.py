"""Merge step: validate Claude's summaries and fold them into site/data/news.json."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from izolenta.collect import iso_z
from izolenta.schema import Skip, Summary, ValidationError, validate_summary
from izolenta.state import StateError, load_seen, read_json_object, save_json_atomic

RETENTION_DAYS = 7
MAX_ATTEMPTS = 3


@dataclass
class MergeResult:
    nothing_to_merge: bool = False
    merged: int = 0
    skipped: int = 0
    missing: int = 0
    failed: int = 0
    invalid: list[tuple[str, list[str]]] = field(default_factory=list)
    unknown_ids: list[str] = field(default_factory=list)
    duplicate_ids: list[str] = field(default_factory=list)
    summaries_error: str | None = None
    news_total: int = 0

    def summary(self) -> str:
        if self.nothing_to_merge:
            return "nothing to merge (no state/pending.json)"
        return (
            f"merged={self.merged} skipped={self.skipped} invalid={len(self.invalid)} "
            f"missing={self.missing} failed={self.failed} | news total={self.news_total}"
        )


def _load_summaries(path: Path) -> tuple[list[Any], str | None]:
    """Claude's output is untrusted: problems are reported, never fatal."""
    if not path.exists():
        return [], f"{path.name} not found"
    try:
        data = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError) as exc:
        return [], f"{path.name} is not valid JSON: {exc}"
    if isinstance(data, dict):
        data = data.get("items")
    if not isinstance(data, list):
        return [], f'{path.name}: expected a list or {{"items": [...]}}'
    return data, None


def _load_news(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    items = read_json_object(path).get("items")
    if not isinstance(items, list):
        raise StateError(f"{path}: 'items' must be a list")
    return items


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


def merge(
    state_dir: Path,
    news_path: Path,
    now: datetime,
    retention_days: int = RETENTION_DAYS,
    max_attempts: int = MAX_ATTEMPTS,
) -> MergeResult:
    state_dir, news_path = Path(state_dir), Path(news_path)
    pending_path = state_dir / "pending.json"
    summaries_path = state_dir / "summaries.json"
    seen_path = state_dir / "seen.json"
    result = MergeResult()

    if not pending_path.exists():
        result.nothing_to_merge = True
        return result

    # Read everything that must be intact before writing anything.
    pending_items = read_json_object(pending_path).get("items")
    if not isinstance(pending_items, list):
        raise StateError(f"{pending_path}: 'items' must be a list")
    seen = load_seen(seen_path)
    news = {record["id"]: record for record in _load_news(news_path)}

    raw_summaries, result.summaries_error = _load_summaries(summaries_path)
    pending_ids = {item["id"] for item in pending_items}
    by_id: dict[str, Any] = {}
    for raw in raw_summaries:
        raw_id = raw.get("id") if isinstance(raw, dict) else None
        if not isinstance(raw_id, str):
            result.invalid.append(("?", ["entry without a string id"]))
        elif raw_id not in pending_ids:
            result.unknown_ids.append(raw_id)
        elif raw_id in by_id:
            result.duplicate_ids.append(raw_id)
        else:
            by_id[raw_id] = raw

    for item in pending_items:
        entry = seen.setdefault(
            item["id"], {"first_seen": now.isoformat(), "status": "pending", "attempts": 0}
        )
        entry["attempts"] = entry.get("attempts", 0) + 1
        raw = by_id.get(item["id"])
        if raw is None:
            result.missing += 1
        else:
            try:
                outcome = validate_summary(raw)
            except ValidationError as exc:
                result.invalid.append((item["id"], exc.reasons))
            else:
                if isinstance(outcome, Skip):
                    entry["status"] = "skipped"
                    result.skipped += 1
                else:
                    news[item["id"]] = _news_record(item, outcome)
                    entry["status"] = "done"
                    result.merged += 1
                continue
        if entry["attempts"] >= max_attempts:
            entry["status"] = "failed"
            result.failed += 1
        else:
            entry["status"] = "pending"

    cutoff = now - timedelta(days=retention_days)
    kept = [r for r in news.values() if datetime.fromisoformat(r["published_at"]) >= cutoff]
    kept.sort(key=lambda r: r["id"])
    kept.sort(key=lambda r: r["published_at"], reverse=True)
    result.news_total = len(kept)

    save_json_atomic(news_path, {"generated_at": iso_z(now), "items": kept})
    save_json_atomic(seen_path, seen)
    pending_path.unlink()
    summaries_path.unlink(missing_ok=True)
    return result
