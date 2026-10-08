import httpx
import pytest

from izolenta.http import FetchError, make_fetcher


def fetcher_for(handler, max_bytes=1000):
    return make_fetcher(
        timeout=5,
        user_agent="IzolentaTest/1.0",
        max_bytes=max_bytes,
        transport=httpx.MockTransport(handler),
    )


def test_fetch_returns_body_and_sends_user_agent():
    seen = {}

    def handler(request):
        seen["ua"] = request.headers["user-agent"]
        return httpx.Response(200, content=b"<rss/>")

    assert fetcher_for(handler)("https://x.example/feed") == b"<rss/>"
    assert seen["ua"] == "IzolentaTest/1.0"


def test_non_2xx_status_raises_fetch_error():
    fetch = fetcher_for(lambda request: httpx.Response(403, content=b"denied"))
    with pytest.raises(FetchError, match="403"):
        fetch("https://x.example/feed")


def test_oversized_response_raises_fetch_error():
    fetch = fetcher_for(lambda request: httpx.Response(200, content=b"x" * 5000), max_bytes=1000)
    with pytest.raises(FetchError, match="too large"):
        fetch("https://x.example/huge")


def test_redirect_is_followed():
    def handler(request):
        if request.url.path == "/old":
            return httpx.Response(301, headers={"location": "https://x.example/new"})
        return httpx.Response(200, content=b"moved")

    assert fetcher_for(handler)("https://x.example/old") == b"moved"


def test_transport_error_raises_fetch_error():
    def handler(request):
        raise httpx.ConnectTimeout("timed out", request=request)

    with pytest.raises(FetchError, match="timed out"):
        fetcher_for(handler)("https://x.example/slow")
