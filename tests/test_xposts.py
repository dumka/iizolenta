import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from izolenta.xposts import XError, parse_statuses

FIXTURES = Path(__file__).parent / "fixtures"
NOW = datetime(2026, 10, 8, 12, 0, tzinfo=UTC)


def parsed(limit=4000):
    raw = (FIXTURES / "fx_statuses.json").read_bytes()
    return {p.status_id: p for p in parse_statuses("testdev", raw, NOW, text_limit=limit)}


def test_root_post_parsed_with_url_built_from_handle_and_id():
    post = parsed()["100"]
    assert post.id == "x:100"
    assert post.url == "https://x.com/testdev/status/100"
    assert (post.author_handle, post.author_name) == ("testdev", "Test Dev")
    assert post.text == "Root post about LLM evals."
    assert post.published_at == NOW - timedelta(hours=1)
    assert post.quote is None
    assert post.lang == "en"


def test_reply_to_other_user_dropped():
    assert "103" not in parsed()


def test_plain_repost_dropped():
    assert "130" not in parsed()


def test_self_reply_thread_glued_to_root_in_time_order():
    posts = parsed()
    assert "111" not in posts and "112" not in posts
    assert posts["110"].text == "Thread start 1/\n\nPart 2: details.\n\nPart 3: conclusions."


def test_thread_continuation_without_root_dropped():
    assert "120" not in parsed()


def test_quote_post_keeps_quoted_text():
    post = parsed()["102"]
    assert post.text == "Great results here"
    assert post.quote == {"author_handle": "other", "author_name": "Other Person", "text": "results for all claudes"}


def test_empty_body_204_returns_no_posts():
    assert parse_statuses("testdev", b"", NOW) == []


@pytest.mark.parametrize(
    "raw",
    [
        json.dumps({"code": 404, "message": "User not found"}).encode(),
        b'{"code": 200, "results": [{"type": "status", "id": "1", "te',
        b'{"code": 200}',
        b"<html>Rate limited</html>",
    ],
)
def test_error_code_and_broken_json_raise_x_error(raw):
    with pytest.raises(XError):
        parse_statuses("testdev", raw, NOW)


def test_future_timestamp_clamped_to_now():
    assert parsed()["140"].published_at == NOW


def test_long_note_tweet_cut_by_paragraphs():
    post = parsed(limit=1000)["101"]
    assert len(post.text) <= 1000
    assert post.text.startswith("Paragraph 1:")
    assert not post.text.endswith(" ")
    assert "Paragraph 10" not in post.text


def test_non_numeric_status_id_dropped():
    raw = json.dumps({"code": 200, "results": [{
        "type": "status", "id": "12/../evil", "text": "hi", "created_timestamp": 1,
        "author": {"screen_name": "testdev", "name": "T"}, "replying_to": None, "reposted_by": None,
    }]}).encode()
    assert parse_statuses("testdev", raw, NOW) == []
