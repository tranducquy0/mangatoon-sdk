"""Endpoint wrappers: signed API calls mapped onto models.

Every method here takes a :class:`~mangatoon._transport.Transport`, signs its
own request, and turns the response into model objects. Chapter payloads are
fetched as bytes and decrypted; see :mod:`mangatoon._crypto`.
"""

from __future__ import annotations

from typing import Any, Mapping, Sequence
from urllib.parse import quote

from ._crypto import decrypt
from ._exceptions import APIError, NotAvailable, PaymentRequired, ValidationError
from ._models import (
    BrowsePage,
    ChatChapter,
    ComicPage,
    Comment,
    ContentType,
    Episode,
    NovelChapter,
    Series,
    SeriesSummary,
)
from ._signing import api_headers, sign_url
from ._text import load_chat_document, split_markdown, split_plain
from ._transport import Transport
from ._urls import comic_page_url

__all__ = ["Api"]

#: ``/api/content/list`` rejects ``page=0``; it is 1-indexed.
_FIRST_PAGE = 1

#: Upper bound the API accepts for ``limit``.
MAX_LIMIT = 500


#: Exact wording the API uses for a locked or unpublished episode.
LOCKED_MESSAGE = "This episode is not ready for online right now."


def _unwrap(payload: Any, url: str) -> Any:
    """Return the ``data`` member, raising on an error envelope."""
    if not isinstance(payload, Mapping):
        raise APIError(f"unexpected response shape for {url}", payload=payload)

    status = payload.get("status")
    if status not in (None, "success"):
        code = payload.get("code")
        message = payload.get("readableMessage") or payload.get("message") or payload.get("reason")
        detail = f"API returned status={status!r} code={code!r}: {message}"
        if code in (40001, 40002) or "validator" in str(message).lower():
            raise ValidationError(detail, status=code, code=code, payload=payload)
        raise APIError(detail, status=code, code=code, payload=payload)

    return payload.get("data")


def _guard_unavailable(payload: Mapping[str, Any], episode_id: int) -> None:
    """Raise :class:`NotAvailable` for the API's locked-episode response.

    A locked episode and a nonexistent id both return ``status: "error"`` with
    ``error_code: 404`` and no ``data``. The only signal that separates them is
    the message wording, so ``looks_locked`` reports whether it matched rather
    than treating the distinction as certain.
    """
    if payload.get("status") == "success":
        return
    message = str(payload.get("message") or payload.get("readableMessage") or "")
    if payload.get("error_code") == 404 or "not found" in message.lower() or "not ready" in message.lower():
        raise NotAvailable(
            message or "episode is unavailable",
            episode_id=episode_id,
            content_id=_as_int(payload.get("content_id")),
            looks_locked=LOCKED_MESSAGE in message,
        )


def _normalise_page(page: int) -> int:
    if page < _FIRST_PAGE:
        raise ValueError(f"page is 1-indexed; got {page}")
    return page


def _clamp_limit(limit: int | None, default: int) -> int:
    if limit is None:
        return default
    if limit < 1:
        raise ValueError(f"limit must be positive; got {limit}")
    return min(limit, MAX_LIMIT)


class Api:
    """Thin, typed wrapper over the signed MangaToon API."""

    def __init__(
        self,
        transport: Transport,
        *,
        language: str = "en",
        udid: str | None = None,
        version: str | None = None,
        timestamp: int | None = None,
    ) -> None:
        self._transport = transport
        self._language = language
        self._udid = udid
        self._version = version
        self._timestamp = timestamp

    def _url(self, path: str, params: Mapping[str, Any]) -> str:
        envelope: dict[str, Any] = {"language": self._language}
        if self._udid is not None:
            envelope["udid"] = self._udid
        if self._version is not None:
            envelope["version"] = self._version
        if self._timestamp is not None:
            envelope["timestamp"] = self._timestamp
        return sign_url(path, dict(params), **envelope)

    async def _get(self, path: str, params: Mapping[str, Any]) -> Any:
        url = self._url(path, params)
        payload = await self._transport.get_json(url, api_headers())
        return _unwrap(payload, url)

    async def _get_envelope(self, path: str, params: Mapping[str, Any], page: int) -> Any:
        url = self._url(path, params)
        payload = await self._transport.get_json(url, api_headers())
        _unwrap(payload, url)  # validate the envelope before reading counters
        return payload

    async def _get_flat(self, path: str, params: Mapping[str, Any]) -> Mapping[str, Any]:
        """Fetch an endpoint whose metadata is the response body itself.

        ``/api/fictions/content`` and ``/api/cartoons/pictures`` do not nest
        their records: the fields sit at the top level and ``data`` holds only
        the payload URL (or the page list). Unwrapping to ``data`` would discard
        the metadata.
        """
        url = self._url(path, params)
        payload = await self._transport.get_json(url, api_headers())
        _unwrap(payload, url)  # validate the envelope
        if not isinstance(payload, Mapping):
            raise APIError(f"unexpected response shape for {url}", payload=payload)
        return payload

    async def _fetch_payload(self, url: str) -> bytes:
        return await self._transport.get_bytes(url, {})

    # -- series ---------------------------------------------------------

    async def detail(self, content_id: int) -> Series:
        """Full metadata for one series of any type."""
        data = await self._get("/api/content/detail", {"id": content_id})
        if not isinstance(data, Mapping):
            raise APIError(f"detail for {content_id} did not return an object")
        return Series.from_api(data)

    async def episodes(self, content_id: int) -> list[Episode]:
        """Every episode of a series, oldest first.

        Chat-story episode lists are served here even though the website hides
        them.
        """
        data = await self._get("/api/content/episodes", {"id": content_id})
        if data is None:
            return []
        return [Episode.from_api(item) for item in data if isinstance(item, Mapping)]

    async def search(
        self,
        word: str,
        *,
        type: ContentType | int | None = None,
        page: int = _FIRST_PAGE,
        limit: int | None = 20,
    ) -> BrowsePage:
        """Search titles.

        With ``type`` omitted the API returns chat stories first, so pass the
        type to search a specific catalogue.
        """
        page = _normalise_page(page)
        params: dict[str, Any] = {
            "word": word,
            "page": page,
            "limit": _clamp_limit(limit, 20),
        }
        if type is not None:
            params["type"] = int(type)
        payload = await self._get_envelope("/api/content/search", params, page)
        return BrowsePage.from_api(payload, page)

    async def browse(
        self,
        *,
        type: ContentType | int | None = None,
        page: int = _FIRST_PAGE,
        limit: int | None = 20,
        order: str = "hot",
        tag_id: int | None = None,
        defined_type: str | int | None = None,
    ) -> BrowsePage:
        """List series in a catalogue.

        Args:
            type: Catalogue to list. ``NOVEL``, ``CHAT_STORY`` or ``COMIC``.
            order: ``hot`` or ``new``.
            tag_id: Restrict to a tag.
            defined_type: Additional catalogue filter used by the app.
        """
        page = _normalise_page(page)
        params: dict[str, Any] = {
            "page": page,
            "limit": _clamp_limit(limit, 20),
            "order": order,
        }
        if type is not None:
            params["type"] = int(type)
        if tag_id is not None:
            params["tag_id"] = tag_id
        if defined_type is not None:
            params["defined_type"] = defined_type
        payload = await self._get_envelope("/api/content/list", params, page)
        return BrowsePage.from_api(payload, page)

    async def iter_search(
        self,
        word: str,
        *,
        type: ContentType | int | None = None,
        limit: int = 20,
        max_pages: int | None = None,
    ) -> Any:
        """Yield search result pages until exhausted or ``max_pages``."""
        page = _FIRST_PAGE
        seen = 0
        while max_pages is None or seen < max_pages:
            batch = await self.search(word, type=type, page=page, limit=limit)
            if not batch.items:
                return
            yield batch
            seen += 1
            if not batch.has_next:
                return
            page = batch.next_page or page + 1

    async def iter_browse(
        self,
        *,
        type: ContentType | int | None = None,
        limit: int = 20,
        order: str = "hot",
        tag_id: int | None = None,
        defined_type: str | int | None = None,
        max_pages: int | None = None,
    ) -> Any:
        """Yield browse pages until exhausted or ``max_pages``."""
        page = _FIRST_PAGE
        seen = 0
        while max_pages is None or seen < max_pages:
            batch = await self.browse(
                type=type, page=page, limit=limit, order=order,
                tag_id=tag_id, defined_type=defined_type,
            )
            if not batch.items:
                return
            yield batch
            seen += 1
            if not batch.has_next:
                return
            page = batch.next_page or page + 1

    # -- chapter payloads ------------------------------------------------

    async def _fiction_meta(self, episode_id: int) -> Mapping[str, Any]:
        """Fetch the metadata record that points at a chapter's payload."""
        url = self._url("/api/fictions/content", {"id": episode_id})
        payload = await self._transport.get_json(url, api_headers())
        if not isinstance(payload, Mapping):
            raise APIError(f"unexpected response shape for {url}", payload=payload)
        _guard_unavailable(payload, episode_id)
        _unwrap(payload, url)
        # A fee episode can also come back flagged with no payload to read.
        if payload.get("is_fee") and not payload.get("data"):
            raise PaymentRequired(episode_id, content_id=_as_int(payload.get("content_id")))
        return payload

    async def get_novel_chapter(
        self,
        episode_id: int,
        *,
        markdown: bool = False,
    ) -> NovelChapter:
        """Fetch and decode a novel chapter.

        Args:
            episode_id: Episode to read.
            markdown: Also fetch the markdown variant when the API offers one.
                Paragraphs come from the plain payload either way.

        Raises:
            NotAvailable: If the episode is locked or unpublished.
            PaymentRequired: If it is flagged paid yet carries no payload.
        """
        meta = await self._fiction_meta(episode_id)
        plain_url = meta.get("data")
        if not plain_url:
            raise PaymentRequired(episode_id, content_id=_as_int(meta.get("content_id")))

        body = decrypt(await self._fetch_payload(plain_url))
        paragraphs = split_plain(_to_text(body))

        md_text: str | None = None
        md_url = meta.get("markdown_data_url")
        if markdown and md_url:
            md_body = decrypt(await self._fetch_payload(md_url))
            md_text = _to_text(md_body)
            # Trust the markdown variant when it is the richer of the two.
            md_paragraphs = split_markdown(md_text)
            if len(md_paragraphs) > len(paragraphs):
                paragraphs = md_paragraphs

        return NovelChapter.from_api(meta, paragraphs, md_text)

    async def get_chat_chapter(self, episode_id: int) -> ChatChapter:
        """Fetch and decode a chat story chapter.

        Chat stories have no web reader; this endpoint is the only route to
        their text.

        Raises:
            NotAvailable: If the episode is locked or unpublished.
            PaymentRequired: If it is flagged paid yet carries no payload.
        """
        meta = await self._fiction_meta(episode_id)
        url = meta.get("data")
        if not url:
            raise PaymentRequired(episode_id, content_id=_as_int(meta.get("content_id")))

        document = load_chat_document(decrypt(await self._fetch_payload(url)))
        return ChatChapter.from_api(meta, document)

    async def get_comic_pages(self, episode_id: int) -> list[ComicPage]:
        """Fetch the page list of a comic episode, as directly fetchable URLs.

        The API returns ``/encrypted/.../name.webp`` URLs; each is rewritten to
        the ``/watermark/.../name.jpg`` form the reader uses, so the bytes need
        no decryption.

        Raises:
            NotAvailable: If the episode is locked or unpublished.
            PaymentRequired: If it is flagged paid yet carries no payload.
        """
        url = self._url("/api/cartoons/pictures", {"id": episode_id})
        payload = await self._transport.get_json(url, api_headers())
        if not isinstance(payload, Mapping):
            raise APIError(f"unexpected response shape for {url}", payload=payload)
        _guard_unavailable(payload, episode_id)
        _unwrap(payload, url)
        if payload.get("is_fee") and not payload.get("data"):
            raise PaymentRequired(episode_id, content_id=_as_int(payload.get("content_id")))

        data = payload.get("data")
        if isinstance(data, Mapping):
            # Defensive: a nested object rather than a list.
            data = data.get("data")
        if not data:
            raise PaymentRequired(episode_id)

        pages: list[ComicPage] = []
        for item in data:
            if not isinstance(item, Mapping):
                continue
            original = item.get("url")
            if not original:
                continue
            pages.append(ComicPage.from_api(item, comic_page_url(str(original)), str(original)))
        return pages

    # -- misc ------------------------------------------------------------

    async def comments(self, content_id: int, *, page: int = _FIRST_PAGE, limit: int = 20) -> list[Comment]:
        """Reader comments for a series or episode."""
        payload = await self._get(
            "/api/comments/index",
            {"content_id": content_id, "page": _normalise_page(page), "limit": _clamp_limit(limit, 20)},
        )
        if isinstance(payload, Mapping):
            payload = payload.get("data") or payload.get("list") or []
        return [Comment.from_api(item) for item in payload or () if isinstance(item, Mapping)]


def _as_int(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _to_text(body: bytes) -> str:
    return body.decode("utf-8", errors="replace").strip("\ufeff").strip()
