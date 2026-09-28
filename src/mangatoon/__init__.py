"""Python SDK for the MangaToon / NovelToon content API.

Retrieves comics, novels and chat stories, including the chapter text that the
website does not otherwise expose.

    >>> import asyncio
    >>> from mangatoon import MangaToon, ContentType
    >>>
    >>> async def main() -> None:
    ...     async with MangaToon(language="en") as mt:
    ...         results = await mt.search("romance", type=ContentType.CHAT_STORY)
    ...         for item in results:
    ...             print(item.id, item.title)
    >>>
    >>> asyncio.run(main())

Chapter readers are separate per content type, since the payloads differ:

    * :meth:`MangaToon.get_comic_pages` for comics
    * :meth:`MangaToon.get_novel_chapter` for novels
    * :meth:`MangaToon.get_chat_chapter` for chat stories
"""

from __future__ import annotations

from ._client import MangaToon
from ._crypto import decrypt, detect_offset
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
from ._urls import comic_page_url

__version__ = "0.1.0"

__all__ = [
    "__version__",
    "MangaToon",
    "ContentType",
    # models
    "Author",
    "BrowsePage",
    "ChatChapter",
    "ChatMessage",
    "ChatMessageType",
    "Character",
    "ComicPage",
    "Comment",
    "Episode",
    "NovelChapter",
    "Series",
    "SeriesSummary",
    "Tag",
    # transports
    "AutoTransport",
    "DirectTransport",
    "ProxyTransport",
    "Transport",
    # errors
    "MangaToonError",
    "APIError",
    "ValidationError",
    "TransportError",
    "DirectAccessBlocked",
    "PaymentRequired",
    "NotAvailable",
    "DecryptionError",
    # helpers
    "comic_page_url",
    "decrypt",
    "detect_offset",
]
