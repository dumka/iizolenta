"""Article text extraction with a graceful fallback to the feed snippet."""

from __future__ import annotations

from typing import NamedTuple
from urllib.parse import urljoin

import trafilatura

from izolenta.config import is_http_url
from izolenta.feeds import FeedItem
from izolenta.http import Fetch, FetchError

MIN_ARTICLE_CHARS = 200


class ArticleContent(NamedTuple):
    text: str
    text_source: str  # "article" or "snippet"
    image: str | None


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


def page_image(page: bytes, base_url: str) -> str | None:
    """og:image (or similar) from page metadata, resolved against the article URL."""
    # trafilatura can raise on pathological markup; losing the image is acceptable
    try:
        metadata = trafilatura.extract_metadata(page)
    except Exception:
        return None
    image = getattr(metadata, "image", None)
    if not isinstance(image, str) or not image.strip():
        return None
    resolved = urljoin(base_url, image.strip())
    return resolved if is_http_url(resolved) else None


def article_text(item: FeedItem, fetch: Fetch, limit: int) -> ArticleContent:
    """Article text (or the feed snippet as a fallback) plus the page's preview image."""
    fallback_text = item.snippet or item.title
    try:
        page = fetch(item.url)
    except FetchError:
        return ArticleContent(fallback_text, "snippet", None)
    image = page_image(page, item.url)
    # trafilatura can raise on pathological markup; the snippet is a safe fallback
    try:
        text = extract_text(page)
    except Exception:
        text = None
    if text is None:
        return ArticleContent(fallback_text, "snippet", image)
    return ArticleContent(truncate_paragraphs(text, limit), "article", image)
