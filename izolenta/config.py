"""Loading and validation of feeds.toml."""

from __future__ import annotations

import tomllib
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlsplit

CATEGORIES = ("ai", "dev", "business")


class ConfigError(Exception):
    pass


@dataclass(frozen=True)
class Feed:
    name: str
    url: str
    default_category: str


@dataclass(frozen=True)
class Settings:
    max_items_per_run: int
    max_age_hours: int
    article_text_limit: int
    http_timeout: float
    max_response_bytes: int
    seen_retention_days: int
    fetch_workers: int
    user_agent: str


@dataclass(frozen=True)
class Config:
    settings: Settings
    feeds: tuple[Feed, ...]


def is_http_url(url: object) -> bool:
    if not isinstance(url, str):
        return False
    parts = urlsplit(url)
    return parts.scheme in ("http", "https") and bool(parts.netloc)


def load_config(path: Path) -> Config:
    try:
        raw = tomllib.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, tomllib.TOMLDecodeError) as exc:
        raise ConfigError(f"cannot read config {path}: {exc}") from exc

    try:
        settings = Settings(**raw["settings"])
    except (KeyError, TypeError) as exc:
        raise ConfigError(f"invalid [settings]: {exc}") from exc

    feeds_raw = raw.get("feeds") or []
    if not feeds_raw:
        raise ConfigError("no [[feeds]] configured")

    feeds: list[Feed] = []
    seen_names: set[str] = set()
    for entry in feeds_raw:
        try:
            feed = Feed(**entry)
        except TypeError as exc:
            raise ConfigError(f"invalid feed entry {entry!r}: {exc}") from exc
        if feed.name in seen_names:
            raise ConfigError(f"duplicate feed name: {feed.name}")
        if feed.default_category not in CATEGORIES:
            raise ConfigError(
                f"feed {feed.name}: category must be one of {CATEGORIES}, "
                f"got {feed.default_category!r}"
            )
        if not is_http_url(feed.url):
            raise ConfigError(f"feed {feed.name}: url must be http(s), got {feed.url!r}")
        seen_names.add(feed.name)
        feeds.append(feed)

    return Config(settings=settings, feeds=tuple(feeds))
