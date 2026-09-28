"""End-to-end client behaviour against a fake transport.

The fake serves recorded responses, so these exercise the full request path:
signing, envelope unwrapping, decryption and model mapping.
"""

from __future__ import annotations

import json

import pytest

from mangatoon import (
    APIError,
    ChatChapter,
    ChatMessageType,
    ComicPage,
    ContentType,
    MangaToon,
    NovelChapter,
    NotAvailable,
    PaymentRequired,
    Series,
)
from mangatoon._endpoints import Api, _clamp_limit, _normalise_page, _unwrap
from mangatoon._exceptions import APIError, ValidationError

from conftest import FakeTransport, load_bytes, load_json

NOVEL_PAYLOAD = "https://en-f-pic.mangatoon.mobi/6067943/81176408/l.bin"
NOVEL_MD = "https://en-f-pic.mangatoon.mobi/6067943/81176408/l_md.bin"
CHAT_PAYLOAD = "https://en-f-pic.mangatoon.mobi/6067953/76866880/B.bin"


def json_by_path() -> dict[str, object]:
    return {
        "/api/content/detail": load_json("detail_chat.json"),
        "/api/content/detail_novel": load_json("detail_novel.json"),
        "/api/content/episodes": load_json("episodes_chat.json"),
        "/api/content/search": load_json("search_chat.json"),
        "/api/content/list": load_json("list_chat.json"),
        "/api/fictions/content": load_json("fiction_chat.json"),
        "/api/cartoons/pictures": load_json("pictures_comic.json"),
    }


def make_client(transport: FakeTransport) -> MangaToon:
    client = MangaToon(transport=transport)
    return client


class TestSeriesCalls:
    async def test_get_detail(self) -> None:
        transport = FakeTransport(json_by_path={"/api/content/detail": load_json("detail_chat.json")})
        async with make_client(transport) as mt:
            series = await mt.get_detail(6067953)
        assert isinstance(series, Series)
        assert series.type is ContentType.CHAT_STORY
        assert transport.json_calls[0].startswith(
            "https://sg.mangatoon.mobi/api/content/detail?sign="
        )

    async def test_request_is_signed_and_carries_envelope(self) -> None:
        transport = FakeTransport(json_by_path={"/api/content/detail": load_json("detail_chat.json")})
        async with make_client(transport) as mt:
            await mt.get_detail(6067953)
        url = transport.json_calls[0]
        assert "sign=" in url
        for param in ("_webp=true", "_platform=web", "_language=en", "&_udid="):
            assert param in url
        assert "id=6067953" in url

    async def test_language_is_propagated(self) -> None:
        transport = FakeTransport(json_by_path={"/api/content/detail": load_json("detail_chat.json")})
        async with MangaToon(language="id", transport=transport) as mt:
            await mt.get_detail(1)
        assert "_language=id" in transport.json_calls[0]

    async def test_episodes(self) -> None:
        transport = FakeTransport(json_by_path={"/api/content/episodes": load_json("episodes_chat.json")})
        async with make_client(transport) as mt:
            episodes = await mt.episodes(6067953)
        assert len(episodes) == 362
        assert episodes[0].id == 4209230

    async def test_search_novel_returns_only_novels(self) -> None:
        transport = FakeTransport(json_by_path={"/api/content/search": load_json("search_novel.json")})
        async with make_client(transport) as mt:
            page = await mt.search("dragon", type=ContentType.NOVEL)
        assert len(page) == 20
        assert all(item.type is ContentType.NOVEL for item in page.items)

    async def test_browse_new_novels(self) -> None:
        transport = FakeTransport(json_by_path={"/api/content/list": load_json("list_novel.json")})
        async with make_client(transport) as mt:
            page = await mt.browse(type=ContentType.NOVEL, order="new")
        assert all(item.type is ContentType.NOVEL for item in page.items)
        assert "order=new" in transport.json_calls[0]

    async def test_null_episode_list_is_empty(self) -> None:
        transport = FakeTransport(default_json={"status": "success", "data": None})
        async with make_client(transport) as mt:
            assert await mt.episodes(1) == []


class TestSearchAndBrowse:
    async def test_search(self) -> None:
        transport = FakeTransport(json_by_path={"/api/content/search": load_json("search_chat.json")})
        async with make_client(transport) as mt:
            page = await mt.search("romance", type=ContentType.CHAT_STORY)
        assert len(page) == 20
        assert "type=4" in transport.json_calls[0]
        assert "word=romance" in transport.json_calls[0]

    async def test_search_without_type_omits_the_param(self) -> None:
        transport = FakeTransport(json_by_path={"/api/content/search": load_json("search_chat.json")})
        async with make_client(transport) as mt:
            await mt.search("romance")
        assert "type=" not in transport.json_calls[0]

    async def test_browse(self) -> None:
        transport = FakeTransport(json_by_path={"/api/content/list": load_json("list_chat.json")})
        async with make_client(transport) as mt:
            page = await mt.browse(type=ContentType.NOVEL, order="new")
        assert "type=2" in transport.json_calls[0]
        assert "order=new" in transport.json_calls[0]
        assert page.total_count

    async def test_page_must_be_one_indexed(self) -> None:
        transport = FakeTransport()
        async with make_client(transport) as mt:
            with pytest.raises(ValueError, match="1-indexed"):
                await mt.search("x", page=0)

    def test_normalise_page_rejects_zero(self) -> None:
        with pytest.raises(ValueError):
            _normalise_page(0)
        assert _normalise_page(1) == 1

    def test_limit_is_clamped_to_the_api_maximum(self) -> None:
        assert _clamp_limit(None, 20) == 20
        assert _clamp_limit(10, 20) == 10
        assert _clamp_limit(10_000, 20) == 500
        with pytest.raises(ValueError):
            _clamp_limit(0, 20)

    async def test_iter_search_stops_at_the_end(self) -> None:
        pages = [
            {"status": "success", "data": [{"id": 1, "title": "a", "type": 4}],
             "next_page": 2, "page_count": 2, "items_count_per_page": 1, "total_count": 2},
            {"status": "success", "data": [], "next_page": 0, "page_count": 2,
             "items_count_per_page": 1, "total_count": 2},
        ]
        seen = []

        class Sequencer(FakeTransport):
            async def get_json(self, url: str, headers: dict[str, str]) -> object:
                self.json_calls.append(url)
                return pages[len(self.json_calls) - 1]

        transport = Sequencer()
        async with make_client(transport) as mt:
            async for page in mt.iter_search("x", type=ContentType.CHAT_STORY):
                seen.append(page)
        assert len(seen) == 1

    async def test_iter_browse_respects_max_pages(self) -> None:
        page_payload = {
            "status": "success",
            "data": [{"id": 1, "title": "a", "type": 2}],
            "next_page": 2,
            "page_count": 99,
            "items_count_per_page": 1,
            "total_count": 99,
        }
        transport = FakeTransport(default_json=page_payload)
        async with make_client(transport) as mt:
            pages = [p async for p in mt.iter_browse(type=ContentType.NOVEL, max_pages=3)]
        assert len(pages) == 3


class TestNovelChapter:
    async def test_reads_and_decrypts(self) -> None:
        transport = FakeTransport(
            json_by_path={"/api/fictions/content": load_json("fiction_novel.json")},
            bytes_by_url={NOVEL_PAYLOAD: load_bytes("l_nomd.bin")},
        )
        async with make_client(transport) as mt:
            chapter = await mt.get_novel_chapter(4388679)
        assert isinstance(chapter, NovelChapter)
        assert chapter.episode_id == 4388679
        assert len(chapter.paragraphs) == 73
        assert "One hour before the wedding" in chapter.text

    async def test_markdown_variant_when_requested(self) -> None:
        transport = FakeTransport(
            json_by_path={"/api/fictions/content": load_json("fiction_novel.json")},
            bytes_by_url={
                NOVEL_PAYLOAD: load_bytes("l_nomd.bin"),
                NOVEL_MD: load_bytes("l_md.bin"),
            },
        )
        async with make_client(transport) as mt:
            chapter = await mt.get_novel_chapter(4388679, markdown=True)
        assert chapter.markdown is not None
        assert NOVEL_MD in transport.byte_calls
        # The markdown variant is richer, so it supplies the paragraphs.
        assert len(chapter.paragraphs) == 74
        assert "* * *" in chapter.paragraphs

    async def test_markdown_not_fetched_by_default(self) -> None:
        transport = FakeTransport(
            json_by_path={"/api/fictions/content": load_json("fiction_novel.json")},
            bytes_by_url={NOVEL_PAYLOAD: load_bytes("l_nomd.bin")},
        )
        async with make_client(transport) as mt:
            chapter = await mt.get_novel_chapter(4388679)
        assert chapter.markdown is None
        assert len(chapter.paragraphs) == 73

    async def test_next_episode_is_exposed(self) -> None:
        transport = FakeTransport(
            json_by_path={"/api/fictions/content": load_json("fiction_novel.json")},
            bytes_by_url={NOVEL_PAYLOAD: load_bytes("l_nomd.bin")},
        )
        async with make_client(transport) as mt:
            chapter = await mt.get_novel_chapter(4388679)
        assert chapter.next_episode_id == 4388680
        assert chapter.title == "Chapter 1"

    async def test_paywalled_novel_raises(self) -> None:
        payload = load_json("fiction_novel.json")
        payload["is_fee"] = True
        payload["data"] = ""
        transport = FakeTransport(json_by_path={"/api/fictions/content": payload})
        async with make_client(transport) as mt:
            with pytest.raises(PaymentRequired) as exc:
                await mt.get_novel_chapter(4388679)
        assert exc.value.episode_id == 4388679
        assert exc.value.content_id == 6067943


class TestChatChapter:
    async def test_reads_and_decrypts(self) -> None:
        transport = FakeTransport(
            json_by_path={"/api/fictions/content": load_json("fiction_chat.json")},
            bytes_by_url={CHAT_PAYLOAD: load_bytes("chat1.bin")},
        )
        async with make_client(transport) as mt:
            chapter = await mt.get_chat_chapter(4209230)
        assert isinstance(chapter, ChatChapter)
        assert chapter.episode_id == 4209230
        assert chapter.content_id == 6067953
        assert len(chapter.messages) == 38
        assert len(chapter.characters) == 54

    async def test_message_types(self) -> None:
        transport = FakeTransport(
            json_by_path={"/api/fictions/content": load_json("fiction_chat.json")},
            bytes_by_url={CHAT_PAYLOAD: load_bytes("chat1.bin")},
        )
        async with make_client(transport) as mt:
            chapter = await mt.get_chat_chapter(4209230)
        kinds = {m.type for m in chapter.messages}
        assert ChatMessageType.NARRATION in kinds
        assert ChatMessageType.DIALOGUE in kinds
        first = chapter.messages[0]
        assert first.is_narration
        assert chapter.speaker(first) is None

    async def test_speaker_lookup(self) -> None:
        transport = FakeTransport(
            json_by_path={"/api/fictions/content": load_json("fiction_chat.json")},
            bytes_by_url={CHAT_PAYLOAD: load_bytes("chat1.bin")},
        )
        async with make_client(transport) as mt:
            chapter = await mt.get_chat_chapter(4209230)
        dialogue = next(m for m in chapter.messages if m.is_dialogue)
        assert dialogue.character_id != 0
        assert chapter.speaker(dialogue)

    async def test_character_lookup(self) -> None:
        transport = FakeTransport(
            json_by_path={"/api/fictions/content": load_json("fiction_chat.json")},
            bytes_by_url={CHAT_PAYLOAD: load_bytes("chat1.bin")},
        )
        async with make_client(transport) as mt:
            chapter = await mt.get_chat_chapter(4209230)
        known = chapter.characters[0]
        assert chapter.character(known.id) is known
        assert chapter.character(999_999_999) is None

    async def test_render_inlines_names(self) -> None:
        transport = FakeTransport(
            json_by_path={"/api/fictions/content": load_json("fiction_chat.json")},
            bytes_by_url={CHAT_PAYLOAD: load_bytes("chat1.bin")},
        )
        async with make_client(transport) as mt:
            chapter = await mt.get_chat_chapter(4209230)
        rendered = chapter.render()
        assert "Kim Taehyung sat quietly" in rendered
        assert "\n\n" in rendered

    async def test_second_chapter_decodes(self) -> None:
        payload = load_json("fiction_chat.json")
        payload["data"] = "https://en-f-pic.mangatoon.mobi/6067953/76866880/C.bin"
        transport = FakeTransport(
            json_by_path={"/api/fictions/content": payload},
            bytes_by_url={payload["data"]: load_bytes("chat2.bin")},
        )
        async with make_client(transport) as mt:
            chapter = await mt.get_chat_chapter(4209295)
        assert chapter.messages


class TestComicPages:
    async def test_pages_are_rewritten(self) -> None:
        transport = FakeTransport(
            json_by_path={"/api/cartoons/pictures": load_json("pictures_comic.json")}
        )
        async with make_client(transport) as mt:
            pages = await mt.get_comic_pages(195858)
        assert len(pages) == 23
        assert all(isinstance(p, ComicPage) for p in pages)
        assert all("/watermark/" in p.url and p.url.endswith(".jpg") for p in pages)
        assert all(p.original_url and "/encrypted/" in p.original_url for p in pages)
        assert all(p.width and p.height for p in pages)

    async def test_no_byte_fetch_needed(self) -> None:
        """Rewritten URLs need no decryption, so no payload is downloaded."""
        transport = FakeTransport(
            json_by_path={"/api/cartoons/pictures": load_json("pictures_comic.json")}
        )
        async with make_client(transport) as mt:
            await mt.get_comic_pages(195858)
        assert transport.byte_calls == []

    async def test_locked_episode_raises(self) -> None:
        transport = FakeTransport(
            json_by_path={"/api/cartoons/pictures": {"status": "success", "data": []}}
        )
        async with make_client(transport) as mt:
            with pytest.raises(PaymentRequired):
                await mt.get_comic_pages(195858)

    async def test_locked_episode_object_shape_raises(self) -> None:
        transport = FakeTransport(
            json_by_path={
                "/api/cartoons/pictures": {
                    "status": "success",
                    "data": {"is_fee": True, "content_id": 1, "data": []},
                }
            }
        )
        async with make_client(transport) as mt:
            with pytest.raises(PaymentRequired):
                await mt.get_comic_pages(1)

    async def test_real_locked_episode_response_raises(self) -> None:
        """A genuinely locked comic episode, as the API actually answers."""
        transport = FakeTransport(
            json_by_path={"/api/cartoons/pictures": load_json("pictures_paid.json")}
        )
        async with make_client(transport) as mt:
            with pytest.raises(NotAvailable) as exc:
                await mt.get_comic_pages(196217)
        assert exc.value.looks_locked is True
        assert exc.value.episode_id == 196217


class TestUnavailable:
    """A locked episode and a bad id are indistinguishable by status alone."""

    async def test_missing_episode_raises_not_available(self) -> None:
        transport = FakeTransport(
            json_by_path={"/api/fictions/content": load_json("fiction_missing.json")}
        )
        async with make_client(transport) as mt:
            with pytest.raises(NotAvailable) as exc:
                await mt.get_novel_chapter(99999999)
        assert exc.value.looks_locked is False
        assert exc.value.episode_id == 99999999

    async def test_not_available_is_an_api_error(self) -> None:
        assert issubclass(NotAvailable, APIError)

    def test_guard_passes_through_success(self) -> None:
        from mangatoon._endpoints import _guard_unavailable

        _guard_unavailable({"status": "success", "data": []}, 1)

    def test_guard_flags_the_locked_wording(self) -> None:
        from mangatoon._endpoints import LOCKED_MESSAGE, _guard_unavailable

        with pytest.raises(NotAvailable) as exc:
            _guard_unavailable({"status": "error", "message": LOCKED_MESSAGE, "error_code": 404}, 5)
        assert exc.value.looks_locked is True


class TestErrorHandling:
    def test_success_envelope_unwraps_data(self) -> None:
        assert _unwrap({"status": "success", "data": [1]}, "u") == [1]

    def test_error_envelope_raises(self) -> None:
        with pytest.raises(APIError):
            _unwrap({"status": "error", "code": 50000, "message": "boom"}, "u")

    def test_validator_error_is_classified(self) -> None:
        payload = {
            "status": "error",
            "code": 40001,
            "readableMessage": "ParamValidationError(page): Number.isInteger(v)",
        }
        with pytest.raises(ValidationError):
            _unwrap(payload, "u")

    def test_non_mapping_response_raises(self) -> None:
        with pytest.raises(APIError):
            _unwrap([1, 2, 3], "u")

    async def test_api_error_propagates(self) -> None:
        transport = FakeTransport(
            default_json={"status": "error", "code": 403, "message": "Permission denied"}
        )
        async with make_client(transport) as mt:
            with pytest.raises(APIError):
                await mt.get_detail(1)


class TestClientConfiguration:
    def test_unknown_transport_rejected(self) -> None:
        with pytest.raises(ValueError, match="unknown transport"):
            MangaToon(transport="carrier-pigeon")

    def test_transport_names(self) -> None:
        for name in ("auto", "direct", "proxy"):
            client = MangaToon(transport=name)
            assert client.transport_name == name

    def test_custom_transport_is_used(self) -> None:
        transport = FakeTransport(name="custom")
        assert MangaToon(transport=transport).transport_name == "custom"

    def test_active_name_reports_selection(self) -> None:
        client = MangaToon(transport="auto")
        assert client.active_transport_name in ("auto", "direct", "proxy")

    async def test_aclose_is_idempotent(self) -> None:
        transport = FakeTransport()
        client = MangaToon(transport=transport)
        await client.aclose()
        await client.aclose()
        assert transport.closed
