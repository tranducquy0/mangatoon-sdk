"""Request signing for the MangaToon mobile JSON API.

Every ``sg.mangatoon.mobi`` call carries an MD5 signature over the request
path and its query parameters. The algorithm is::

    sign = md5(pathname + "k=v&k=v&..."(sorted) + SALT)

Two details are easy to get wrong and are pinned by ``tests/test_signing.py``:

* The query string is concatenated **directly onto the path** with no
  separator before the first parameter.
* Parameters are ordered by their *percent-encoded* key, and ``sign`` itself
  is appended only after signing.
"""

from __future__ import annotations

import hashlib
import time
from typing import Any
from urllib.parse import quote

__all__ = ["API_ROOT", "API_VERSION", "SIGNING_SALT", "sign_url", "build_query"]

#: Origin serving the signed JSON API.
API_ROOT = "https://sg.mangatoon.mobi"

#: Client version advertised to the API. Both this and older values have been
#: observed returning ``status: success``. If requests start failing, this
#: constant is the first thing to check -- ``tests/test_signing.py`` guards it.
API_VERSION = "2.00.02"

#: Shared secret mixed into the signature.
SIGNING_SALT = "66c10a61bd916c23f3b33810d3785d17"

#: Referer/Origin expected on API calls.
_REFERER = "https://h5.mangatoon.mobi"

DEFAULT_UDID = "483487d947b77e0bc544306e196612eb"

ParamValue = str | int | float | bool


def _encode(value: ParamValue) -> str:
    """Percent-encode a value the way the reference client does."""
    if isinstance(value, bool):
        return "true" if value else "false"
    return quote(str(value), safe="")


def build_query(
    params: dict[str, ParamValue],
    *,
    language: str = "en",
    udid: str = DEFAULT_UDID,
    timestamp: int | None = None,
    version: str = API_VERSION,
) -> dict[str, ParamValue]:
    """Add the standard envelope parameters to ``params``.

    Args:
        params: Endpoint-specific parameters.
        language: Content language code.
        udid: Anonymous device id. Not tied to any account, so the default is
            shared by all anonymous users.
        timestamp: Unix seconds; defaults to now.
        version: API version string to advertise.

    Returns:
        A new dict including ``_``, ``_webp``, ``_platform``, ``_v``,
        ``_language`` and ``_udid``.
    """
    merged: dict[str, ParamValue] = dict(params)
    merged.setdefault("_", timestamp if timestamp is not None else int(time.time()))
    merged.setdefault("_webp", "true")
    merged.setdefault("_platform", "web")
    merged.setdefault("_v", version)
    merged.setdefault("_language", language)
    merged.setdefault("_udid", udid)
    return merged


def _canonical_query(params: dict[str, ParamValue]) -> str:
    """Render ``params`` in the exact form the signature is computed over."""
    encoded = {quote(str(key), safe=""): _encode(value) for key, value in params.items()}
    return "&".join(f"{key}={encoded[key]}" for key in sorted(encoded))


def compute_sign(path: str, params: dict[str, ParamValue]) -> str:
    """Compute the ``sign`` value for ``path`` and ``params``.

    Args:
        path: Request path beginning with ``/`` (host excluded).
        params: Parameters *excluding* ``sign``.

    Returns:
        Lowercase hex MD5 digest.
    """
    payload = path + _canonical_query(params) + SIGNING_SALT
    return hashlib.md5(payload.encode("utf-8")).hexdigest()


def sign_url(
    path: str,
    params: dict[str, ParamValue] | None = None,
    *,
    root: str = API_ROOT,
    **envelope: Any,
) -> str:
    """Build a fully signed absolute URL.

    Args:
        path: Request path beginning with ``/``.
        params: Endpoint-specific parameters. Added to the standard envelope.
        root: API origin.
        **envelope: Overrides forwarded to :func:`build_query` (``language``,
            ``udid``, ``timestamp``, ``version``).

    Returns:
        Absolute URL with ``sign`` as the first query parameter.
    """
    merged = build_query(params or {}, **envelope)
    sign = compute_sign(path, merged)
    ordered: dict[str, ParamValue] = {"sign": sign, **merged}
    query = "&".join(f"{quote(str(k), safe='')}={_encode(v)}" for k, v in ordered.items())
    return f"{root.rstrip('/')}{path}?{query}"


def api_headers() -> dict[str, str]:
    """Headers the API expects on signed calls."""
    return {
        "Referer": _REFERER,
        "Origin": _REFERER,
        "x-respond-with": "text",
    }
