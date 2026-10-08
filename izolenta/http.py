"""HTTP fetching with timeouts and a response size cap."""

from __future__ import annotations

from collections.abc import Callable

import httpx

Fetch = Callable[[str], bytes]


class FetchError(Exception):
    pass


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
                    raise FetchError(f"{url}: HTTP {response.status_code}")
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
