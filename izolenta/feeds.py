"""Feed parsing and article identity."""

from __future__ import annotations

import hashlib
import html
from dataclasses import dataclass
from datetime import UTC, datetime
from html.parser import HTMLParser
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

import feedparser

from izolenta.config import is_http_url

SNIPPET_LIMIT = 1000
TRACKING_PARAMS = {"fbclid", "gclid", "ref", "ref_src", "mc_cid", "mc_eid"}


class FeedError(Exception):
    pass


@dataclass(frozen=True)
class FeedItem:
    id: str
    url: str
    source: str
    title: str
    snippet: str
    published_at: datetime
    image: str | None
    default_category: str


def canonical_url(url: str) -> str:
    parts = urlsplit(url.strip())
    host = parts.netloc.lower()
    if host.startswith("www."):
        host = host[4:]
    query = sorted(
        (key, value)
        for key, value in parse_qsl(parts.query, keep_blank_values=True)
        if not key.lower().startswith("utm_") and key.lower() not in TRACKING_PARAMS
    )
    path = parts.path or "/"
    if len(path) > 1:
        path = path.rstrip("/")
    return urlunsplit(("https", host, path, urlencode(query), ""))


def item_id(url: str) -> str:
    return hashlib.sha1(canonical_url(url).encode("utf-8")).hexdigest()[:16]


class _TextCollector(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []

    def handle_data(self, data: str) -> None:
        self.parts.append(data)


def html_to_text(value: str) -> str:
    collector = _TextCollector()
    collector.feed(value)
    collector.close()
    text = html.unescape("".join(collector.parts))
    return " ".join(text.split())


def _cap(text: str, limit: int) -> str:
    if len(text) <= limit:
        return text
    cut = text[: limit - 3]
    if " " in cut:
        cut = cut.rsplit(" ", 1)[0]
    return cut + "..."


def _published(entry, now: datetime) -> datetime:
    parsed = entry.get("published_parsed") or entry.get("updated_parsed")
    if not parsed:
        return now
    published = datetime(*parsed[:6], tzinfo=UTC)
    return min(published, now)


def _image(entry) -> str | None:
    candidates: list[str] = []
    for media in entry.get("media_content") or []:
        medium = media.get("medium")
        mime = media.get("type", "")
        if medium == "image" or mime.startswith("image/") or (not medium and not mime):
            candidates.append(media.get("url", ""))
    for thumb in entry.get("media_thumbnail") or []:
        candidates.append(thumb.get("url", ""))
    for enclosure in entry.get("enclosures") or []:
        if enclosure.get("type", "").startswith("image/"):
            candidates.append(enclosure.get("href", ""))
    return next((url for url in candidates if is_http_url(url)), None)


def parse_feed(name: str, raw: bytes, default_category: str, now: datetime) -> list[FeedItem]:
    parsed = feedparser.parse(raw)
    if not parsed.entries:
        reason = parsed.get("bozo_exception") or "no entries"
        raise FeedError(f"{name}: not a feed or empty ({reason})")

    items: list[FeedItem] = []
    for entry in parsed.entries:
        title = html_to_text(entry.get("title", ""))
        url = (entry.get("link") or "").strip()
        if not title or not is_http_url(url):
            continue
        snippet = html_to_text(entry.get("summary", ""))
        items.append(
            FeedItem(
                id=item_id(url),
                url=url,
                source=name,
                title=title,
                snippet=_cap(snippet, SNIPPET_LIMIT),
                published_at=_published(entry, now),
                image=_image(entry),
                default_category=default_category,
            )
        )
    return items
