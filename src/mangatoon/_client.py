"""MangaToon client: the public entry point of the SDK."""

from __future__ import annotations

from types import TracebackType
from typing import Any, Sequence

from ._endpoints import Api
from ._exceptions import (
    APIError,
    DecryptionError,
    DirectAccessBlocked,
    MangaToonError,
    NotAvailable,
    PaymentRequired,
    TransportError,
    ValidationError,
)
from ._models import (
    Author,
    BrowsePage,
    ChatChapter,
    ChatMessage,
    ChatMessageType,
    Character,
    ComicPage,
    Comment,
    ContentType,
    Episode,
    NovelChapter,
    Series,
    SeriesSummary,
    Tag,
)
from ._transport import AutoTransport, DirectTransport, ProxyTransport, Transport

__all__ = ["MangaToon", "ContentType"]


class MangaToon:
    """Async client for the MangaToon / NovelToon content API.

    Example:
        >>> async with MangaToon() as mt:
        ...     series = await mt.get_detail(6067953)
        ...     episodes = await mt.episodes(6067953)
        ...     chapter = await mt.get_chat_chapter(episodes[0].id)

    Args:
        language: Content language code, e.g. ``en``, ``id``, ``es``.
        transport: ``"auto"`` (default), ``"direct"``, ``"proxy"``, or a custom
            :class:`~mangatoon._transport.Transport`.
        udid: Anonymous device id. Not tied to an account; the default is
            shared by all anonymous users.
        version: API version string to advertise. Only override when the
            default is rejected.
        timeout: Per-request timeout in seconds.
        rate_limit: Minimum seconds between requests. The origin is throttled,
            so 1.0 is a safe floor.
        max_retries: Retries per request before giving up.
        timestamp: Pin the ``_`` signing parameter, for reproducible requests.
    """

    def __init__(
        self,
        *,
        language: str = "en",
        transport: str | Transport = "auto",
        udid: str | None = None,
        version: str | None = None,
        timeout: float = 30.0,
        rate_limit: float = 1.0,
        max_retries: int = 3,
        timestamp: int | None = None,
        **transport_kwargs: Any,
    ) -> None:
        self.language = language
        self._api = Api(
            self._build_transport(transport, timeout, rate_limit, max_retries, transport_kwargs),
            language=language,
            udid=udid,
            version=version,
            timestamp=timestamp,
        )

    @staticmethod
    def _build_transport(
        kind: str | Transport,
        timeout: float,
        rate_limit: float,
        max_retries: int,
        extra: dict[str, Any],
    ) -> Transport:
        if not isinstance(kind, str):
            return kind

        options: dict[str, Any] = {
            "timeout": timeout,
            "rate_limit": rate_limit,
            "max_retries": max_retries,
            **extra,
        }
        match kind:
            case "auto":
                return AutoTransport(**options)
            case "direct":
                return DirectTransport(**options)
            case "proxy":
                return ProxyTransport(**options)
            case _:
                raise ValueError(
                    f"unknown transport {kind!r}; expected 'auto', 'direct', 'proxy' or a Transport"
                )

    @property
    def transport_name(self) -> str:
        """Name of the transport actually in use."""
        return self._api._transport.name

    @property
    def active_transport_name(self) -> str:
        """Name of the transport selected by auto-detection."""
        return getattr(self._api._transport, "active_name", self._api._transport.name)

    # -- series ----------------------------------------------------------

    async def get_detail(self, content_id: int) -> Series:
        """Full metadata for one series, of any type.

        Args:
            content_id: Numeric series id.
        """
        return await self._api.detail(content_id)

    async def episodes(self, content_id: int) -> list[Episode]:
        """Every episode of a series, oldest first.

        Chat-story episode lists are returned here even though the website
        does not expose them.
        """
        return await self._api.episodes(content_id)

    async def search(
        self,
        word: str,
        *,
        type: ContentType | None = None,
        page: int = 1,
        limit: int | None = 20,
    ) -> BrowsePage:
        """Search titles.

        Pass ``type`` to search one catalogue: without it the API ranks chat
        stories first.
        """
        return await self._api.search(word, type=type, page=page, limit=limit)

    async def browse(
        self,
        *,
        type: ContentType | None = None,
        page: int = 1,
        limit: int | None = 20,
        order: str = "hot",
        tag_id: int | None = None,
        defined_type: int | str | None = None,
    ) -> BrowsePage:
        """List a catalogue: ``NOVEL``, ``CHAT_STORY`` or ``COMIC``.

        Args:
            order: ``hot`` for ranking, ``new`` for recency.
        """
        return await self._api.browse(
            type=type, page=page, limit=limit, order=order,
            tag_id=tag_id, defined_type=defined_type,
        )

    def iter_search(
        self,
        word: str,
        *,
        type: ContentType | None = None,
        limit: int = 20,
        max_pages: int | None = None,
    ) -> Any:
        """Async-iterate search result pages."""
        return self._api.iter_search(word, type=type, limit=limit, max_pages=max_pages)

    def iter_browse(
        self,
        *,
        type: ContentType | None = None,
        limit: int = 20,
        order: str = "hot",
        tag_id: int | None = None,
        defined_type: int | str | None = None,
        max_pages: int | None = None,
    ) -> Any:
        """Async-iterate browse pages."""
        return self._api.iter_browse(
            type=type, limit=limit, order=order, tag_id=tag_id,
            defined_type=defined_type, max_pages=max_pages,
        )

    # -- per-type chapter readers ---------------------------------------

    async def get_novel_chapter(
        self,
        episode_id: int,
        *,
        markdown: bool = False,
    ) -> NovelChapter:
        """Read a novel chapter.

        Args:
            episode_id: Episode to read.
            markdown: Additionally fetch the markdown variant when offered.
                The richer of the two decodes into ``paragraphs``.

        Raises:
            NotAvailable: If the episode is locked or unpublished.
            PaymentRequired: If it is flagged paid yet carries no payload.
        """
        return await self._api.get_novel_chapter(episode_id, markdown=markdown)

    async def get_chat_chapter(self, episode_id: int) -> ChatChapter:
        """Read a chat story chapter.

        Chat stories are API-only; there is no web reader to scrape.

        Raises:
            NotAvailable: If the episode is locked or unpublished.
            PaymentRequired: If it is flagged paid yet carries no payload.
        """
        return await self._api.get_chat_chapter(episode_id)

    async def get_comic_pages(self, episode_id: int) -> list[ComicPage]:
        """List a comic episode's pages as directly fetchable URLs.

        The returned URLs need no decryption; download them as-is.

        Raises:
            NotAvailable: If the episode is locked or unpublished.
            PaymentRequired: If it is flagged paid yet carries no payload.
        """
        return await self._api.get_comic_pages(episode_id)

    # -- misc ------------------------------------------------------------

    async def comments(self, content_id: int, *, page: int = 1, limit: int = 20) -> list[Comment]:
        """Reader comments for a series."""
        return await self._api.comments(content_id, page=page, limit=limit)

    async def fetch_bytes(self, url: str) -> bytes:
        """Fetch a CDN URL through the configured transport.

        Comic page images are public CDN files that need no signing, but they
        live on the same hosts as the API, so they go through the transport:
        that keeps them working when the origin needs a proxy.
        """
        return await self._api._transport.get_bytes(url, {})

    async def aclose(self) -> None:
        """Release the underlying HTTP connections."""
        await self._api._transport.aclose()

    async def __aenter__(self) -> "MangaToon":
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        await self.aclose()
