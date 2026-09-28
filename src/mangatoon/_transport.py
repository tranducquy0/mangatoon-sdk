"""HTTP transports with runtime reachability detection.

The SDK defaults to :class:`AutoTransport`, which probes the origin once and
either talks to it directly or routes through a configured read proxy. That
matters in practice: on some networks ``mangatoon.mobi`` is unreachable while
generic internet access works fine, and the choice is not something the caller
should have to reason about per call site.

Transports expose two operations, because the API needs both:

* :meth:`Transport.get_json` for the signed JSON API;
* :meth:`Transport.get_bytes` for the ``application/octet-stream`` chapter
  payloads, which must arrive unmangled.
"""

from __future__ import annotations

import asyncio
import time
from types import TracebackType
from typing import Any, Protocol, Sequence, runtime_checkable

import httpx

from ._exceptions import APIError, DirectAccessBlocked, TransportError

__all__ = [
    "Transport",
    "DirectTransport",
    "ProxyTransport",
    "AutoTransport",
    "default_headers",
]

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)

#: Free read proxy able to return a JSON body as text.
DEFAULT_TEXT_PROXY = "https://r.jina.ai/"

#: Free CORS proxy able to return arbitrary binary bodies intact.
DEFAULT_BINARY_PROXY = "https://api.cors.lol/?url="

RETRY_STATUS = frozenset({408, 425, 429, 500, 502, 503, 504})


def default_headers() -> dict[str, str]:
    """Headers shared by all transports."""
    return {
        "User-Agent": USER_AGENT,
        "Accept": "*/*",
        "Accept-Language": "en-US,en;q=0.9",
    }


@runtime_checkable
class Transport(Protocol):
    """Minimal interface the client depends on."""

    name: str

    async def get_json(self, url: str, headers: dict[str, str]) -> Any: ...

    async def get_bytes(self, url: str, headers: dict[str, str]) -> bytes: ...

    async def aclose(self) -> None: ...


class _BaseTransport:
    """Shared retry, rate limiting and error handling."""

    name = "base"

    def __init__(
        self,
        *,
        timeout: float = 30.0,
        rate_limit: float = 1.0,
        max_retries: int = 3,
        backoff: float = 1.5,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self._timeout = timeout
        self._rate_limit = max(0.0, rate_limit)
        self._max_retries = max_retries
        self._backoff = backoff
        self._client = client
        self._owns_client = client is None
        self._lock = asyncio.Lock()
        self._next_slot = 0.0

    @property
    def client(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(
                timeout=self._timeout, follow_redirects=True, headers=default_headers()
            )
            self._owns_client = True
        return self._client

    async def _throttle(self) -> None:
        """Serialise requests and keep a minimum gap between them."""
        if self._rate_limit <= 0:
            return
        async with self._lock:
            now = time.monotonic()
            wait = self._next_slot - now
            if wait > 0:
                await asyncio.sleep(wait)
                now = time.monotonic()
            self._next_slot = max(now, self._next_slot) + self._rate_limit

    async def _send(self, url: str, headers: dict[str, str]) -> httpx.Response:
        merged = {**default_headers(), **headers}
        last: Exception | None = None

        for attempt in range(self._max_retries + 1):
            await self._throttle()
            try:
                response = await self.client.get(url, headers=merged)
            except httpx.HTTPError as exc:
                last = exc
            else:
                if response.status_code not in RETRY_STATUS:
                    return response
                last = TransportError(
                    f"HTTP {response.status_code}", url=url
                )
                response.close()

            if attempt < self._max_retries:
                await asyncio.sleep(self._backoff**attempt)

        assert last is not None
        raise TransportError(f"request failed after {self._max_retries + 1} attempts: {last}", url=url)

    async def aclose(self) -> None:
        if self._client is not None and self._owns_client:
            await self._client.aclose()
            self._client = None

    async def __aenter__(self) -> "_BaseTransport":
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        await self.aclose()


class DirectTransport(_BaseTransport):
    """Talks to the origin with no intermediary."""

    name = "direct"

    def __init__(self, *, probe_url: str = "https://sg.mangatoon.mobi/", **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self._probe_url = probe_url

    async def is_reachable(self) -> bool:
        """Whether the origin answers at all."""
        try:
            response = await self.client.get(
                self._probe_url, headers=default_headers(), timeout=8.0
            )
        except httpx.HTTPError:
            return False
        # Any HTTP status proves reachability; the origin simply refuses
        # unsigned paths, which is not a network problem.
        return True

    async def get_json(self, url: str, headers: dict[str, str]) -> Any:
        return await self._fetch_json(url, headers, url)

    async def _fetch_json(self, url: str, headers: dict[str, str], report_url: str) -> Any:
        import json

        response = await self._send(url, headers)
        if response.status_code >= 400:
            raise APIError(
                f"HTTP {response.status_code} for {report_url}",
                status=response.status_code,
            )
        return _parse_json(response, report_url)

    async def get_bytes(self, url: str, headers: dict[str, str]) -> bytes:
        response = await self._send(url, headers)
        if response.status_code >= 400:
            raise APIError(
                f"HTTP {response.status_code} for {url}", status=response.status_code
            )
        return response.content


class ProxyTransport(_BaseTransport):
    """Routes through read proxies for networks that block the origin.

    Two proxies are used because they fail differently: the text proxy
    reformats responses as markdown-ish text and is only usable for JSON, while
    the CORS proxy passes bytes through untouched and is required for chapter
    payloads. ``text_proxy=None`` or ``binary_proxy=None`` disables that half.
    """

    name = "proxy"

    def __init__(
        self,
        *,
        text_proxy: str | None = DEFAULT_TEXT_PROXY,
        binary_proxy: str | None = DEFAULT_BINARY_PROXY,
        max_retries: int = 3,
        **kwargs: Any,
    ) -> None:
        super().__init__(max_retries=max_retries, **kwargs)
        self._text_proxy = text_proxy
        self._binary_proxy = binary_proxy

    def _via_text(self, url: str) -> str:
        if not self._text_proxy:
            raise DirectAccessBlocked(
                "origin is unreachable and no text proxy is configured", url=url
            )
        return f"{self._text_proxy}{url}"

    def _via_binary(self, url: str) -> str:
        if not self._binary_proxy:
            raise DirectAccessBlocked(
                "origin is unreachable and no binary proxy is configured", url=url
            )
        separator = "&" if "?" in self._binary_proxy else ""
        return f"{self._binary_proxy}{separator}url={url}"

    async def is_reachable(self) -> bool:
        try:
            await self.client.get(
                self._via_text("https://sg.mangatoon.mobi/"),
                headers=default_headers(),
                timeout=20.0,
            )
        except httpx.HTTPError:
            return False
        return True

    async def get_json(self, url: str, headers: dict[str, str]) -> Any:
        last: Exception | None = None
        for attempt in range(self._max_retries + 1):
            response = await self._send(self._via_text(url), headers)
            text = response.text
            # The text proxy signals throttling in-band, not with a status code.
            if "RateLimit" in text or "429 Too Many Requests" in text:
                last = TransportError("read proxy rate limited", url=url)
                if attempt < self._max_retries:
                    await asyncio.sleep(3.0 + 4.0 * attempt)
                    continue
            return _parse_json_text(text, url)
        raise TransportError(f"read proxy kept failing: {last}", url=url)

    async def get_bytes(self, url: str, headers: dict[str, str]) -> bytes:
        last: Exception | None = None
        for attempt in range(self._max_retries + 1):
            response = await self._send(self._via_binary(url), headers)
            body = response.content
            if response.status_code == 200 and len(body) > 32:
                return body
            last = TransportError(
                f"binary proxy returned HTTP {response.status_code}, {len(body)} bytes",
                url=url,
            )
            if attempt < self._max_retries:
                await asyncio.sleep(3.0 + 4.0 * attempt)
        raise TransportError(f"binary proxy kept failing: {last}", url=url)


class AutoTransport:
    """Picks a working transport at runtime and remembers the choice.

    The origin is probed once. On success direct access is used; otherwise the
    proxy transport takes over. A later transport-level failure demotes the
    choice once, so a network that changes mid-session is survivable.
    """

    name = "auto"

    def __init__(
        self,
        *,
        direct: Transport | None = None,
        proxy: Transport | None = None,
        probe: bool = True,
        **kwargs: Any,
    ) -> None:
        self._direct = direct or DirectTransport(**kwargs)
        self._proxy = proxy or ProxyTransport(**kwargs)
        self._active: Transport = self._direct
        self._probed = False
        self._probe = probe
        self._probe_lock = asyncio.Lock()

    @property
    def active_name(self) -> str:
        """Name of the transport currently in use."""
        return self._active.name

    async def _ensure_probed(self) -> None:
        if self._probed or not self._probe:
            return
        async with self._probe_lock:
            if self._probed:
                return
            if await _reachable(self._direct):
                self._active = self._direct
            elif await _reachable(self._proxy):
                self._active = self._proxy
            else:
                raise DirectAccessBlocked(
                    "neither the origin nor the read proxy is reachable; check "
                    "network access or pass an explicit transport"
                )
            self._probed = True

    async def _dispatch(self, method: str, *args: Any) -> Any:
        await self._ensure_probed()
        try:
            return await getattr(self._active, method)(*args)
        except (TransportError, httpx.HTTPError):
            other = self._proxy if self._active is self._direct else self._direct
            if other is self._active or not await _reachable(other):
                raise
            self._active = other
            return await getattr(self._active, method)(*args)

    async def get_json(self, url: str, headers: dict[str, str]) -> Any:
        return await self._dispatch("get_json", url, headers)

    async def get_bytes(self, url: str, headers: dict[str, str]) -> bytes:
        return await self._dispatch("get_bytes", url, headers)

    async def aclose(self) -> None:
        await self._direct.aclose()
        await self._proxy.aclose()


async def _reachable(transport: Any) -> bool:
    probe = getattr(transport, "is_reachable", None)
    if probe is None:
        return False
    try:
        return bool(await probe())
    except Exception:  # noqa: BLE001 - probing must never raise
        return False


def _parse_json(response: httpx.Response, url: str) -> Any:
    try:
        return response.json()
    except ValueError as exc:
        raise APIError(f"response was not valid JSON: {exc}", payload=response.text[:500]) from exc


def _parse_json_text(text: str, url: str) -> Any:
    """Parse JSON that may be wrapped in markup by a text proxy.

    A read proxy sometimes answers ``200`` with an HTML shell containing the
    real payload in a ``<pre>`` block, so fall back to extracting that.
    """
    import json
    import re

    stripped = text.strip()
    try:
        return json.loads(stripped)
    except ValueError:
        pass

    match = re.search(r"<pre[^>]*>(.*?)</pre>", stripped, re.DOTALL)
    if match:
        candidate = match.group(1)
        for unescape in (_unescape, lambda s: s):
            try:
                return json.loads(unescape(candidate.strip()))
            except ValueError:
                continue

    raise APIError(
        f"could not locate a JSON body in the response for {url}",
        payload=stripped[:500],
    )


def _unescape(text: str) -> str:
    import html

    return html.unescape(text)
