"""CDN URL rewriting for comic page images.

The API hands back ``/encrypted/<width>/<name>.webp`` URLs whose contents are
the obfuscated payload. The reader is served the same page under
``/watermark/<width>/<name>.jpg`` instead. Three details matter and each was
confirmed against the CDN:

* the extension must become ``.jpg`` -- ``/watermark/<name>.webp`` is a
  ``NoSuchKey``;
* the width segment must be reused verbatim -- other widths are ``NoSuchKey``;
* ``/encrypted/`` with a ``.jpg`` extension is a ``NoSuchKey``.

The page is therefore reconstructed rather than downloaded and decrypted.
"""

from __future__ import annotations

import posixpath
from typing import Iterable
from urllib.parse import urlsplit, urlunsplit

__all__ = ["comic_page_url", "mirror_hosts", "to_https"]

#: Alternate CDN hostnames serving identical objects, tried in order.
DEFAULT_MIRRORS: tuple[str, ...] = (
    "{host}-aliyun.mangatoon.mobi",
    "{host}-tencent.mangatoon.mobi",
)


def to_https(url: str) -> str:
    """Rewrite an ``http://`` URL to ``https://``, leaving the rest intact."""
    parts = urlsplit(url)
    if parts.scheme == "http":
        return urlunsplit(("https", parts.netloc, parts.path, parts.query, parts.fragment))
    return url


def _split_suffix(name: str) -> str:
    """Base filename without its extension."""
    stem, dot, _ = name.rpartition(".")
    return stem if dot else name


def comic_page_url(url: str, mirror: str | None = None) -> str:
    """Return a directly fetchable URL for a comic page.

    Args:
        url: URL as returned by ``/api/cartoons/pictures``.
        mirror: Optional replacement hostname, e.g.
            ``en-c-pic-aliyun.mangatoon.mobi``.

    Returns:
        The ``https`` ``/watermark/<width>/<name>.jpg`` form.
    """
    parts = urlsplit(url)
    segments = [segment for segment in parts.path.split("/") if segment]
    if not segments:
        raise ValueError(f"comic page URL has no path: {url!r}")

    segments = [
        "watermark" if segment == "encrypted" else segment for segment in segments
    ]
    last = segments[-1]
    if "." in last:
        segments[-1] = _split_suffix(last) + ".jpg"

    netloc = mirror or parts.netloc
    return urlunsplit(("https", netloc, "/" + "/".join(segments), parts.query, parts.fragment))


def mirror_hosts(url: str) -> tuple[str, ...]:
    """Alternative hostnames for ``url``, most likely to work first.

    The primary hostname is not included; the caller keeps it by default and
    uses these only after a failure.
    """
    host = urlsplit(url).hostname or ""
    stem = host.split(".")[0]
    return tuple(template.format(host=stem) for template in DEFAULT_MIRRORS)


def absolute(base: str, url: str) -> str:
    """Resolve ``url`` against ``base`` without requiring a filesystem."""
    from urllib.parse import urljoin

    return to_https(urljoin(base, url))
