"""Comic page URL rewriting and text normalisation."""

from __future__ import annotations

import pytest

from mangatoon._urls import comic_page_url, mirror_hosts, to_https
from mangatoon._text import is_divider, load_chat_document, split_markdown, split_plain
from mangatoon._exceptions import DecryptionError

from conftest import load_bytes, load_json, load_text

RAW = "http://en-c-pic.mangatoon.mobi/ps/1464942/encrypted/1000/M.webp"


class TestComicPageUrl:
    def test_rewrites_to_watermark_jpg(self) -> None:
        assert comic_page_url(RAW) == (
            "https://en-c-pic.mangatoon.mobi/ps/1464942/watermark/1000/M.jpg"
        )

    def test_width_segment_is_preserved(self) -> None:
        """Any other width is a NoSuchKey on the CDN."""
        assert "/watermark/1000/" in comic_page_url(RAW)
        assert "/watermark/1800/" not in comic_page_url(RAW)

    def test_extension_becomes_jpg(self) -> None:
        assert comic_page_url(RAW).endswith(".jpg")

    def test_scheme_is_upgraded(self) -> None:
        assert comic_page_url(RAW).startswith("https://")

    def test_https_input_is_untouched_scheme_wise(self) -> None:
        assert comic_page_url(RAW.replace("http://", "https://")).startswith("https://")

    def test_single_character_names(self) -> None:
        for name in "M7DxqTe":
            url = f"http://h.mangatoon.mobi/ps/1/encrypted/1000/{name}.webp"
            assert comic_page_url(url).endswith(f"/watermark/1000/{name}.jpg")

    def test_mirror_override(self) -> None:
        rewritten = comic_page_url(RAW, mirror="en-c-pic-aliyun.mangatoon.mobi")
        assert rewritten.startswith("https://en-c-pic-aliyun.mangatoon.mobi/")

    def test_mirror_hosts_are_derived_from_the_stem(self) -> None:
        assert mirror_hosts(RAW) == (
            "en-c-pic-aliyun.mangatoon.mobi",
            "en-c-pic-tencent.mangatoon.mobi",
        )

    def test_query_string_is_kept(self) -> None:
        signed = RAW + "?sign=abc&t=123"
        assert comic_page_url(signed).endswith("?sign=abc&t=123")

    def test_missing_path_rejected(self) -> None:
        with pytest.raises(ValueError):
            comic_page_url("https://host/")

    def test_every_fixture_page_rewrites(self) -> None:
        for item in load_json("pictures_comic.json")["data"]:
            rewritten = comic_page_url(item["url"])
            assert "/encrypted/" not in rewritten
            assert "/watermark/" in rewritten
            assert rewritten.endswith(".jpg")
            assert f"/watermark/{item['width']}/" in rewritten

    def test_to_https_is_idempotent(self) -> None:
        assert to_https(to_https("http://a/b")) == "https://a/b"


class TestParagraphSplitting:
    def test_plain_splits_on_single_newlines(self) -> None:
        assert split_plain("One\nTwo\nThree") == ["One", "Two", "Three"]

    def test_plain_fixture_paragraph_count(self) -> None:
        assert len(split_plain(load_text("dec_l_nomd.txt"))) == 73

    def test_markdown_splits_on_blank_lines(self) -> None:
        assert split_markdown("One\n\nTwo") == ["One", "Two"]

    def test_markdown_fixture_paragraph_count(self) -> None:
        assert len(split_markdown(load_text("dec_l_md.txt"))) == 74

    def test_markdown_keeps_scene_divider(self) -> None:
        paragraphs = split_markdown(load_text("dec_l_md.txt"))
        assert [p for p in paragraphs if is_divider(p)] == ["* * *"]

    def test_empty_segments_dropped(self) -> None:
        assert split_plain("One\n\n\nTwo") == ["One", "Two"]
        assert split_markdown("One\n\n\n\nTwo") == ["One", "Two"]

    def test_whitespace_is_stripped(self) -> None:
        assert split_plain("  One  \n   Two  ") == ["One", "Two"]

    def test_empty_input(self) -> None:
        assert split_plain("") == []
        assert split_markdown("   ") == []

    def test_carriage_returns_normalised(self) -> None:
        assert split_plain("One\r\nTwo") == ["One", "Two"]

    @pytest.mark.parametrize("divider", ["* * *", "---", "— — —", "***"])
    def test_divider_detection(self, divider: str) -> None:
        assert is_divider(divider)

    def test_prose_is_not_a_divider(self) -> None:
        assert not is_divider("She opened the door.")
        assert not is_divider("")


class TestChatDocument:
    def test_parses_decoded_payload(self) -> None:
        from mangatoon import decrypt

        document = load_chat_document(decrypt(load_bytes("chat1.bin")))
        assert document["messages"]
        first = document["messages"][0]
        assert {"id", "character_id", "type", "position", "content"} <= set(first)

    def test_second_fixture_also_parses(self) -> None:
        from mangatoon import decrypt

        assert load_chat_document(decrypt(load_bytes("chat2.bin")))["messages"]

    def test_invalid_json_raises(self) -> None:
        with pytest.raises(DecryptionError):
            load_chat_document("not json at all")

    def test_json_without_messages_raises(self) -> None:
        with pytest.raises(DecryptionError):
            load_chat_document('{"something": 1}')

    def test_encrypted_bytes_raise_a_useful_error(self) -> None:
        with pytest.raises(DecryptionError):
            load_chat_document(load_bytes("chat1.bin"))
