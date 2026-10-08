"""Posts from X accounts via the FxTwitter API (api.fxtwitter.com)."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from izolenta.extract import truncate_paragraphs
from izolenta.http import Fetch

API_URL = "https://api.fxtwitter.com/2/profile/{handle}/statuses?count=20"
POST_TEXT_LIMIT = 4000


class XError(Exception):
    pass


@dataclass(frozen=True)
class XPost:
    id: str
    status_id: str
    url: str
    author_handle: str
    author_name: str
    published_at: datetime
    text: str
    quote: dict[str, str] | None
    lang: str | None


def _quote(status: dict[str, Any]) -> dict[str, str] | None:
    quoted = status.get("quote")
    if not isinstance(quoted, dict) or not (quoted.get("text") or "").strip():
        return None
    author = quoted.get("author") or {}
    return {
        "author_handle": str(author.get("screen_name") or ""),
        "author_name": str(author.get("name") or ""),
        "text": quoted["text"].strip(),
    }


def _load_results(raw: bytes) -> list[Any]:
    if not raw.strip():
        return []  # 204 No Content: nothing new
    try:
        data = json.loads(raw)
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise XError(f"not JSON: {exc}") from exc
    if not isinstance(data, dict) or data.get("code") != 200:
        raise XError(f"API error: {str(data)[:200]}")
    results = data.get("results")
    if not isinstance(results, list):
        raise XError("API response has no results list")
    return results


def parse_statuses(
    handle: str, raw: bytes, now: datetime, text_limit: int = POST_TEXT_LIMIT
) -> list[XPost]:
    """Own posts of `handle`: replies to others and plain reposts are dropped,
    self-reply threads are glued onto their root post."""
    own = handle.lower()
    statuses: dict[str, dict[str, Any]] = {}
    for status in _load_results(raw):
        if not isinstance(status, dict) or status.get("type") != "status":
            continue
        status_id = str(status.get("id") or "")
        author = status.get("author") or {}
        if (
            not status_id.isdigit()
            or status.get("reposted_by")
            or str(author.get("screen_name") or "").lower() != own
            or not (status.get("text") or "").strip()
        ):
            continue
        statuses[status_id] = status

    def parent_of(status: dict[str, Any]) -> str | None:
        reply = status.get("replying_to")
        return str(reply.get("status")) if isinstance(reply, dict) else None

    roots: dict[str, list[dict[str, Any]]] = {}
    continuations: list[tuple[str, dict[str, Any]]] = []
    for status_id, status in statuses.items():
        reply = status.get("replying_to")
        if reply is None:
            roots[status_id] = []
        elif isinstance(reply, dict) and str(reply.get("screen_name") or "").lower() == own:
            continuations.append((status_id, status))
        # replies to other people are dropped

    for status_id, status in continuations:
        parent, seen = parent_of(status), {status_id}
        while parent in statuses and parent not in roots and parent not in seen:
            seen.add(parent)
            parent = parent_of(statuses[parent])
        if parent in roots:
            roots[parent].append(status)
        # a continuation whose root is not in this batch is dropped

    posts: list[XPost] = []
    for status_id, parts in roots.items():
        root = statuses[status_id]
        parts.sort(key=lambda s: s.get("created_timestamp") or 0)
        text = "\n\n".join(s["text"].strip() for s in [root, *parts])
        published = datetime.fromtimestamp(int(root.get("created_timestamp") or 0), UTC)
        posts.append(
            XPost(
                id=f"x:{status_id}",
                status_id=status_id,
                url=f"https://x.com/{handle}/status/{status_id}",
                author_handle=handle,
                author_name=str((root.get("author") or {}).get("name") or handle),
                published_at=min(published, now),
                text=truncate_paragraphs(text, text_limit).rstrip(),
                quote=_quote(root),
                lang=root.get("lang"),
            )
        )
    return posts


def fetch_posts(handle: str, fetch: Fetch, now: datetime) -> list[XPost]:
    return parse_statuses(handle, fetch(API_URL.format(handle=handle)), now)
