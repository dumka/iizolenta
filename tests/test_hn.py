import json
from datetime import UTC, datetime, timedelta

import pytest

from izolenta.hn import ALGOLIA_URL, ITEM_URL, HNError, collect_discussions, parse_front_page
from izolenta.http import FetchError

NOW = datetime(2026, 10, 9, 12, 0, tzinfo=UTC)


def hit(story_id, title, points, comments, age_hours=2, url="https://example.com/a", story_text=None):
    return {
        "objectID": str(story_id),
        "title": title,
        "url": url,
        "points": points,
        "num_comments": comments,
        "created_at_i": int((NOW - timedelta(hours=age_hours)).timestamp()),
        "story_text": story_text,
    }


def algolia(*hits):
    return json.dumps({"hits": list(hits)}).encode()


def item(item_id, **fields):
    return json.dumps({"id": item_id, **fields}).encode()


class Web:
    def __init__(self, pages):
        self.pages = pages
        self.requested = []

    def __call__(self, url):
        self.requested.append(url)
        page = self.pages.get(url)
        if page is None:
            raise FetchError(f"{url}: HTTP 404")
        if isinstance(page, Exception):
            raise page
        return page


def story_with_comments(story_id, n_comments, prefix="Comment"):
    kids = [story_id * 100 + i for i in range(n_comments)]
    pages = {ITEM_URL.format(id=story_id): item(story_id, kids=kids)}
    for i, kid in enumerate(kids):
        pages[ITEM_URL.format(id=kid)] = item(kid, text=f"<p>{prefix} {i} about <i>models</i></p>")
    return pages


def run(pages, seen=None, max_per_run=4, top_comments=12):
    result = collect_discussions(
        Web(pages),
        seen or {},
        NOW,
        min_points=200,
        min_comments=80,
        max_age_hours=36,
        max_per_run=max_per_run,
        top_comments=top_comments,
    )
    return result.selected, result.errors


def test_parse_front_page_reads_fields_and_builds_hn_url():
    [c] = parse_front_page(algolia(hit(42, "Show HN: A thing", 300, 120, story_text="<p>Hi &amp; bye</p>")), NOW)
    assert (c.id, c.title, c.points, c.comments) == ("42", "Show HN: A thing", 300, 120)
    assert c.hn_url == "https://news.ycombinator.com/item?id=42"
    assert c.published_at == NOW - timedelta(hours=2)
    assert c.story_text == "Hi & bye"


@pytest.mark.parametrize("raw", [b"not json", b'{"nohits": []}', b"<html>captcha</html>"])
def test_parse_front_page_bad_response_raises(raw):
    with pytest.raises(HNError):
        parse_front_page(raw, NOW)


def test_non_http_article_url_becomes_none_and_bad_ids_skipped():
    raw = algolia(hit(1, "Ask HN: x", 300, 100, url="javascript:alert(1)"), {**hit(2, "bad", 300, 100), "objectID": "2/../x"})
    [c] = parse_front_page(raw, NOW)
    assert c.id == "1" and c.url is None


def test_thresholds_age_and_seen_filter_and_sort_by_comments():
    pages = {
        ALGOLIA_URL: algolia(
            hit(1, "Low points", 150, 300),
            hit(2, "Few comments", 400, 50),
            hit(3, "Too old", 500, 500, age_hours=40),
            hit(4, "Seen", 500, 400),
            hit(5, "Good A", 300, 120),
            hit(6, "Good B", 250, 350),
        ),
        **story_with_comments(5, 5),
        **story_with_comments(6, 5),
    }
    seen = {"hn:4": {"first_seen": NOW.isoformat(), "status": "done", "attempts": 1}}
    discussions, errors = run(pages, seen=seen)
    assert [d["title"] for d in discussions] == ["Good B", "Good A"]
    assert errors == []


def test_cap_per_run():
    hits = [hit(i, f"Story {i}", 300, 100 + i) for i in range(1, 7)]
    pages = {ALGOLIA_URL: algolia(*hits)}
    for i in range(1, 7):
        pages.update(story_with_comments(i, 4))
    discussions, _ = run(pages, max_per_run=2)
    assert [d["id"] for d in discussions] == ["hn:6", "hn:5"]


def test_record_shape_and_comments_in_kids_order_without_dead():
    pages = {ALGOLIA_URL: algolia(hit(7, "Story", 300, 100, url="https://example.com/s"))}
    pages[ITEM_URL.format(id=7)] = item(7, kids=[71, 72, 73, 74, 75])
    pages[ITEM_URL.format(id=71)] = item(71, text="First &amp; best")
    pages[ITEM_URL.format(id=72)] = item(72, deleted=True)
    pages[ITEM_URL.format(id=73)] = item(73, dead=True, text="flagged")
    pages[ITEM_URL.format(id=74)] = item(74, text="<p>Second</p>")
    pages[ITEM_URL.format(id=75)] = item(75, text="Third " + "x" * 3000)
    [d], _ = run(pages)
    assert set(d) == {"id", "hn_url", "url", "title", "points", "comments", "published_at", "story_text", "top_comments"}
    assert d["id"] == "hn:7" and d["hn_url"] == "https://news.ycombinator.com/item?id=7"
    assert d["url"] == "https://example.com/s"
    assert d["published_at"] == (NOW - timedelta(hours=2)).strftime("%Y-%m-%dT%H:%M:%SZ")
    assert d["top_comments"][:2] == ["First & best", "Second"]
    assert len(d["top_comments"]) == 3
    assert len(d["top_comments"][2]) <= 1200


def test_top_comments_limit():
    pages = {ALGOLIA_URL: algolia(hit(8, "Story", 300, 100)), **story_with_comments(8, 20)}
    [d], _ = run(pages, top_comments=12)
    assert len(d["top_comments"]) == 12
    assert d["top_comments"][0] == "Comment 0 about models"


def test_story_with_fewer_than_3_live_comments_is_skipped():
    pages = {ALGOLIA_URL: algolia(hit(9, "Thin", 300, 100), hit(10, "Rich", 300, 90))}
    pages[ITEM_URL.format(id=9)] = item(9, kids=[91, 92])
    pages[ITEM_URL.format(id=91)] = item(91, text="one")
    pages[ITEM_URL.format(id=92)] = item(92, text="two")
    pages.update(story_with_comments(10, 3))
    discussions, _ = run(pages)
    assert [d["id"] for d in discussions] == ["hn:10"]


def test_algolia_failure_reported_as_error():
    discussions, errors = run({ALGOLIA_URL: FetchError("hn.algolia.com: HTTP 503")})
    assert discussions == []
    assert errors and errors[0]["feed"] == "HN discussions" and "503" in errors[0]["error"]


def test_failed_comment_fetch_is_skipped_not_fatal():
    pages = {ALGOLIA_URL: algolia(hit(11, "Story", 300, 100))}
    pages[ITEM_URL.format(id=11)] = item(11, kids=[111, 112, 113, 114])
    pages[ITEM_URL.format(id=111)] = item(111, text="ok one")
    pages[ITEM_URL.format(id=112)] = FetchError("timeout")
    pages[ITEM_URL.format(id=113)] = item(113, text="ok two")
    pages[ITEM_URL.format(id=114)] = item(114, text="ok three")
    [d], errors = run(pages)
    assert d["top_comments"] == ["ok one", "ok two", "ok three"]
    assert errors == []
