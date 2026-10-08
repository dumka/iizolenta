import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from izolenta.collect import collect
from izolenta.config import Config, Feed, Settings
from izolenta.feeds import item_id
from izolenta.http import FetchError
from izolenta.state import StateError

NOW = datetime(2026, 10, 8, 12, 0, tzinfo=UTC)
ARTICLE = (Path(__file__).parent / "fixtures" / "article.html").read_bytes()


def make_config(feeds, max_items=15, max_age_hours=48):
    return Config(
        settings=Settings(
            max_items_per_run=max_items,
            max_age_hours=max_age_hours,
            article_text_limit=8000,
            http_timeout=5,
            max_response_bytes=1_000_000,
            seen_retention_days=14,
            fetch_workers=4,
            user_agent="test",
        ),
        feeds=tuple(Feed(name, f"https://{name.lower()}.example/feed", "ai") for name in feeds),
    )


def rss(entries):
    """entries: list of (url, title, published datetime)."""
    items = "".join(
        f"<item><title>{title}</title><link>{url}</link>"
        f"<pubDate>{published.strftime('%a, %d %b %Y %H:%M:%S +0000')}</pubDate>"
        f"<description>Snippet for {title}</description></item>"
        for url, title, published in entries
    )
    return f'<?xml version="1.0"?><rss version="2.0"><channel><title>T</title>{items}</channel></rss>'.encode()


class FakeWeb:
    def __init__(self, pages=None):
        self.pages = dict(pages or {})
        self.requested = []

    def __call__(self, url):
        self.requested.append(url)
        page = self.pages.get(url)
        if page is None:
            raise FetchError(f"{url}: HTTP 404")
        if isinstance(page, Exception):
            raise page
        return page


def feed_url(name):
    return f"https://{name.lower()}.example/feed"


def entries(name, count, start=NOW, step=timedelta(minutes=10)):
    return [
        (f"https://{name.lower()}.example/post-{i}", f"{name} post {i}", start - step * i)
        for i in range(count)
    ]


def run(tmp_path, config, web, seen=None):
    state_dir = tmp_path / "state"
    state_dir.mkdir(exist_ok=True)
    if seen is not None:
        (state_dir / "seen.json").write_text(json.dumps(seen), encoding="utf-8")
    result = collect(config, state_dir, web, NOW)
    pending = json.loads((state_dir / "pending.json").read_text(encoding="utf-8"))
    new_seen = json.loads((state_dir / "seen.json").read_text(encoding="utf-8"))
    return result, pending, new_seen


def seen_entry(status, attempts=0, first_seen=NOW - timedelta(hours=1)):
    return {"first_seen": first_seen.isoformat(), "status": status, "attempts": attempts}


def test_done_skipped_failed_items_are_not_selected(tmp_path):
    posts = entries("A", 4)
    web = FakeWeb({feed_url("A"): rss(posts)})
    seen = {
        item_id(posts[0][0]): seen_entry("done", 1),
        item_id(posts[1][0]): seen_entry("skipped", 1),
        item_id(posts[2][0]): seen_entry("failed", 3),
    }
    _, pending, _ = run(tmp_path, make_config(["A"]), web, seen)
    assert [i["url"] for i in pending["items"]] == [posts[3][0]]


def test_pending_item_from_crashed_run_is_selected_again(tmp_path):
    posts = entries("A", 1)
    web = FakeWeb({feed_url("A"): rss(posts)})
    seen = {item_id(posts[0][0]): seen_entry("pending", 1)}
    _, pending, _ = run(tmp_path, make_config(["A"]), web, seen)
    assert [i["url"] for i in pending["items"]] == [posts[0][0]]


def test_items_older_than_max_age_are_dropped(tmp_path):
    fresh = ("https://a.example/fresh", "Fresh", NOW - timedelta(hours=47))
    stale = ("https://a.example/stale", "Stale", NOW - timedelta(hours=49))
    web = FakeWeb({feed_url("A"): rss([fresh, stale])})
    _, pending, _ = run(tmp_path, make_config(["A"], max_age_hours=48), web)
    assert [i["title"] for i in pending["items"]] == ["Fresh"]


def test_duplicate_article_across_feeds_selected_once(tmp_path):
    shared = "https://news.example/shared-story"
    web = FakeWeb(
        {
            feed_url("A"): rss([(shared + "?utm_source=a", "Shared", NOW)]),
            feed_url("B"): rss([(shared, "Shared", NOW)]),
        }
    )
    _, pending, _ = run(tmp_path, make_config(["A", "B"]), web)
    assert len(pending["items"]) == 1
    assert pending["items"][0]["source"] == "A"  # first feed in config order wins


def test_round_robin_prevents_one_feed_taking_whole_limit(tmp_path):
    web = FakeWeb(
        {
            feed_url("A"): rss(entries("A", 20)),
            feed_url("B"): rss(entries("B", 2, start=NOW - timedelta(hours=5))),
        }
    )
    _, pending, _ = run(tmp_path, make_config(["A", "B"], max_items=5), web)
    sources = [i["source"] for i in pending["items"]]
    assert len(sources) == 5
    assert sources.count("B") == 2
    # within a feed, freshest first
    a_titles = [i["title"] for i in pending["items"] if i["source"] == "A"]
    assert a_titles == ["A post 0", "A post 1", "A post 2"]


def test_failing_feed_recorded_in_errors_others_processed(tmp_path):
    web = FakeWeb(
        {
            feed_url("A"): FetchError("https://a.example/feed: HTTP 403"),
            feed_url("B"): b"<html><body>captcha</body></html>",
            feed_url("C"): rss(entries("C", 2)),
        }
    )
    result, pending, _ = run(tmp_path, make_config(["A", "B", "C"]), web)
    assert {e["feed"] for e in pending["errors"]} == {"A", "B"}
    assert "403" in next(e["error"] for e in pending["errors"] if e["feed"] == "A")
    assert [i["source"] for i in pending["items"]] == ["C", "C"]
    assert (result.feeds_ok, result.feeds_failed) == (1, 2)


def test_selected_items_marked_pending_and_attempts_preserved(tmp_path):
    posts = entries("A", 2)
    web = FakeWeb({feed_url("A"): rss(posts)})
    retry_id = item_id(posts[1][0])
    old_first_seen = NOW - timedelta(hours=3)
    seen = {retry_id: seen_entry("pending", attempts=2, first_seen=old_first_seen)}
    _, _, new_seen = run(tmp_path, make_config(["A"]), web, seen)
    new_id = item_id(posts[0][0])
    assert new_seen[new_id] == {"first_seen": NOW.isoformat(), "status": "pending", "attempts": 0}
    assert new_seen[retry_id] == {
        "first_seen": old_first_seen.isoformat(),
        "status": "pending",
        "attempts": 2,
    }


def test_items_over_limit_are_not_marked_seen(tmp_path):
    posts = entries("A", 5)
    web = FakeWeb({feed_url("A"): rss(posts)})
    _, pending, new_seen = run(tmp_path, make_config(["A"], max_items=2), web)
    assert len(pending["items"]) == 2
    assert set(new_seen) == {i["id"] for i in pending["items"]}


def test_pending_json_matches_item_schema(tmp_path):
    post = ("https://a.example/post", "Post", NOW - timedelta(hours=1))
    web = FakeWeb({feed_url("A"): rss([post]), post[0]: ARTICLE})
    _, pending, _ = run(tmp_path, make_config(["A"]), web)
    assert pending["generated_at"] == "2026-10-08T12:00:00Z"
    [item] = pending["items"]
    assert set(item) == {
        "id", "url", "source", "title", "snippet", "text", "text_source",
        "published_at", "image", "default_category",
    }
    assert item["id"] == item_id(post[0])
    assert item["published_at"] == "2026-10-08T11:00:00Z"
    assert item["text_source"] == "article"
    assert "released GPT-7" in item["text"]
    assert item["default_category"] == "ai"


def test_article_fetch_failure_uses_snippet(tmp_path):
    post = ("https://a.example/post", "Post", NOW)
    web = FakeWeb({feed_url("A"): rss([post])})  # article URL -> 404
    _, pending, _ = run(tmp_path, make_config(["A"]), web)
    [item] = pending["items"]
    assert item["text_source"] == "snippet"
    assert item["text"] == "Snippet for Post"


def test_old_seen_entries_are_pruned(tmp_path):
    web = FakeWeb({feed_url("A"): rss(entries("A", 1))})
    seen = {"ancient": seen_entry("done", 1, first_seen=NOW - timedelta(days=30))}
    _, _, new_seen = run(tmp_path, make_config(["A"]), web, seen)
    assert "ancient" not in new_seen


def test_corrupted_seen_aborts_without_writing(tmp_path):
    state_dir = tmp_path / "state"
    state_dir.mkdir()
    (state_dir / "seen.json").write_text("{broken", encoding="utf-8")
    web = FakeWeb({feed_url("A"): rss(entries("A", 1))})
    with pytest.raises(StateError):
        collect(make_config(["A"]), state_dir, web, NOW)
    assert (state_dir / "seen.json").read_text(encoding="utf-8") == "{broken"
    assert not (state_dir / "pending.json").exists()
    assert web.requested == []  # fails before any network work


def test_summary_line_reports_counts(tmp_path):
    post = ("https://a.example/post", "Post", NOW)
    web = FakeWeb({feed_url("A"): rss([post]), post[0]: ARTICLE, feed_url("B"): FetchError("x")})
    result, _, _ = run(tmp_path, make_config(["A", "B"]), web)
    assert result.summary() == "feeds ok=1 failed=1 | candidates=1 | selected=1 (article=1, snippet=0)"


def test_og_image_used_when_feed_has_no_image(tmp_path):
    post = ("https://a.example/post", "Post", NOW)
    web = FakeWeb({feed_url("A"): rss([post]), post[0]: ARTICLE})
    _, pending, _ = run(tmp_path, make_config(["A"]), web)
    assert pending["items"][0]["image"] == "https://cdn.example.com/og/gpt7.jpg"


def test_feed_image_wins_over_og_image(tmp_path):
    feed = (
        '<?xml version="1.0"?><rss version="2.0" xmlns:media="http://search.yahoo.com/mrss/">'
        "<channel><title>T</title><item><title>Post</title><link>https://a.example/post</link>"
        f"<pubDate>{NOW.strftime('%a, %d %b %Y %H:%M:%S +0000')}</pubDate>"
        '<media:content url="https://cdn.example.com/feed.jpg" medium="image"/></item></channel></rss>'
    ).encode()
    web = FakeWeb({feed_url("A"): feed, "https://a.example/post": ARTICLE})
    _, pending, _ = run(tmp_path, make_config(["A"]), web)
    assert pending["items"][0]["image"] == "https://cdn.example.com/feed.jpg"
