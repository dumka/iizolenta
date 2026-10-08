from datetime import UTC, datetime
from pathlib import Path

from izolenta.extract import article_text, extract_text, truncate_paragraphs
from izolenta.feeds import FeedItem
from izolenta.http import FetchError

FIXTURES = Path(__file__).parent / "fixtures"


def make_item(snippet="Feed snippet text.", title="Some title") -> FeedItem:
    return FeedItem(
        id="abc",
        url="https://tech.example.com/a",
        source="Example",
        title=title,
        snippet=snippet,
        published_at=datetime(2026, 10, 8, tzinfo=UTC),
        image=None,
        default_category="ai",
    )


def test_article_text_extracted_from_html():
    text = extract_text((FIXTURES / "article.html").read_bytes())
    assert text is not None
    assert "released GPT-7" in text
    assert "Pricing is set" in text
    assert "Sign in" not in text  # navigation boilerplate removed


def page_fetch(html: str):
    return lambda url: html.encode("utf-8")


def test_paywall_page_falls_back_to_snippet():
    page = (FIXTURES / "article_paywall.html").read_bytes()
    result = article_text(make_item(), lambda url: page, limit=8000)
    assert (result.text, result.text_source) == ("Feed snippet text.", "snippet")


def test_fetch_error_falls_back_to_snippet():
    def failing_fetch(url):
        raise FetchError("HTTP 403")

    result = article_text(make_item(), failing_fetch, limit=8000)
    assert (result.text, result.text_source, result.image) == ("Feed snippet text.", "snippet", None)


def test_fallback_uses_title_when_snippet_empty():
    def failing_fetch(url):
        raise FetchError("boom")

    result = article_text(make_item(snippet=""), failing_fetch, limit=8000)
    assert (result.text, result.text_source) == ("Some title", "snippet")


def test_article_source_marked_when_extraction_succeeds():
    page = (FIXTURES / "article.html").read_bytes()
    result = article_text(make_item(), lambda url: page, limit=8000)
    assert result.text_source == "article"
    assert "released GPT-7" in result.text


def test_og_image_extracted_from_article_page():
    page = (FIXTURES / "article.html").read_bytes()
    result = article_text(make_item(), lambda url: page, limit=8000)
    assert result.image == "https://cdn.example.com/og/gpt7.jpg"


def test_relative_og_image_resolved_against_article_url():
    html = '<html><head><meta property="og:image" content="/img/x.jpg"></head><body><p>x</p></body></html>'
    result = article_text(make_item(), page_fetch(html), limit=8000)
    assert result.image == "https://tech.example.com/img/x.jpg"


def test_non_http_og_image_ignored():
    html = '<html><head><meta property="og:image" content="javascript:alert(1)"></head><body></body></html>'
    result = article_text(make_item(), page_fetch(html), limit=8000)
    assert result.image is None


def test_metadata_failure_keeps_article_text(monkeypatch):
    def broken_metadata(*args, **kwargs):
        raise ValueError("bad markup")

    monkeypatch.setattr("izolenta.extract.trafilatura.extract_metadata", broken_metadata)
    page = (FIXTURES / "article.html").read_bytes()
    result = article_text(make_item(), lambda url: page, limit=8000)
    assert result.text_source == "article"
    assert result.image is None


def test_truncate_keeps_whole_paragraphs_under_limit():
    text = "aaaa\nbbbb\ncccc"
    assert truncate_paragraphs(text, 9) == "aaaa\nbbbb"
    assert truncate_paragraphs(text, 100) == text


def test_truncate_hard_cuts_single_long_paragraph():
    text = "x" * 50 + "\nshort"
    result = truncate_paragraphs(text, 20)
    assert result == "x" * 17 + "..."
    assert len(result) == 20
