"""Exception hierarchy for the MangaToon SDK."""

from __future__ import annotations

__all__ = [
    "MangaToonError",
    "TransportError",
    "DirectAccessBlocked",
    "APIError",
    "ValidationError",
    "PaymentRequired",
    "NotAvailable",
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


class NotAvailable(APIError):
    """The episode exists but its payload is not served anonymously.

    The API answers a locked or not-yet-published episode with
    ``status: "error"``, ``error_code: 404`` and the message ``"This episode is
    not ready for online right now."`` — note there is no ``is_fee`` flag and no
    ``data`` key in that response, so it is indistinguishable from a genuinely
    missing episode by status alone. :attr:`looks_locked` records that the
    message matched the known wording, which is a strong but not certain signal.
    """

    def __init__(
        self,
        message: str,
        *,
        episode_id: int | None = None,
        content_id: int | None = None,
        looks_locked: bool = False,
    ) -> None:
        super().__init__(message, status=404, code=404)
        self.episode_id = episode_id
        self.content_id = content_id
        self.looks_locked = looks_locked


class DecryptionError(MangaToonError):
    """A content payload could not be decrypted."""
