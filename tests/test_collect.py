import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from izolenta.collect import collect
from izolenta.config import Config, Feed, Settings, XAccount
from izolenta.feeds import item_id
from izolenta.http import FetchError
from izolenta.state import StateError
from izolenta.xposts import API_URL

NOW = datetime(2026, 10, 8, 12, 0, tzinfo=UTC)


@pytest.fixture(autouse=True)
def no_retry_delay(monkeypatch):
    monkeypatch.setattr("izolenta.collect.ACCOUNT_RETRY_DELAY", 0)
ARTICLE = (Path(__file__).parent / "fixtures" / "article.html").read_bytes()


def make_config(feeds, max_items=15, max_age_hours=48, accounts=(), max_posts=10, hn=False):
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
            max_posts_per_run=max_posts,
            post_max_age_hours=48,
            hn_discussions=hn,
            hn_min_points=200,
            hn_min_comments=80,
            hn_max_age_hours=36,
            max_discussions_per_run=2,
            hn_top_comments=5,
        ),
        feeds=tuple(Feed(name, f"https://{name.lower()}.example/feed", "ai") for name in feeds),
        x_accounts=tuple(XAccount(h) for h in accounts),
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


def fx(handle, posts):
    """FxTwitter-style response; posts: list of (status_id, text, published datetime)."""
    results = [
        {
            "type": "status", "id": sid, "text": text, "created_timestamp": int(ts.timestamp()),
            "author": {"screen_name": handle, "name": handle.title()},
            "replying_to": None, "reposted_by": None, "lang": "en",
        }
        for sid, text, ts in posts
    ]
    return json.dumps({"code": 200, "results": results}).encode()


def x_url(handle):
    return API_URL.format(handle=handle)


def test_posts_collected_into_pending_with_cap_and_round_robin(tmp_path):
    a_posts = [(str(100 + i), f"A post {i}", NOW - timedelta(minutes=10 * i)) for i in range(5)]
    web = FakeWeb({
        feed_url("F"): rss(entries("F", 1)),
        x_url("alice"): fx("alice", a_posts),
        x_url("bob"): fx("bob", [("200", "B post", NOW - timedelta(hours=3))]),
    })
    result, pending, seen = run(tmp_path, make_config(["F"], accounts=["alice", "bob"], max_posts=3), web)
    posts = pending["posts"]
    assert [p["text"] for p in posts] == ["A post 0", "B post", "A post 1"]
    assert set(posts[0]) == {"id", "url", "author_handle", "author_name", "published_at", "text", "quote", "lang"}
    assert posts[0]["id"] == "x:100" and posts[0]["url"] == "https://x.com/alice/status/100"
    assert seen["x:100"]["status"] == "pending"
    assert "x:102" not in seen  # over the cap: not marked
    assert "posts: accounts ok=2 failed=0 | candidates=6 | selected=3" in result.summary()


def test_seen_posts_not_selected_again(tmp_path):
    web = FakeWeb({x_url("alice"): fx("alice", [("100", "Old", NOW), ("101", "New", NOW)]), feed_url("F"): rss([])})
    seen = {"x:100": seen_entry("done", 1)}
    _, pending, _ = run(tmp_path, make_config(["F"], accounts=["alice"]), web, seen)
    assert [p["id"] for p in pending["posts"]] == ["x:101"]


def test_failing_account_recorded_and_articles_still_collected(tmp_path):
    web = FakeWeb({feed_url("F"): rss(entries("F", 2)), x_url("alice"): FetchError("api.fxtwitter.com: HTTP 503")})
    result, pending, _ = run(tmp_path, make_config(["F"], accounts=["alice"]), web)
    assert len(pending["items"]) == 2
    assert pending["posts"] == []
    assert any(e["feed"] == "@alice" and "503" in e["error"] for e in pending["errors"])
    assert "posts: accounts ok=0 failed=1" in result.summary()


def test_old_posts_dropped(tmp_path):
    web = FakeWeb({
        feed_url("F"): rss([]),
        x_url("alice"): fx("alice", [("1", "Fresh", NOW - timedelta(hours=47)), ("2", "Stale", NOW - timedelta(hours=49))]),
    })
    _, pending, _ = run(tmp_path, make_config(["F"], accounts=["alice"]), web)
    assert [p["text"] for p in pending["posts"]] == ["Fresh"]


def test_failing_account_retried_once(tmp_path):
    calls = {"n": 0}
    good = fx("alice", [("1", "Post", NOW)])

    class Flaky(FakeWeb):
        def __call__(self, url):
            if url == x_url("alice"):
                calls["n"] += 1
                if calls["n"] == 1:
                    raise FetchError("api.fxtwitter.com: HTTP 404")
                return good
            return super().__call__(url)

    _, pending, _ = run(tmp_path, make_config(["F"], accounts=["alice"]), Flaky({feed_url("F"): rss([])}))
    assert calls["n"] == 2
    assert [p["id"] for p in pending["posts"]] == ["x:1"]
    assert not any(e["feed"] == "@alice" for e in pending["errors"])


def hn_pages():
    from izolenta.hn import ALGOLIA_URL, ITEM_URL

    hits = [
        {"objectID": "500", "title": "Big thread", "url": "https://example.com/big", "points": 400,
         "num_comments": 300, "created_at_i": int((NOW - timedelta(hours=3)).timestamp())},
    ]
    pages = {ALGOLIA_URL: json.dumps({"hits": hits}).encode(),
             ITEM_URL.format(id=500): json.dumps({"id": 500, "kids": [1, 2, 3]}).encode()}
    for kid in (1, 2, 3):
        pages[ITEM_URL.format(id=kid)] = json.dumps({"id": kid, "text": f"comment {kid}"}).encode()
    return pages


def test_hn_discussions_collected_and_marked_pending(tmp_path):
    web = FakeWeb({feed_url("F"): rss(entries("F", 1)), **hn_pages()})
    result, pending, seen = run(tmp_path, make_config(["F"], hn=True), web)
    [d] = pending["discussions"]
    assert d["id"] == "hn:500" and d["top_comments"] == ["comment 1", "comment 2", "comment 3"]
    assert seen["hn:500"]["status"] == "pending"
    assert "hn: selected=1" in result.summary()


def test_hn_disabled_gives_empty_list_and_no_requests(tmp_path):
    from izolenta.hn import ALGOLIA_URL

    web = FakeWeb({feed_url("F"): rss(entries("F", 1)), **hn_pages()})
    result, pending, _ = run(tmp_path, make_config(["F"], hn=False), web)
    assert pending["discussions"] == []
    assert ALGOLIA_URL not in web.requested
    assert "hn:" not in result.summary()


def test_hn_failure_recorded_and_articles_collected(tmp_path):
    from izolenta.hn import ALGOLIA_URL

    web = FakeWeb({feed_url("F"): rss(entries("F", 2)), ALGOLIA_URL: FetchError("hn.algolia.com: HTTP 503")})
    _, pending, _ = run(tmp_path, make_config(["F"], hn=True), web)
    assert len(pending["items"]) == 2
    assert pending["discussions"] == []
    assert any(e["feed"] == "HN discussions" for e in pending["errors"])


def test_source_stats_count_entries_candidates_selected(tmp_path):
    from izolenta.feeds import canonical_url, item_id

    a_entries = entries("A", 5)
    already_done = item_id(canonical_url(a_entries[0][0]))
    web = FakeWeb({feed_url("A"): rss(a_entries), feed_url("B"): FetchError("https://b.example/feed: HTTP 403")})
    _, pending, _ = run(tmp_path, make_config(["A", "B"], max_items=2), web, seen={already_done: seen_entry("done")})
    by_name = {s["name"]: s for s in pending["stats"]["sources"]}
    assert by_name["A"] == {"name": "A", "kind": "feed", "ok": True, "error": None,
                            "entries": 5, "candidates": 4, "selected": 2}
    assert by_name["B"]["ok"] is False and "403" in by_name["B"]["error"]
    assert (by_name["B"]["entries"], by_name["B"]["selected"]) == (0, 0)


def test_source_stats_cover_x_accounts_and_hn(tmp_path):
    web = FakeWeb({
        feed_url("F"): rss(entries("F", 1)),
        x_url("alice"): fx("alice", [("1", "Alice says something long enough", NOW - timedelta(hours=1))]),
        **hn_pages(),
    })
    _, pending, _ = run(tmp_path, make_config(["F"], accounts=("alice", "bob"), hn=True), web)
    by_name = {s["name"]: s for s in pending["stats"]["sources"]}
    assert by_name["@alice"]["kind"] == "x" and by_name["@alice"]["selected"] == 1
    assert by_name["@bob"]["ok"] is False
    assert by_name["HN discussions"] == {"name": "HN discussions", "kind": "hn", "ok": True, "error": None,
                                         "entries": 1, "candidates": 1, "selected": 1}


def test_source_stats_hn_failure(tmp_path):
    from izolenta.hn import ALGOLIA_URL

    web = FakeWeb({feed_url("F"): rss(entries("F", 1)), ALGOLIA_URL: FetchError("hn.algolia.com: HTTP 503")})
    _, pending, _ = run(tmp_path, make_config(["F"], hn=True), web)
    hn = next(s for s in pending["stats"]["sources"] if s["kind"] == "hn")
    assert hn["ok"] is False and "503" in hn["error"]
