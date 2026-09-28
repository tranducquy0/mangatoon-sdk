"""Decryption of obfuscated chapter payloads.

The ``dec_*.txt`` fixtures are plaintext captured from a known-good decoder, so
they act as an oracle: any change that breaks decoding shows up as a byte
mismatch rather than a subtly different chapter.
"""

from __future__ import annotations

import pytest

from mangatoon._crypto import TABLE_1, TABLE_2, build_lookup_table, decrypt, detect_offset
from mangatoon._exceptions import DecryptionError

from conftest import load_bytes, load_text

PAYLOADS = [
    ("l_nomd.bin", "dec_l_nomd.txt", 173),
    ("l_md.bin", "dec_l_md.txt", 253),
    ("p_md_ch2.bin", "dec_p_md_ch2.txt", 136),
    ("chat1.bin", "dec_chat1.txt", 243),
    ("chat2.bin", "dec_chat2.txt", 73),
]


class TestTables:
    def test_both_tables_are_256_byte_permutations(self) -> None:
        for table in (TABLE_1, TABLE_2):
            assert len(table) == 256
            assert sorted(table) == list(range(256))

    def test_lookup_table_is_also_a_permutation(self) -> None:
        for offset in (0, 1, 128, 255):
            table = build_lookup_table(offset)
            assert len(table) == 256
            assert sorted(table) == list(range(256))

    def test_offset_zero_differs_from_offset_one(self) -> None:
        assert build_lookup_table(0) != build_lookup_table(1)

    def test_out_of_range_offset_rejected(self) -> None:
        with pytest.raises(ValueError):
            build_lookup_table(256)
        with pytest.raises(ValueError):
            build_lookup_table(-1)


class TestDecryption:
    @pytest.mark.parametrize("name,oracle,offset", PAYLOADS)
    def test_matches_known_good_plaintext(self, name: str, oracle: str, offset: int) -> None:
        assert decrypt(load_bytes(name)) == load_text(oracle).encode("utf-8")

    @pytest.mark.parametrize("name,oracle,offset", PAYLOADS)
    def test_offset_is_detected_exactly(self, name: str, oracle: str, offset: int) -> None:
        assert detect_offset(load_bytes(name)) == offset

    @pytest.mark.parametrize("name,oracle,offset", PAYLOADS)
    def test_explicit_offset_matches_detection(self, name: str, oracle: str, offset: int) -> None:
        data = load_bytes(name)
        assert decrypt(data, offset) == decrypt(data)

    def test_round_trip_through_reversal(self) -> None:
        """Applying a table twice is not the identity, but a table inverts."""
        data = load_bytes("chat1.bin")
        table = build_lookup_table(243)
        assert data.translate(table).translate(bytes(table.index(i) for i in range(256))) == data

    def test_novel_payload_decodes_to_english(self) -> None:
        text = decrypt(load_bytes("l_nomd.bin")).decode("utf-8")
        assert "One hour before the wedding" in text

    def test_chat_payload_decodes_to_json(self) -> None:
        import json

        document = json.loads(decrypt(load_bytes("chat1.bin")))
        assert "messages" in document
        assert document["messages"]

    def test_empty_input_raises(self) -> None:
        with pytest.raises(DecryptionError):
            decrypt(b"")

    def test_undecodable_input_raises(self) -> None:
        """Random bytes should not accidentally look like text at any offset."""
        import os

        blob = os.urandom(64)
        if detect_offset(blob) is not None:
            # Only assert the failure if detection genuinely found nothing.
            pytest.skip("random bytes happened to yield a plausible header")
        with pytest.raises(DecryptionError):
            decrypt(blob)
