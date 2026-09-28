"""Shared test fixtures.

Every test runs offline. JSON responses and obfuscated payloads were recorded
from the live API; the corresponding ``dec_*.txt`` files are the known-good
plaintext used as a decryption oracle.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Callable

import pytest

FIXTURES = Path(__file__).parent / "fixtures"


def load_json(name: str) -> Any:
    """Load a recorded API response."""
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def load_bytes(name: str) -> bytes:
    """Load a recorded binary payload."""
    return (FIXTURES / name).read_bytes()


def load_text(name: str) -> str:
    """Load known-good plaintext for a recorded payload."""
    return (FIXTURES / name).read_text(encoding="utf-8")


@pytest.fixture
def fixtures_dir() -> Path:
    return FIXTURES


@pytest.fixture
def read_json() -> Callable[[str], Any]:
    return load_json


class FakeTransport:
    """Records requests and replays canned responses.

    Lets the whole client be exercised without a network. Set ``json_by_path``
    and ``bytes_by_url`` to control what comes back.
    """

    def __init__(
        self,
        *,
        json_by_path: dict[str, Any] | None = None,
        bytes_by_url: dict[str, bytes] | None = None,
        default_json: Any = None,
        name: str = "fake",
    ) -> None:
        self.name = name
        # Keys may be given as a path ("/api/content/detail") or an endpoint
        # name ("content/detail"); the latter avoids hardcoding the host.
        self.json_by_path = {
            self._normalise(key): value for key, value in (json_by_path or {}).items()
        }
        self.bytes_by_url = bytes_by_url or {}
        self.default_json = default_json
        self.json_calls: list[str] = []
        self.byte_calls: list[str] = []
        self.closed = False

    @staticmethod
    def _normalise(key: str) -> str:
        if not key.startswith("/"):
            return f"/api/{key}"
        return key

    async def get_json(self, url: str, headers: dict[str, str]) -> Any:
        self.json_calls.append(url)
        # Strip scheme, host and query so keys are plain endpoint paths.
        from urllib.parse import urlsplit

        path = urlsplit(url).path
        if path in self.json_by_path:
            return self.json_by_path[path]
        if self.default_json is not None:
            return self.default_json
        raise AssertionError(f"no canned JSON response for {path}")

    async def get_bytes(self, url: str, headers: dict[str, str]) -> bytes:
        self.byte_calls.append(url)
        if url in self.bytes_by_url:
            return self.bytes_by_url[url]
        raise AssertionError(f"no canned bytes for {url}")

    async def aclose(self) -> None:
        self.closed = True


@pytest.fixture
def fake_transport() -> FakeTransport:
    return FakeTransport()
