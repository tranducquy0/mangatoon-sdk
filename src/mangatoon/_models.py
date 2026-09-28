"""Typed models for MangaToon API responses.

Frozen dataclasses, mapped by hand from the documented response shapes. Mapping
is deliberately lenient: fields the API omits fall back to ``None`` rather than
raising, because the payloads vary between content types and change over time.
Unknown keys are ignored.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import IntEnum
from typing import Any, Mapping, Sequence

__all__ = [
    "ContentType",
    "Author",
    "Tag",
    "FirstEpisode",
    "Series",
    "SeriesSummary",
    "Episode",
    "BrowsePage",
    "Character",
    "ChatMessage",
    "ChatChapter",
    "NovelChapter",
    "ComicPage",
    "Comment",
]


class ContentType(IntEnum):
    """The ``type`` field of a content record."""

    COMIC = 1
    NOVEL = 2
    CHAT_STORY = 4

    @property
    def is_text(self) -> bool:
        """Whether the type is read as prose rather than images."""
        return self in (ContentType.NOVEL, ContentType.CHAT_STORY)

    @classmethod
    def coerce(cls, value: Any) -> "ContentType | None":
        """Best-effort conversion; ``None`` for unknown values."""
        try:
            return cls(int(value))
        except (TypeError, ValueError):
            return None


def _str(payload: Mapping[str, Any], key: str) -> str | None:
    value = payload.get(key)
    if value is None or value == "":
        return None
    return str(value)


def _int(payload: Mapping[str, Any], key: str) -> int | None:
    value = payload.get(key)
    if value is None or isinstance(value, bool):
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _bool(payload: Mapping[str, Any], key: str, default: bool | None = None) -> bool | None:
    value = payload.get(key)
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes"}
    return default


@dataclass(frozen=True, slots=True)
class Author:
    """A series author."""

    id: int | None = None
    user_id: int | None = None
    name: str | None = None
    image_url: str | None = None

    @classmethod
    def from_api(cls, payload: Mapping[str, Any] | None) -> "Author | None":
        if not payload:
            return None
        return cls(
            id=_int(payload, "id"),
            user_id=_int(payload, "user_id"),
            name=_str(payload, "name"),
            image_url=_str(payload, "image_url"),
        )


@dataclass(frozen=True, slots=True)
class Tag:
    """A genre or fandom tag."""

    id: int | None = None
    name: str | None = None
    type: int | None = None

    @classmethod
    def from_api(cls, payload: Mapping[str, Any]) -> "Tag":
        return cls(
            id=_int(payload, "id"),
            name=_str(payload, "name"),
            type=_int(payload, "type"),
        )


@dataclass(frozen=True, slots=True)
class FirstEpisode:
    """Pointer to a series' opening episode."""

    id: int | None = None
    title: str | None = None

    @classmethod
    def from_api(cls, payload: Mapping[str, Any] | None) -> "FirstEpisode | None":
        if not payload:
            return None
        return cls(id=_int(payload, "id"), title=_str(payload, "title"))


@dataclass(frozen=True, slots=True)
class Series:
    """Full detail record for a comic, novel or chat story."""

    id: int
    title: str
    type: ContentType | None
    description: str | None = None
    content_description: str | None = None
    author: Author | None = None
    cover_url: str | None = None
    big_cover_url: str | None = None
    tags: tuple[Tag, ...] = ()
    category_id: int | None = None
    category_name: str | None = None
    episode_count: int | None = None
    first_episode: FirstEpisode | None = None
    first_fee_episode_index: int | None = None
    is_end: bool | None = None
    is_mature: bool | None = None
    is_deleted: bool | None = None
    is_contribute: bool | None = None
    disable_download: bool | None = None
    gender: int | None = None
    status: int | None = None
    age_level: int | None = None
    price: int | None = None
    watch_count: int | None = None
    like_count: int | None = None
    comment_count: int | None = None
    favorite_count: int | None = None
    reward_count: int | None = None
    score: float | None = None
    score_count: int | None = None
    created_at: str | None = None
    updated_at: int | None = None
    announcement: str | None = None
    share_url: str | None = None

    @classmethod
    def from_api(cls, payload: Mapping[str, Any]) -> "Series":
        score = payload.get("score")
        return cls(
            id=_int(payload, "id") or 0,
            title=_str(payload, "title") or "",
            type=ContentType.coerce(payload.get("type")),
            description=_str(payload, "description"),
            content_description=_str(payload, "content_description"),
            author=Author.from_api(payload.get("author")),
            cover_url=_str(payload, "image_url") or _str(payload, "image_path"),
            big_cover_url=_str(payload, "big_image_url"),
            tags=tuple(Tag.from_api(t) for t in payload.get("tags") or () if isinstance(t, Mapping)),
            category_id=_int(payload, "category_id"),
            category_name=_str(payload, "category_name"),
            episode_count=_int(payload, "open_episodes_count"),
            first_episode=FirstEpisode.from_api(payload.get("first_episode")),
            first_fee_episode_index=_int(payload, "first_fee_episode_index"),
            is_end=_bool(payload, "is_end"),
            is_mature=_bool(payload, "is_mature"),
            is_deleted=_bool(payload, "is_deleted"),
            is_contribute=_bool(payload, "is_contribute"),
            disable_download=_bool(payload, "disable_download"),
            gender=_int(payload, "gender"),
            status=_int(payload, "status"),
            age_level=_int(payload, "age_level"),
            price=_int(payload, "price"),
            watch_count=_int(payload, "watch_count"),
            like_count=_int(payload, "like_count"),
            comment_count=_int(payload, "comment_count"),
            favorite_count=_int(payload, "favorite_count"),
            reward_count=_int(payload, "reward_count"),
            score=float(score) if isinstance(score, (int, float)) else None,
            score_count=_int(payload, "score_count"),
            created_at=_str(payload, "created_at"),
            updated_at=_int(payload, "updated_at"),
            announcement=_str(payload, "announcement"),
            share_url=_str(payload, "share_url"),
        )

    @property
    def tag_names(self) -> tuple[str, ...]:
        """Tag labels in declaration order."""
        return tuple(tag.name for tag in self.tags if tag.name)


@dataclass(frozen=True, slots=True)
class SeriesSummary:
    """A reduced series record as returned by search and browse listings."""

    id: int
    title: str
    type: ContentType | None
    author: Author | None = None
    cover_url: str | None = None
    description: str | None = None
    tags: tuple[Tag, ...] = ()
    episode_count: int | None = None
    is_end: bool | None = None
    updated_at: int | None = None
    watch_count: int | None = None
    like_count: int | None = None
    comment_count: int | None = None
    score: float | None = None

    @classmethod
    def from_api(cls, payload: Mapping[str, Any]) -> "SeriesSummary":
        score = payload.get("score")
        return cls(
            id=_int(payload, "id") or 0,
            title=_str(payload, "title") or "",
            type=ContentType.coerce(payload.get("type")),
            author=Author.from_api(payload.get("author")),
            cover_url=_str(payload, "image_url"),
            description=_str(payload, "description"),
            tags=tuple(Tag.from_api(t) for t in payload.get("tags") or () if isinstance(t, Mapping)),
            episode_count=_int(payload, "open_episodes_count"),
            is_end=_bool(payload, "is_end"),
            updated_at=_int(payload, "updated_at"),
            watch_count=_int(payload, "watch_count"),
            like_count=_int(payload, "like_count"),
            comment_count=_int(payload, "comment_count"),
            score=float(score) if isinstance(score, (int, float)) else None,
        )


@dataclass(frozen=True, slots=True)
class Episode:
    """A single chapter of any content type.

    ``is_fee`` marks a paywalled chapter. The SDK surfaces it rather than
    attempting any bypass.
    """

    id: int
    title: str
    weight: int | None = None
    open_at: int | None = None
    is_fee: bool = False
    is_mature: bool = False
    has_video: bool = False
    like_count: int | None = None
    comment_count: int | None = None
    file_size: int | None = None

    @classmethod
    def from_api(cls, payload: Mapping[str, Any]) -> "Episode":
        return cls(
            id=_int(payload, "id") or 0,
            title=_str(payload, "title") or "",
            weight=_int(payload, "weight"),
            open_at=_int(payload, "open_at"),
            is_fee=bool(_bool(payload, "is_fee", False)),
            is_mature=bool(_bool(payload, "is_mature", False)),
            has_video=bool(_bool(payload, "has_video", False)),
            like_count=_int(payload, "like_count"),
            comment_count=_int(payload, "comment_count"),
            file_size=_int(payload, "file_size"),
        )


@dataclass(frozen=True, slots=True)
class BrowsePage:
    """One page of a search or browse result set."""

    items: tuple[SeriesSummary, ...] = ()
    page: int = 1
    page_count: int | None = None
    total_count: int | None = None
    next_page: int | None = None
    per_page: int | None = None
    authors: tuple[Author, ...] = ()

    def __len__(self) -> int:
        return len(self.items)

    def __iter__(self) -> Any:
        return iter(self.items)

    @property
    def has_next(self) -> bool:
        """Whether another page is advertised."""
        if self.next_page is not None:
            return bool(self.next_page)
        if self.page_count is not None and self.page is not None:
            return self.page < self.page_count
        return False

    @classmethod
    def from_api(cls, payload: Mapping[str, Any], page: int = 1) -> "BrowsePage":
        return cls(
            items=tuple(
                SeriesSummary.from_api(item) for item in payload.get("data") or () if isinstance(item, Mapping)
            ),
            page=page,
            page_count=_int(payload, "page_count"),
            total_count=_int(payload, "total_count"),
            next_page=_int(payload, "next_page"),
            per_page=_int(payload, "items_count_per_page"),
            authors=tuple(
                a for a in (Author.from_api(item) for item in payload.get("authors") or ()) if a
            ),
        )


@dataclass(frozen=True, slots=True)
class Character:
    """A named participant in a chat story."""

    id: int
    name: str | None = None
    type: int | None = None
    status: int | None = None
    avatar_url: str | None = None

    @classmethod
    def from_api(cls, payload: Mapping[str, Any]) -> "Character":
        return cls(
            id=_int(payload, "id") or 0,
            name=_str(payload, "name"),
            type=_int(payload, "type"),
            status=_int(payload, "status"),
            avatar_url=_str(payload, "avatar_url"),
        )


class ChatMessageType(IntEnum):
    """Render style of a chat story bubble."""

    NARRATION = 1
    DIALOGUE = 2
    IMAGE = 3


@dataclass(frozen=True, slots=True)
class ChatMessage:
    """One bubble or narration block in a chat story chapter.

    ``character_id`` of ``0`` means the narrator. Use :attr:`ChatChapter.character`
    to resolve a name.
    """

    id: int
    type: ChatMessageType
    character_id: int = 0
    position: int = 0
    content: str | None = None
    image_path: str | None = None
    image_url: str | None = None
    image_width: int | None = None
    image_height: int | None = None

    @property
    def is_narration(self) -> bool:
        return self.type == ChatMessageType.NARRATION

    @property
    def is_dialogue(self) -> bool:
        return self.type == ChatMessageType.DIALOGUE

    @property
    def is_image(self) -> bool:
        return self.type == ChatMessageType.IMAGE

    @classmethod
    def from_api(cls, payload: Mapping[str, Any]) -> "ChatMessage":
        try:
            kind = ChatMessageType(int(payload.get("type", 1)))
        except (TypeError, ValueError):
            kind = ChatMessageType.NARRATION
        return cls(
            id=_int(payload, "id") or 0,
            type=kind,
            character_id=_int(payload, "character_id") or 0,
            position=_int(payload, "position") or 0,
            content=_str(payload, "content"),
            image_path=_str(payload, "image_path"),
            image_width=_int(payload, "image_width"),
            image_height=_int(payload, "image_height"),
        )


@dataclass(frozen=True, slots=True)
class ChatChapter:
    """A decoded chat story chapter.

    Chat stories have no web reader; this is the only way to read them.
    """

    episode_id: int
    content_id: int
    title: str | None = None
    messages: tuple[ChatMessage, ...] = ()
    characters: tuple[Character, ...] = ()
    next_episode_id: int | None = None
    is_end: bool | None = None

    def character(self, character_id: int) -> Character | None:
        """Look up a character by id, or ``None`` for the narrator."""
        for entry in self.characters:
            if entry.id == character_id:
                return entry
        return None

    def speaker(self, message: ChatMessage) -> str | None:
        """Display name for a message, or ``None`` when it is narration."""
        if message.character_id == 0:
            return None
        found = self.character(message.character_id)
        return found.name if found else None

    def render(self) -> str:
        """Plain-text transcript with speaker names inlined."""
        lines: list[str] = []
        for message in self.messages:
            if message.is_image:
                lines.append(f"[image: {message.image_url or message.image_path or ''}]")
                continue
            body = (message.content or "").strip()
            if not body:
                continue
            name = self.speaker(message)
            lines.append(f"{name}: {body}" if name else body)
        return "\n\n".join(lines)

    @classmethod
    def from_api(
        cls,
        payload: Mapping[str, Any],
        document: Mapping[str, Any],
    ) -> "ChatChapter":
        messages = document.get("messages") or ()
        next_episode = payload.get("next")
        return cls(
            episode_id=_int(payload, "episode_id") or 0,
            content_id=_int(payload, "content_id") or 0,
            title=_str(payload, "episode_title"),
            messages=tuple(
                ChatMessage.from_api(m) for m in messages if isinstance(m, Mapping)
            ),
            characters=tuple(
                Character.from_api(c) for c in payload.get("characters") or () if isinstance(c, Mapping)
            ),
            next_episode_id=_int(next_episode, "id") if isinstance(next_episode, Mapping) else None,
            is_end=_bool(payload, "is_end"),
        )


@dataclass(frozen=True, slots=True)
class NovelChapter:
    """A decoded novel chapter, as paragraphs or markdown."""

    episode_id: int
    content_id: int
    title: str | None = None
    paragraphs: tuple[str, ...] = ()
    markdown: str | None = None
    next_episode_id: int | None = None
    is_end: bool | None = None

    @property
    def text(self) -> str:
        """Paragraphs joined by blank lines."""
        return "\n\n".join(self.paragraphs)

    def __len__(self) -> int:
        return len(self.paragraphs)

    @classmethod
    def from_api(
        cls,
        payload: Mapping[str, Any],
        paragraphs: Sequence[str],
        markdown: str | None = None,
    ) -> "NovelChapter":
        next_episode = payload.get("next")
        return cls(
            episode_id=_int(payload, "episode_id") or 0,
            content_id=_int(payload, "content_id") or 0,
            title=_str(payload, "episode_title"),
            paragraphs=tuple(paragraphs),
            markdown=markdown,
            next_episode_id=_int(next_episode, "id") if isinstance(next_episode, Mapping) else None,
            is_end=_bool(payload, "is_end"),
        )


@dataclass(frozen=True, slots=True)
class ComicPage:
    """One comic page, already rewritten to a directly fetchable CDN URL."""

    url: str
    width: int | None = None
    height: int | None = None
    size: int | None = None
    original_url: str | None = None

    @classmethod
    def from_api(cls, payload: Mapping[str, Any], url: str, original: str | None = None) -> "ComicPage":
        return cls(
            url=url,
            width=_int(payload, "width"),
            height=_int(payload, "height"),
            size=_int(payload, "size"),
            original_url=original,
        )


@dataclass(frozen=True, slots=True)
class Comment:
    """A reader comment."""

    id: int
    content: str | None = None
    user_id: int | None = None
    nickname: str | None = None
    avatar_url: str | None = None
    like_count: int | None = None
    reply_count: int | None = None
    created_at: int | None = None

    @classmethod
    def from_api(cls, payload: Mapping[str, Any]) -> "Comment":
        user = payload.get("user")
        user_map = user if isinstance(user, Mapping) else {}
        return cls(
            id=_int(payload, "id") or 0,
            content=_str(payload, "content"),
            user_id=_int(payload, "user_id") or _int(user_map, "id"),
            nickname=_str(user_map, "nickname") or _str(payload, "nickname"),
            avatar_url=_str(user_map, "avatar_url") or _str(payload, "avatar_url"),
            like_count=_int(payload, "like_count"),
            reply_count=_int(payload, "reply_count"),
            created_at=_int(payload, "created_at"),
        )
