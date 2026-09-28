"""Transport behaviour: retries, throttling, fallback and proxy parsing.

Uses ``httpx.MockTransport`` so no network is touched.
"""

from __future__ import annotations

import json

import httpx
import pytest

from mangatoon._exceptions import APIError, DirectAccessBlocked, TransportError
from mangatoon._transport import (
    DEFAULT_BINARY_PROXIES,
    PROXY_USER_AGENT,
    AutoTransport,
    DirectTransport,
    ProxyTransport,
    _is_rate_limited,
    _parse_json_text,
)


def client_for(handler) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


def always(status: int, body: bytes = b"x", *, ctype: str = "application/json"):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(status, content=body, headers={"content-type": ctype})

    return handler


class TestDirect:
    async def test_returns_json(self) -> None:
        payload = json.dumps({"status": "success", "data": {"id": 1}}).encode()
        t = DirectTransport(client=client_for(always(200, payload)), rate_limit=0)
        assert await t.get_json("https://x/api", {}) == {"status": "success", "data": {"id": 1}}
        await t.aclose()

    async def test_sends_browser_user_agent(self) -> None:
        seen: list[str] = []

        def handler(request: httpx.Request) -> httpx.Response:
            seen.append(request.headers.get("user-agent", ""))
            return httpx.Response(200, content=b"{}")

        t = DirectTransport(client=client_for(handler), rate_limit=0)
        await t.get_json("https://x/api", {})
        assert "Mozilla" in seen[0]
        await t.aclose()

    async def test_http_error_raises_api_error(self) -> None:
        t = DirectTransport(client=client_for(always(403, b"{}")), rate_limit=0, max_retries=0)
        with pytest.raises(APIError) as exc:
            await t.get_json("https://x/api", {})
        assert exc.value.status == 403
        await t.aclose()

    async def test_retries_transient_status(self) -> None:
        calls = {"n": 0}

        def handler(request: httpx.Request) -> httpx.Response:
            calls["n"] += 1
            if calls["n"] < 3:
                return httpx.Response(503)
            return httpx.Response(200, content=b'{"ok":true}')

        t = DirectTransport(
            client=client_for(handler), rate_limit=0, max_retries=3, backoff=1.01
        )
        assert await t.get_json("https://x/api", {}) == {"ok": True}
        assert calls["n"] == 3
        await t.aclose()

    async def test_gives_up_after_max_retries(self) -> None:
        t = DirectTransport(
            client=client_for(always(503)), rate_limit=0, max_retries=2, backoff=1.01
        )
        with pytest.raises(TransportError, match="after 3 attempts"):
            await t.get_json("https://x/api", {})
        await t.aclose()

    async def test_network_error_is_wrapped(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            raise httpx.ConnectError("refused", request=request)

        t = DirectTransport(client=client_for(handler), rate_limit=0, max_retries=1, backoff=1.01)
        with pytest.raises(TransportError):
            await t.get_json("https://x/api", {})
        await t.aclose()

    async def test_rate_limit_spaces_requests(self) -> None:
        t = DirectTransport(client=client_for(always(200, b"{}")), rate_limit=0.05, max_retries=0)
        import time

        start = time.monotonic()
        await t.get_json("https://x/api", {})
        await t.get_json("https://x/api", {})
        assert time.monotonic() - start >= 0.05
        await t.aclose()

    async def test_bytes_pass_through(self) -> None:
        t = DirectTransport(
            client=client_for(always(200, b"\x00\x01binary", ctype="application/octet-stream")),
            rate_limit=0,
        )
        assert await t.get_bytes("https://x/f.bin", {}) == b"\x00\x01binary"
        await t.aclose()

    async def test_reachability_true_on_any_status(self) -> None:
        """A refusal by the origin is still proof the network works."""
        t = DirectTransport(client=client_for(always(403, b"")), rate_limit=0)
        assert await t.is_reachable() is True
        await t.aclose()

    async def test_reachability_false_on_connect_error(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            raise httpx.ConnectError("refused", request=request)

        t = DirectTransport(client=client_for(handler), rate_limit=0)
        assert await t.is_reachable() is False
        await t.aclose()


class TestProxy:
    async def test_text_proxy_prefixes_the_url(self) -> None:
        seen: list[str] = []

        def handler(request: httpx.Request) -> httpx.Response:
            seen.append(str(request.url))
            return httpx.Response(200, content=b'{"status":"success"}')

        t = ProxyTransport(client=client_for(handler), rate_limit=0, max_retries=0)
        await t.get_json("https://sg.mangatoon.mobi/api/x", {})
        assert seen[0].startswith("https://r.jina.ai/https://sg.mangatoon.mobi/api/x")
        await t.aclose()

    async def test_uses_a_non_browser_user_agent(self) -> None:
        """Read proxies challenge browser UAs, so do not send one."""
        seen: list[str] = []

        def handler(request: httpx.Request) -> httpx.Response:
            seen.append(request.headers.get("user-agent", ""))
            return httpx.Response(200, content=b"{}")

        t = ProxyTransport(client=client_for(handler), rate_limit=0, max_retries=0)
        await t.get_json("https://x/api", {"User-Agent": "Mozilla/5.0 Chrome"})
        assert "Mozilla" not in seen[0]
        assert seen[0] == PROXY_USER_AGENT
        await t.aclose()

    async def test_binary_proxies_are_rotated(self) -> None:
        t = ProxyTransport(rate_limit=0)
        first = await t._next_binary_url("https://cdn/f.bin")
        second = await t._next_binary_url("https://cdn/f.bin")
        assert first[0] != second[0], "each call should start at the next proxy"
        assert sorted(first) == sorted(second), "rotation must not change the set"
        assert len(first) == len(DEFAULT_BINARY_PROXIES)
        await t.aclose()

    async def test_every_candidate_encodes_the_target_once(self) -> None:
        t = ProxyTransport(rate_limit=0)
        for candidate in await t._next_binary_url("https://cdn/f.bin"):
            assert "%3A%2F%2F" in candidate
            assert "%253A" not in candidate, f"double encoded: {candidate}"
        await t.aclose()

    async def test_bytes_tolerate_a_failing_proxy(self) -> None:
        """One throttled proxy must not sink the request."""
        seen: list[str] = []

        def handler(request: httpx.Request) -> httpx.Response:
            host = request.url.host
            seen.append(host)
            if host == "api.cors.lol":
                return httpx.Response(429, content=b"Rate limit")
            return httpx.Response(200, content=b"\x01" * 64)

        t = ProxyTransport(
            client=client_for(handler), rate_limit=0, max_retries=0,
            binary_proxies=("https://api.cors.lol/?url=", "https://ok.example/?url="),
        )
        assert await t.get_bytes("https://cdn/f.bin", {}) == b"\x01" * 64
        assert seen[0] == "api.cors.lol"
        await t.aclose()

    async def test_all_proxies_failing_reports_each(self) -> None:
        t = ProxyTransport(
            client=client_for(always(429, b"Rate limit")),
            rate_limit=0, max_retries=0,
            binary_proxies=("https://a.example/?url=", "https://b.example/?url="),
        )
        with pytest.raises(TransportError) as exc:
            await t.get_bytes("https://cdn/f.bin", {})
        assert "a.example" in str(exc.value)
        assert "b.example" in str(exc.value)
        await t.aclose()

    async def test_no_binary_proxy_configured_raises(self) -> None:
        t = ProxyTransport(rate_limit=0, binary_proxies=())
        with pytest.raises(DirectAccessBlocked):
            await t.get_bytes("https://cdn/f.bin", {})
        await t.aclose()

    async def test_rate_limit_body_triggers_retry_then_gives_up(self) -> None:
        """A 200 whose body is a throttle notice is retried, then reported."""
        calls = {"n": 0}

        def handler(request: httpx.Request) -> httpx.Response:
            calls["n"] += 1
            return httpx.Response(200, content=b"Rate limit exceeded. Try again later.")

        t = ProxyTransport(
            client=client_for(handler), rate_limit=0, max_retries=1, backoff=1.01
        )
        with pytest.raises(TransportError, match="rate limit"):
            await t.get_json("https://x/api", {})
        assert calls["n"] == 2
        await t.aclose()

    async def test_a_success_envelope_mentioning_a_rate_limit_still_parses(self) -> None:
        body = json.dumps({"status": "success", "data": [], "note": "rate limit ok"}).encode()
        t = ProxyTransport(client=client_for(always(200, body)), rate_limit=0, max_retries=0)
        assert (await t.get_json("https://x/api", {}))["status"] == "success"
        await t.aclose()

    async def test_upstream_403_is_surfaced(self) -> None:
        """The proxy answers 200 while the origin answers 403 in the body."""
        body = (
            "Title: \n\nURL Source: https://sg.mangatoon.mobi/api/x\n\n"
            "Warning: Target URL returned error 403: Forbidden\n\n"
            'Markdown Content:\n{"message":"sign error","code":403}\n'
        ).encode()
        t = ProxyTransport(client=client_for(always(200, body)), rate_limit=0, max_retries=0)
        with pytest.raises(APIError) as exc:
            await t.get_json("https://x/api", {})
        assert exc.value.status == 403
        assert "sign error" in str(exc.value)
        await t.aclose()


class TestProxyParsing:
    def test_bare_json(self) -> None:
        assert _parse_json_text('{"a":1}', "u") == {"a": 1}

    def test_json_inside_pre_block(self) -> None:
        assert _parse_json_text('<pre>{"a":1}</pre>', "u") == {"a": 1}

    def test_json_in_markdown_envelope(self) -> None:
        text = 'Title:\n\nURL Source: u\n\nMarkdown Content:\n{"a":1}\n'
        assert _parse_json_text(text, "u") == {"a": 1}

    def test_html_escaped_json(self) -> None:
        assert _parse_json_text('<pre>{"a":"x&amp;y"}</pre>', "u") == {"a": "x&y"}

    def test_upstream_error_reported(self) -> None:
        text = (
            "Warning: Target URL returned error 404: Not Found\n\n"
            'Markdown Content:\n{"message":"not found"}\n'
        )
        with pytest.raises(APIError) as exc:
            _parse_json_text(text, "u")
        assert exc.value.status == 404
        assert "not found" in str(exc.value)

    def test_upstream_error_envelope_is_not_returned_as_data(self) -> None:
        """An error body lacking ``status`` must not look like an API envelope.

        Returning it would skip the error handling that turns the API's
        ``status: "error"`` replies into NotAvailable / APIError.
        """
        text = (
            "Warning: Target URL returned error 500: Internal Server Error\n\n"
            'Markdown Content:\n{"code":500,"message":"boom"}\n'
        )
        with pytest.raises(APIError) as exc:
            _parse_json_text(text, "u")
        assert exc.value.status == 500

    def test_api_error_envelope_passes_through(self) -> None:
        """A real ``status: error`` envelope must survive proxying intact.

        This is the locked-episode shape; the endpoint layer maps it to
        NotAvailable, so it has to reach there as data, not as an exception.
        """
        text = (
            "Warning: Target URL returned error 404: Not Found\n\n"
            "Markdown Content:\n"
            '{"status":"error","error_code":404,'
            '"message":"This episode is not ready for online right now."}\n'
        )
        payload = _parse_json_text(text, "u")
        assert payload["status"] == "error"
        assert payload["error_code"] == 404

    def test_unparseable_raises(self) -> None:
        with pytest.raises(APIError, match="could not locate"):
            _parse_json_text("nothing useful here", "u")

    @pytest.mark.parametrize(
        "text,expected",
        [
            ("RateLimit", True),
            ("429 Too Many Requests", True),
            ("**Error**: Rate limit", True),
            ('{"status":"success"}', False),
        ],
    )
    def test_rate_limit_detection(self, text: str, expected: bool) -> None:
        assert _is_rate_limited(text) is expected


class StubTransport:
    """Minimal transport with controllable reachability."""

    def __init__(self, name: str, reachable: bool) -> None:
        self.name = name
        self._reachable = reachable
        self.calls = 0
        self.closed = False

    async def is_reachable(self) -> bool:
        return self._reachable

    async def get_json(self, url: str, headers: dict[str, str]) -> object:
        self.calls += 1
        if not self._reachable:
            raise TransportError("down", url=url)
        return {"status": "success", "data": [], "via": self.name}

    async def get_bytes(self, url: str, headers: dict[str, str]) -> bytes:
        self.calls += 1
        if not self._reachable:
            raise TransportError("down", url=url)
        return b"ok"

    async def aclose(self) -> None:
        self.closed = True


class TestAuto:
    async def test_prefers_direct_when_reachable(self) -> None:
        direct, proxy = StubTransport("direct", True), StubTransport("proxy", True)
        auto = AutoTransport(direct=direct, proxy=proxy)
        assert (await auto.get_json("u", {}))["via"] == "direct"
        assert auto.active_name == "direct"
        assert proxy.calls == 0
        await auto.aclose()

    async def test_falls_back_to_proxy(self) -> None:
        direct, proxy = StubTransport("direct", False), StubTransport("proxy", True)
        auto = AutoTransport(direct=direct, proxy=proxy)
        assert (await auto.get_json("u", {}))["via"] == "proxy"
        assert auto.active_name == "proxy"
        await auto.aclose()

    async def test_probe_runs_once(self) -> None:
        direct, proxy = StubTransport("direct", False), StubTransport("proxy", True)
        auto = AutoTransport(direct=direct, proxy=proxy)
        await auto.get_json("u", {})
        await auto.get_json("u", {})
        await auto.get_json("u", {})
        assert proxy.calls == 3  # used every time, probed once
        await auto.aclose()

    async def test_demotes_mid_session(self) -> None:
        """A transport that dies after the probe is replaced."""
        direct, proxy = StubTransport("direct", True), StubTransport("proxy", True)
        auto = AutoTransport(direct=direct, proxy=proxy)
        assert (await auto.get_json("u", {}))["via"] == "direct"
        direct._reachable = False  # network changed
        assert (await auto.get_json("u", {}))["via"] == "proxy"
        assert auto.active_name == "proxy"
        await auto.aclose()

    async def test_neither_reachable_raises(self) -> None:
        auto = AutoTransport(
            direct=StubTransport("direct", False), proxy=StubTransport("proxy", False)
        )
        with pytest.raises(DirectAccessBlocked, match="neither"):
            await auto.get_json("u", {})
        await auto.aclose()

    async def test_probe_can_be_disabled(self) -> None:
        """Without a probe, direct is tried first and failure falls back."""
        direct, proxy = StubTransport("direct", False), StubTransport("proxy", True)
        auto = AutoTransport(direct=direct, proxy=proxy, probe=False)
        assert (await auto.get_json("u", {}))["via"] == "proxy"
        assert direct.calls == 1
        assert auto.active_name == "proxy"
        await auto.aclose()

    async def test_closes_both(self) -> None:
        direct, proxy = StubTransport("direct", True), StubTransport("proxy", True)
        auto = AutoTransport(direct=direct, proxy=proxy)
        await auto.aclose()
        assert direct.closed and proxy.closed

    async def test_bytes_route_through_the_active_transport(self) -> None:
        auto = AutoTransport(
            direct=StubTransport("direct", False), proxy=StubTransport("proxy", True)
        )
        assert await auto.get_bytes("u", {}) == b"ok"
        await auto.aclose()
