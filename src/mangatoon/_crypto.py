"""Content deobfuscation for MangaToon chapter payloads.

Chapter text and images are delivered as ``application/octet-stream`` bodies
protected by a byte-substitution cipher. The cipher is fully determined by two
256-byte permutation tables plus a single unknown byte-rotation offset that
varies per file.

The offset is recovered by brute force: exactly one of the 256 candidates
produces a well-formed header. See ``tests/test_crypto.py``, which checks this
against recorded payloads from a novel and a chat story.
"""

from __future__ import annotations

from functools import lru_cache

from ._exceptions import DecryptionError

__all__ = ["decrypt", "detect_offset", "build_lookup_table"]

TABLE_1: Final = bytes((
    161, 158, 189, 103, 2, 8, 54, 66, 27, 65, 108, 98, 114, 215, 107, 119,
    96, 242, 19, 248, 230, 72, 218, 166, 239, 246, 252, 245, 137, 179,
    243, 206, 197, 236, 9, 145, 249, 225, 0, 176, 28, 13, 250, 244, 35,
    48, 57, 216, 16, 127, 220, 73, 21, 224, 124, 199, 228, 85, 191, 154,
    162, 140, 160, 200, 234, 50, 113, 62, 5, 229, 178, 104, 133, 195, 86,
    194, 11, 42, 134, 89, 193, 120, 4, 47, 152, 192, 126, 101, 63, 196,
    208, 172, 38, 163, 150, 132, 240, 112, 117, 146, 255, 118, 141, 58,
    110, 41, 81, 144, 188, 88, 32, 175, 46, 59, 167, 68, 93, 139, 227,
    121, 251, 182, 180, 60, 94, 136, 156, 201, 147, 29, 78, 143, 40, 109,
    185, 202, 138, 164, 130, 186, 170, 31, 45, 91, 18, 173, 100, 187, 254,
    39, 97, 155, 74, 111, 223, 26, 203, 34, 67, 23, 237, 177, 207, 231,
    20, 204, 159, 71, 125, 80, 174, 241, 221, 92, 84, 90, 168, 122, 153,
    247, 77, 213, 64, 6, 184, 10, 116, 37, 149, 129, 99, 83, 115, 123,
    128, 135, 33, 70, 238, 253, 214, 56, 76, 210, 226, 44, 51, 25, 82,
    157, 53, 106, 131, 148, 151, 142, 198, 183, 169, 55, 212, 95, 43, 211,
    36, 75, 209, 102, 14, 171, 190, 7, 12, 105, 181, 15, 24, 61, 17, 52,
    87, 222, 30, 3, 233, 232, 22, 165, 219, 79, 217, 69, 1, 235, 205, 49
))

TABLE_2: Final = bytes((
    39, 197, 251, 159, 23, 170, 21, 209, 188, 18, 9, 13, 212, 105, 14,
    200, 43, 100, 89, 161, 62, 27, 29, 19, 239, 134, 234, 109, 24, 112,
    173, 133, 95, 32, 73, 91, 35, 107, 196, 125, 226, 113, 20, 94, 81,
    143, 75, 44, 151, 220, 156, 246, 117, 41, 85, 240, 122, 187, 193, 15,
    189, 175, 157, 211, 37, 26, 40, 178, 243, 6, 229, 179, 202, 233, 74,
    114, 154, 204, 48, 165, 57, 127, 8, 207, 65, 61, 201, 206, 86, 195,
    77, 22, 110, 181, 237, 254, 97, 160, 47, 138, 69, 221, 12, 140, 70,
    191, 68, 255, 180, 5, 210, 245, 250, 56, 80, 249, 205, 144, 106, 174,
    166, 121, 99, 244, 162, 194, 185, 82, 53, 84, 88, 230, 214, 64, 135,
    228, 42, 58, 103, 52, 158, 218, 10, 124, 46, 167, 198, 208, 216, 222,
    217, 153, 155, 59, 132, 223, 98, 142, 123, 152, 90, 199, 111, 129, 76,
    146, 66, 118, 172, 71, 164, 1, 219, 247, 79, 36, 28, 4, 141, 72, 50,
    137, 149, 120, 139, 236, 128, 227, 38, 115, 253, 241, 83, 203, 49,
    213, 238, 232, 30, 186, 182, 184, 183, 176, 16, 148, 3, 92, 130, 0,
    93, 34, 54, 25, 67, 150, 33, 102, 192, 168, 242, 2, 231, 87, 252, 55,
    171, 177, 136, 248, 31, 96, 119, 163, 11, 45, 7, 60, 78, 131, 147,
    104, 116, 215, 225, 190, 224, 126, 63, 169, 101, 235, 145, 51, 17, 108
))

# Number of leading bytes inspected when probing for the rotation offset.
_PROBE_BYTES = 8


@lru_cache(maxsize=256)
def build_lookup_table(offset: int) -> bytes:
    """Return the 256-byte substitution table for ``offset``.

    The construction inverts ``TABLE_2`` after rotating it by ``offset``, then
    composes the result with ``TABLE_1``. Cached, since only 256 values exist.
    """
    if not 0 <= offset <= 255:
        raise ValueError(f"offset must be in 0..255, got {offset}")

    rotated = bytearray(256)
    for index, value in enumerate(TABLE_2):
        rotated[(index + offset) % 256] = value

    inverse = bytearray(256)
    for position, value in enumerate(rotated):
        inverse[value] = position

    return bytes(TABLE_1[inverse[i]] for i in range(256))


def _is_plausible_header(header: bytes) -> bool:
    """Whether a candidate header looks like real decoded content."""
    try:
        text = header.decode("utf-8")
    except UnicodeDecodeError:
        return False
    if not text or not any(char.isalnum() for char in text):
        return False
    return all(char.isprintable() or char == "\n" for char in text)


def detect_offset(data: bytes) -> int | None:
    """Recover the rotation offset of ``data``.

    Returns the single offset whose decoded header is plausible text, or
    ``None`` when the payload is empty or no candidate qualifies. In practice
    exactly one candidate qualifies.
    """
    if not data:
        return None

    probe = data[:_PROBE_BYTES]
    for offset in range(256):
        if _is_plausible_header(probe.translate(build_lookup_table(offset))):
            return offset
    return None


def decrypt(data: bytes, offset: int | None = None) -> bytes:
    """Deobfuscate a MangaToon content payload.

    Args:
        data: Raw body as served by the API.
        offset: Known rotation offset. Detected when omitted.

    Returns:
        The decoded bytes. Decoding is a full-payload substitution.

    Raises:
        DecryptionError: If ``offset`` is omitted and cannot be determined.
    """
    if offset is None:
        offset = detect_offset(data)
        if offset is None:
            raise DecryptionError(
                "could not determine cipher offset: no candidate produced a "
                f"plausible header in the first {_PROBE_BYTES} bytes"
            )
    return data.translate(build_lookup_table(offset))
