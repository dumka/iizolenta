from datetime import UTC, datetime
from pathlib import Path

import pytest

from izolenta.feeds import FeedError, canonical_url, item_id, parse_feed

FIXTURES = Path(__file__).parent / "fixtures"
NOW = datetime(2026, 10, 8, 12, 0, tzinfo=UTC)


def fixture(name: str) -> bytes:
    return (FIXTURES / name).read_bytes()


def rss(items: str) -> bytes:
    return (
        '<?xml version="1.0" encoding="UTF-8"?><rss version="2.0" '
        'xmlns:media="http://search.yahoo.com/mrss/"><channel><title>T</title>'
        f"{items}</channel></rss>"
    ).encode("utf-8")


# canonical_url / item_id


def test_canonical_url_strips_tracking_params_and_fragment():
    url = "https://Example.com/post?utm_source=rss&utm_medium=feed&fbclid=x&gclid=y&ref=hn#comments"
    assert canonical_url(url) == "https://example.com/post"


def test_canonical_url_same_id_for_http_https_www_and_trailing_slash():
    variants = [
        "https://example.com/a/b",
        "http://example.com/a/b/",
        "https://www.example.com/a/b",
        "https://WWW.EXAMPLE.COM/a/b/?utm_campaign=z",
    ]
    assert len({item_id(v) for v in variants}) == 1


def test_canonical_url_keeps_meaningful_query_params():
    assert item_id("https://example.com/item?id=123") != item_id("https://example.com/item?id=456")
    assert canonical_url("https://example.com/item?b=2&a=1") == "https://example.com/item?a=1&b=2"


def test_canonical_url_keeps_root_path():
    assert canonical_url("https://example.com/") == "https://example.com/"


# parse_feed


def test_parse_rss_extracts_fields_and_images():
    items = parse_feed("Example Tech", fixture("rss_basic.xml"), "ai", NOW)
    assert [i.title for i in items] == [
        "OpenAI ships GPT-7 & new API",
        "Startup raises $50M for AI agents",
        "Rust 2.0 released",
    ]
    first = items[0]
    assert first.source == "Example Tech"
    assert first.default_category == "ai"
    assert first.url.startswith("https://tech.example.com/2026/10/08/gpt-7/")
    assert first.id == item_id("https://tech.example.com/2026/10/08/gpt-7/")
    assert first.published_at == datetime(2026, 10, 8, 10, 0, tzinfo=UTC)
    assert first.image == "https://cdn.example.com/gpt7.jpg"
    assert items[1].image == "https://cdn.example.com/funding.png"
    assert items[2].image is None


def test_parse_atom_entry_without_date_gets_now():
    items = parse_feed("Example Blog", fixture("atom_basic.xml"), "dev", NOW)
    assert len(items) == 2
    assert items[0].title == "Notes on «LLM» evaluation"
    assert items[0].published_at == datetime(2026, 10, 8, 11, 0, tzinfo=UTC)
    assert items[1].published_at == NOW


def test_future_date_is_clamped_to_now():
    raw = rss(
        "<item><title>From the future</title><link>https://x.example/f</link>"
        "<pubDate>Sat, 10 Oct 2026 10:00:00 +0000</pubDate></item>"
    )
    [item] = parse_feed("X", raw, "ai", NOW)
    assert item.published_at == NOW


def test_published_date_with_offset_is_normalized_to_utc():
    raw = rss(
        "<item><title>Offset</title><link>https://x.example/o</link>"
        "<pubDate>Thu, 08 Oct 2026 13:00:00 +0300</pubDate></item>"
    )
    [item] = parse_feed("X", raw, "ai", NOW)
    assert item.published_at == datetime(2026, 10, 8, 10, 0, tzinfo=UTC)


def test_entry_without_link_or_title_is_skipped():
    raw = rss(
        "<item><title>No link</title></item>"
        "<item><link>https://x.example/no-title</link></item>"
        "<item><title>   </title><link>https://x.example/blank-title</link></item>"
        "<item><title>Good</title><link>https://x.example/good</link></item>"
    )
    items = parse_feed("X", raw, "ai", NOW)
    assert [i.title for i in items] == ["Good"]


def test_javascript_link_and_image_are_rejected():
    raw = rss(
        "<item><title>Evil link</title><link>javascript:alert(1)</link></item>"
        "<item><title>Evil image</title><link>https://x.example/ok</link>"
        '<media:content url="javascript:alert(2)" medium="image"/></item>'
    )
    items = parse_feed("X", raw, "ai", NOW)
    assert [i.title for i in items] == ["Evil image"]
    assert items[0].image is None


def test_html_in_title_and_snippet_is_stripped_and_unescaped():
    [first, *_] = parse_feed("Example Tech", fixture("rss_basic.xml"), "ai", NOW)
    assert first.title == "OpenAI ships GPT-7 & new API"
    assert first.snippet == "The new model is faster and cheaper."


def test_long_snippet_is_capped():
    long_text = "word " * 600
    raw = rss(
        f"<item><title>Long</title><link>https://x.example/l</link>"
        f"<description>{long_text}</description></item>"
    )
    [item] = parse_feed("X", raw, "ai", NOW)
    assert len(item.snippet) <= 1000


def test_bozo_feed_with_entries_is_parsed():
    items = parse_feed("Broken", fixture("rss_bozo.xml"), "dev", NOW)
    assert [i.title for i in items] == ["Still readable item"]


def test_html_page_instead_of_feed_raises_feed_error():
    with pytest.raises(FeedError):
        parse_feed("Cloudflare", fixture("not_a_feed.html"), "ai", NOW)


def test_author_parsed_when_present():
    raw = rss(
        "<item><title>With author</title><link>https://a.example/1</link>"
        "<dc:creator xmlns:dc='http://purl.org/dc/elements/1.1/'>ivanov</dc:creator></item>"
        "<item><title>Without author</title><link>https://a.example/2</link></item>"
    )
    with_author, without_author = parse_feed("A", raw, "ai", NOW)
    assert (with_author.author, without_author.author) == ("ivanov", None)
