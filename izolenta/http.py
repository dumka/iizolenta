"""HTTP fetching with timeouts and a response size cap."""

from __future__ import annotations

from collections.abc import Callable

import httpx

Fetch = Callable[[str], bytes]


class FetchError(Exception):
    pass


ERROR_SNIPPET_BYTES = 120


def _error_detail(response: httpx.Response) -> str:
    """Why a request failed: the cloud egress proxy names the reason in a header
    (e.g. host_not_allowed); APIs usually explain it at the start of the body."""
    deny_reason = response.headers.get("x-deny-reason")
    if deny_reason:
        return f" ({deny_reason})"
    snippet = b""
    for chunk in response.iter_bytes():
        snippet += chunk
        if len(snippet) >= ERROR_SNIPPET_BYTES:
            break
    text = " ".join(snippet[:ERROR_SNIPPET_BYTES].decode("utf-8", "replace").split())
    return f" ({text})" if text else ""


def make_fetcher(
    timeout: float,
    user_agent: str,
    max_bytes: int,
    transport: httpx.BaseTransport | None = None,
) -> Fetch:
    client = httpx.Client(
        timeout=timeout,
        headers={"User-Agent": user_agent},
        follow_redirects=True,
        transport=transport,
    )

    def fetch(url: str) -> bytes:
        try:
            with client.stream("GET", url) as response:
                if not response.is_success:
                    raise FetchError(f"{url}: HTTP {response.status_code}{_error_detail(response)}")
                chunks: list[bytes] = []
                size = 0
                for chunk in response.iter_bytes():
                    size += len(chunk)
                    if size > max_bytes:
                        raise FetchError(f"{url}: response too large (> {max_bytes} bytes)")
                    chunks.append(chunk)
                return b"".join(chunks)
        except httpx.HTTPError as exc:
            raise FetchError(f"{url}: {exc}") from exc

    return fetch
