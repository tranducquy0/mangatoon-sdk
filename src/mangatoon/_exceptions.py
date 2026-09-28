"""Exception hierarchy for the MangaToon SDK."""

from __future__ import annotations

__all__ = [
    "MangaToonError",
    "TransportError",
    "DirectAccessBlocked",
    "APIError",
    "ValidationError",
    "PaymentRequired",
    "DecryptionError",
]


class MangaToonError(Exception):
    """Base class for every error raised by this SDK."""


class TransportError(MangaToonError):
    """The request could not be completed at the network level."""

    def __init__(self, message: str, *, url: str | None = None) -> None:
        super().__init__(message)
        self.url = url


class DirectAccessBlocked(TransportError):
    """The origin refused the connection and no proxy is configured."""


class APIError(MangaToonError):
    """The API answered, but with an error envelope or an unexpected status."""

    def __init__(
        self,
        message: str,
        *,
        status: int | None = None,
        code: int | None = None,
        payload: object | None = None,
    ) -> None:
        super().__init__(message)
        self.status = status
        self.code = code
        self.payload = payload


class ValidationError(APIError):
    """The API rejected a parameter (mirrors its ``ParamValidationError``)."""


class PaymentRequired(MangaToonError):
    """The requested episode is behind MangaToon's paywall.

    This SDK never attempts to bypass paid episodes. Catch this and surface it
    to the user.
    """

    def __init__(self, episode_id: int, *, content_id: int | None = None) -> None:
        super().__init__(
            f"Episode {episode_id} is a paid episode and cannot be read anonymously"
        )
        self.episode_id = episode_id
        self.content_id = content_id


class DecryptionError(MangaToonError):
    """A content payload could not be decrypted."""
