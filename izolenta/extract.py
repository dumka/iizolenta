"""Article text extraction with a graceful fallback to the feed snippet."""

from __future__ import annotations

import trafilatura

from izolenta.feeds import FeedItem
from izolenta.http import Fetch, FetchError

MIN_ARTICLE_CHARS = 200


def extract_text(page: bytes) -> str | None:
    text = trafilatura.extract(page, include_comments=False, include_tables=False)
    if not text or len(text) < MIN_ARTICLE_CHARS:
        return None
    return text


def truncate_paragraphs(text: str, limit: int) -> str:
    if len(text) <= limit:
        return text
    kept: list[str] = []
    size = 0
    for paragraph in text.split("\n"):
        extra = len(paragraph) + (1 if kept else 0)
        if size + extra > limit:
            break
        kept.append(paragraph)
        size += extra
    if not kept:
        return text[: limit - 3] + "..."
    return "\n".join(kept)


def article_text(item: FeedItem, fetch: Fetch, limit: int) -> tuple[str, str]:
    """Return (text, text_source) where text_source is "article" or "snippet"."""
    fallback = (item.snippet or item.title, "snippet")
    try:
        page = fetch(item.url)
    except FetchError:
        return fallback
    # trafilatura can raise on pathological markup; the snippet is a safe fallback
    try:
        text = extract_text(page)
    except Exception:
        return fallback
    if text is None:
        return fallback
    return truncate_paragraphs(text, limit), "article"
