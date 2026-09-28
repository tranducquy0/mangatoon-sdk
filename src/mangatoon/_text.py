"""Normalisation helpers for decoded chapter payloads.

Chapter bodies arrive as a single blob. Plain novel text separates paragraphs
with a single newline; the markdown variant uses a blank line and additionally
carries scene dividers such as ``* * *``.
"""

from __future__ import annotations

import json
import re
from typing import Any, Mapping

from ._exceptions import DecryptionError

__all__ = ["split_plain", "split_markdown", "is_divider", "load_chat_document"]

_CARRIAGE = re.compile(r"\r\n?")

#: Scene dividers, e.g. ``* * *`` or ``---``.
_DIVIDER = re.compile(r"^[*\-\u2014\u2015_=~\s]{3,}$")


def _normalise_newlines(text: str) -> str:
    return _CARRIAGE.sub("\n", text)


def is_divider(paragraph: str) -> bool:
    """Whether a paragraph is a scene divider rather than prose."""
    stripped = paragraph.strip()
    return bool(stripped) and bool(_DIVIDER.match(stripped))


def split_plain(text: str) -> list[str]:
    """Split plain novel text into paragraphs.

    Paragraphs are newline-separated. Empty segments are dropped and each
    paragraph is stripped of surrounding whitespace.
    """
    normalised = _normalise_newlines(text).strip()
    if not normalised:
        return []
    return [chunk.strip() for chunk in normalised.split("\n") if chunk.strip()]


def split_markdown(text: str) -> list[str]:
    """Split markdown novel text into paragraphs.

    Uses blank lines as separators, matching the format the API serves. Scene
    dividers are preserved as their own paragraphs.
    """
    normalised = _normalise_newlines(text).strip()
    if not normalised:
        return []
    return [chunk.strip() for chunk in normalised.split("\n\n") if chunk.strip()]


def load_chat_document(data: bytes | str) -> Mapping[str, Any]:
    """Parse a decoded chat story payload into its message document.

    Raises:
        DecryptionError: If the payload is not a JSON object carrying
            ``messages``.
    """
    if isinstance(data, bytes):
        try:
            text = data.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise DecryptionError(f"chat payload is not valid UTF-8: {exc}") from exc
    else:
        text = data

    try:
        document = json.loads(text)
    except json.JSONDecodeError as exc:
        raise DecryptionError(
            "chat payload is not valid JSON; it may be encrypted with an "
            f"unknown offset ({exc})"
        ) from exc

    if not isinstance(document, Mapping) or "messages" not in document:
        raise DecryptionError("chat payload JSON does not contain a 'messages' array")
    return document
