"""Popular Hacker News discussions: front page via Algolia, top comments via the official API."""

from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

from izolenta.config import is_http_url
from izolenta.feeds import _cap, html_to_text
from izolenta.http import Fetch, FetchError

ALGOLIA_URL = "https://hn.algolia.com/api/v1/search?tags=front_page&hitsPerPage=40"
ITEM_URL = "https://hacker-news.firebaseio.com/v0/item/{id}.json"
HN_ITEM_PAGE = "https://news.ycombinator.com/item?id={id}"
COMMENT_LIMIT = 1200
COMMENTS_TOTAL_LIMIT = 8000
STORY_TEXT_LIMIT = 1500
MIN_LIVE_COMMENTS = 3
FINAL_STATUSES = {"done", "skipped", "failed"}
ERROR_SOURCE = "HN discussions"


class HNError(Exception):
    pass


@dataclass(frozen=True)
class Candidate:
    id: str
    title: str
    url: str | None
    points: int
    comments: int
    published_at: datetime
    story_text: str

    @property
    def hn_url(self) -> str:
        return HN_ITEM_PAGE.format(id=self.id)


def _json(raw: bytes) -> Any:
    try:
        return json.loads(raw)
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise HNError(f"not JSON: {exc}") from exc


def parse_front_page(raw: bytes, now: datetime) -> list[Candidate]:
    data = _json(raw)
    hits = data.get("hits") if isinstance(data, dict) else None
    if not isinstance(hits, list):
        raise HNError("Algolia response has no hits list")
    candidates = []
    for hit in hits:
        story_id = str(hit.get("objectID") or "")
        title = html_to_text(hit.get("title") or "")
        if not story_id.isdigit() or not title:
            continue
        url = hit.get("url")
        published = datetime.fromtimestamp(int(hit.get("created_at_i") or 0), UTC)
        candidates.append(
            Candidate(
                id=story_id,
                title=title,
                url=url if is_http_url(url) else None,
                points=int(hit.get("points") or 0),
                comments=int(hit.get("num_comments") or 0),
                published_at=min(published, now),
                story_text=_cap(html_to_text(hit.get("story_text") or ""), STORY_TEXT_LIMIT),
            )
        )
    return candidates


def _comment_text(fetch: Fetch, comment_id: int) -> str | None:
    try:
        comment = _json(fetch(ITEM_URL.format(id=comment_id)))
    except (FetchError, HNError):
        return None  # one missing comment does not matter
    if not isinstance(comment, dict) or comment.get("deleted") or comment.get("dead"):
        return None
    text = html_to_text(comment.get("text") or "")
    return _cap(text, COMMENT_LIMIT) if text else None


def _top_comments(fetch: Fetch, story_id: str, limit: int, pool: ThreadPoolExecutor) -> list[str]:
    story = _json(fetch(ITEM_URL.format(id=story_id)))
    kids = story.get("kids") if isinstance(story, dict) else None
    kids = [kid for kid in (kids or []) if isinstance(kid, int)][:limit]  # kids are in HN rank order
    comments: list[str] = []
    total = 0
    for text in pool.map(lambda kid: _comment_text(fetch, kid), kids):
        if text is None:
            continue
        if total + len(text) > COMMENTS_TOTAL_LIMIT:
            break
        comments.append(text)
        total += len(text)
    return comments


def collect_discussions(
    fetch: Fetch,
    seen: dict[str, dict[str, Any]],
    now: datetime,
    *,
    min_points: int,
    min_comments: int,
    max_age_hours: int,
    max_per_run: int,
    top_comments: int,
) -> tuple[list[dict[str, Any]], list[dict[str, str]]]:
    errors: list[dict[str, str]] = []
    try:
        candidates = parse_front_page(fetch(ALGOLIA_URL), now)
    except (FetchError, HNError) as exc:
        return [], [{"feed": ERROR_SOURCE, "error": str(exc)}]

    oldest = now - timedelta(hours=max_age_hours)
    eligible = [
        c
        for c in candidates
        if c.points >= min_points
        and c.comments >= min_comments
        and c.published_at >= oldest
        and seen.get(f"hn:{c.id}", {}).get("status") not in FINAL_STATUSES
    ]
    eligible.sort(key=lambda c: c.comments, reverse=True)

    selected: list[dict[str, Any]] = []
    with ThreadPoolExecutor(max_workers=8) as pool:
        for candidate in eligible[: max_per_run * 3]:
            if len(selected) >= max_per_run:
                break
            try:
                comments = _top_comments(fetch, candidate.id, top_comments, pool)
            except (FetchError, HNError) as exc:
                errors.append({"feed": ERROR_SOURCE, "error": f"story {candidate.id}: {exc}"})
                continue
            if len(comments) < MIN_LIVE_COMMENTS:
                continue
            selected.append(
                {
                    "id": f"hn:{candidate.id}",
                    "hn_url": candidate.hn_url,
                    "url": candidate.url,
                    "title": candidate.title,
                    "points": candidate.points,
                    "comments": candidate.comments,
                    "published_at": candidate.published_at.strftime("%Y-%m-%dT%H:%M:%SZ"),
                    "story_text": candidate.story_text,
                    "top_comments": comments,
                }
            )
    return selected, errors
