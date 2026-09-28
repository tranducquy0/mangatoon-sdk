"""CLI argument handling and command output, against a stub client."""

from __future__ import annotations

import json
import sys
from typing import Any, Callable, Sequence

import pytest

from mangatoon import cli
from mangatoon._exceptions import APIError, NotAvailable
from mangatoon._models import (
    BrowsePage,
    ChatChapter,
    ChatMessage,
    ChatMessageType,
    Comment,
    ComicPage,
    ContentType,
    Episode,
    Series,
    SeriesSummary,
    Tag,
)


class StubMangaToon:
    """Replaces :class:`MangaToon` inside the CLI, recording the options used."""

    created: list["StubMangaToon"] = []

    def __init__(self, **kwargs: Any) -> None:
        self.kwargs = kwargs
        self.closed = False
        self.calls: list[tuple[str, tuple[Any, ...], dict[str, Any]]] = []
        StubMangaToon.created.append(self)

    def _record(self, name: str, *args: Any, **kwargs: Any) -> None:
        self.calls.append((name, args, kwargs))

    async def __aenter__(self) -> "StubMangaToon":
        return self

    async def __aexit__(self, *exc: Any) -> None:
        self.closed = True

    def _reply(self, name: str, *args: Any, **kwargs: Any) -> Any:
        self._record(name, *args, **kwargs)
        if name in ("get_detail", "episodes", "get_novel_chapter", "get_chat_chapter", "comments"):
            return RESPONSES[name]
        if name == "get_comic_pages":
            return RESPONSES["get_comic_pages"]
        raise AssertionError(f"unexpected call {name}")

    async def get_detail(self, content_id: int) -> Series:
        return self._reply("get_detail", content_id)

    async def episodes(self, content_id: int) -> list[Episode]:
        return self._reply("episodes", content_id)

    async def get_novel_chapter(self, episode_id: int, *, markdown: bool = False) -> Any:
        return self._reply("get_novel_chapter", episode_id, markdown=markdown)

    async def get_chat_chapter(self, episode_id: int) -> ChatChapter:
        return self._reply("get_chat_chapter", episode_id)

    async def get_comic_pages(self, episode_id: int) -> list[ComicPage]:
        return self._reply("get_comic_pages", episode_id)

    async def comments(self, content_id: int, *, page: int = 1, limit: int = 20) -> list[Comment]:
        return self._reply("comments", content_id, page=page, limit=limit)

    async def fetch_bytes(self, url: str) -> bytes:
        self._record("fetch_bytes", url)
        return b"jpeg-data"

    def iter_search(self, word: str, **kwargs: Any) -> Any:
        self._record("iter_search", word, **kwargs)
        return _page_source()

    def iter_browse(self, **kwargs: Any) -> Any:
        self._record("iter_browse", **kwargs)
        return _page_source()


#: Builds the listing the stub iterators yield. Overridable per test.
PAGE_FACTORY: Callable[[], BrowsePage] = lambda: BrowsePage(items=(SUMMARY,), page=1)


def _page_source() -> Any:
    async def pages() -> Any:
        yield PAGE_FACTORY()

    return pages()


SERIES = Series(
    id=12345,
    title="A Test Series",
    type=ContentType.NOVEL,
    episode_count=40,
    category_name="Romance",
    is_end=False,
    description="  A description.  ",
    tags=(Tag(id=1, name="Fantasy"),),
)

SUMMARY = SeriesSummary(
    id=12345,
    title="A Test Series",
    type=ContentType.NOVEL,
    episode_count=40,
    tags=(Tag(id=1, name="Fantasy"),),
)

RESPONSES: dict[str, Any] = {
    "get_detail": SERIES,
    "episodes": [
        Episode(id=1, title="Chapter 1", is_fee=False),
        Episode(id=2, title="Chapter 2", is_fee=True),
    ],
    "get_novel_chapter": type(
        "N", (), {"episode_id": 1, "title": "Chapter 1", "paragraphs": ("One.", "Two."), "markdown": None}
    )(),
    "get_chat_chapter": ChatChapter(
        episode_id=7,
        content_id=99,
        title="Chapter 1",
        messages=(
            ChatMessage(id=1, type=ChatMessageType.NARRATION, content="It was dark."),
            ChatMessage(id=2, type=ChatMessageType.DIALOGUE, character_id=5, content="Hello."),
            ChatMessage(id=3, type=ChatMessageType.IMAGE, image_url="https://x/i.jpg"),
        ),
    ),
    "get_comic_pages": [ComicPage(url="https://x/1.jpg", width=800, height=1200)],
    "comments": [Comment(id=1, content="Nice", nickname="reader")],
}


@pytest.fixture(autouse=True)
def stub_client(monkeypatch: pytest.MonkeyPatch) -> None:
    StubMangaToon.created.clear()
    monkeypatch.setattr(cli, "MangaToon", StubMangaToon)
    # Restored after each test; individual tests substitute their own listing.
    monkeypatch.setattr(
        sys.modules[__name__],
        "PAGE_FACTORY",
        lambda: BrowsePage(items=(SUMMARY,), page=1),
    )


def run(argv: Sequence[str]) -> int:
    return cli.main(["--no-delay", *argv])


class TestParser:
    def test_requires_a_subcommand(self, capsys: pytest.CaptureFixture[str]) -> None:
        with pytest.raises(SystemExit):
            cli.main([])

    def test_rejects_unknown_transport(self) -> None:
        with pytest.raises(SystemExit):
            cli.main(["--transport", "carrier-pigeon", "detail", "1"])

    def test_rejects_unknown_type(self) -> None:
        with pytest.raises(SystemExit):
            run(["search", "x", "--type", "poem"])

    @pytest.mark.parametrize("value,expected", [
        ("comic", ContentType.COMIC),
        ("novel", ContentType.NOVEL),
        ("chat", ContentType.CHAT_STORY),
        ("all", None),
        (None, None),
    ])
    def test_type_mapping(self, value: str | None, expected: Any) -> None:
        assert cli._parse_type(value) is expected

    def test_transport_and_tuning_reach_the_client(self) -> None:
        run(["detail", "12345"])
        kwargs = StubMangaToon.created[0].kwargs
        assert kwargs["transport"] == "auto"
        assert kwargs["rate_limit"] == 0.0  # --no-delay
        assert kwargs["language"] == "en"

    def test_client_is_closed(self) -> None:
        run(["detail", "12345"])
        assert StubMangaToon.created[0].closed is True


class TestDetail:
    def test_text_output(self, capsys: pytest.CaptureFixture[str]) -> None:
        assert run(["detail", "12345"]) == 0
        out = capsys.readouterr().out
        assert "A Test Series" in out
        assert "NOVEL" in out
        assert "episodes 40" in out
        assert "Fantasy" in out
        assert "ongoing" in out

    def test_json_output_is_valid(self, capsys: pytest.CaptureFixture[str]) -> None:
        assert run(["--json", "detail", "12345"]) == 0
        payload = json.loads(capsys.readouterr().out)
        assert payload["id"] == 12345
        assert payload["type"] == "NOVEL"
        assert payload["tags"][0]["name"] == "Fantasy"

    def test_id_is_sent_as_int(self) -> None:
        run(["detail", "12345"])
        assert StubMangaToon.created[0].calls[0] == ("get_detail", (12345,), {})


class TestChapters:
    def test_marks_paywalled_episodes(self, capsys: pytest.CaptureFixture[str]) -> None:
        assert run(["chapters", "12345"]) == 0
        out = capsys.readouterr().out
        assert "2 episodes (1 free, 1 paywalled)" in out
        assert "     1  Chapter 1" in out.rstrip("\n")  # free: no trailing flag
        assert out.rstrip("\n").endswith("2  Chapter 2  $")

    def test_json_output(self, capsys: pytest.CaptureFixture[str]) -> None:
        run(["--json", "chapters", "12345"])
        payload = json.loads(capsys.readouterr().out)
        assert [e["is_fee"] for e in payload] == [False, True]


class TestRead:
    def test_novel_prints_paragraphs(self, capsys: pytest.CaptureFixture[str]) -> None:
        assert run(["read", "1", "--kind", "novel"]) == 0
        out = capsys.readouterr().out
        assert "# Chapter 1" in out
        assert "One.\n\nTwo." in out

    def test_novel_markdown_flag_is_forwarded(self) -> None:
        run(["read", "1", "--kind", "novel", "--markdown"])
        assert StubMangaToon.created[0].calls[0][2] == {"markdown": True}

    def test_chat_resolves_speakers(self, capsys: pytest.CaptureFixture[str]) -> None:
        assert run(["read", "7", "--kind", "chat"]) == 0
        out = capsys.readouterr().out
        assert "It was dark." in out  # narration, indented
        assert "[image] https://x/i.jpg" in out

    def test_chat_json_uses_enum_names(self, capsys: pytest.CaptureFixture[str]) -> None:
        run(["--json", "read", "7", "--kind", "chat"])
        payload = json.loads(capsys.readouterr().out)
        assert [m["type"] for m in payload["messages"]] == [
            "NARRATION", "DIALOGUE", "IMAGE",
        ]


class TestPages:
    def test_lists_urls(self, capsys: pytest.CaptureFixture[str]) -> None:
        assert run(["pages", "5"]) == 0
        out = capsys.readouterr().out
        assert "1 pages" in out
        assert "https://x/1.jpg" in out

    def test_download_requires_output(self, capsys: pytest.CaptureFixture[str]) -> None:
        assert run(["pages", "5", "--download"]) == 2
        assert "--output" in capsys.readouterr().err

    def test_download_writes_numbered_files(
        self, tmp_path: Any, capsys: pytest.CaptureFixture[str]
    ) -> None:
        assert run(["pages", "5", "--download", "--output", str(tmp_path)]) == 0
        assert (tmp_path / "0001.jpg").exists()

    def test_download_skips_existing(
        self, tmp_path: Any, capsys: pytest.CaptureFixture[str]
    ) -> None:
        (tmp_path / "0001.jpg").write_bytes(b"already here")
        run(["pages", "5", "--download", "--output", str(tmp_path)])
        assert (tmp_path / "0001.jpg").read_bytes() == b"already here"
        assert "skip" in capsys.readouterr().err


class TestSearchAndBrowse:
    def test_search_prints_rows(self, capsys: pytest.CaptureFixture[str]) -> None:
        assert run(["search", "heir"]) == 0
        out = capsys.readouterr().out
        assert "A Test Series" in out
        assert "40 eps" in out

    def test_search_type_is_forwarded(self) -> None:
        run(["search", "heir", "--type", "comic"])
        assert StubMangaToon.created[0].calls[0][2]["type"] is ContentType.COMIC

    def test_browse_order_is_forwarded(self) -> None:
        run(["browse", "--order", "new"])
        assert StubMangaToon.created[0].calls[0][2]["order"] == "new"

    def test_empty_results_exit_7(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(
            sys.modules[__name__], "PAGE_FACTORY", lambda: BrowsePage(items=())
        )
        assert run(["search", "zzz"]) == 7


class TestComments:
    def test_prints_nicknames(self, capsys: pytest.CaptureFixture[str]) -> None:
        assert run(["comments", "1"]) == 0
        assert "- reader: Nice" in capsys.readouterr().out

    def test_paging_is_forwarded(self) -> None:
        run(["comments", "1", "--page", "3", "--limit", "5"])
        assert StubMangaToon.created[0].calls[0][2] == {"page": 3, "limit": 5}


class TestExitCodes:
    def test_locked_episode_is_exit_3(self, monkeypatch: pytest.MonkeyPatch) -> None:
        async def locked(self: Any, episode_id: int, **_kwargs: Any) -> Any:
            raise NotAvailable(
                "This episode is not ready for online right now.",
                episode_id=episode_id,
                looks_locked=True,
            )

        monkeypatch.setattr(StubMangaToon, "get_novel_chapter", locked)
        assert run(["read", "1", "--kind", "novel"]) == 3

    def test_api_error_is_exit_5(self, monkeypatch: pytest.MonkeyPatch) -> None:
        async def boom(self: Any, content_id: int) -> Any:
            raise APIError("nope", status=403)

        monkeypatch.setattr(StubMangaToon, "get_detail", boom)
        assert run(["detail", "1"]) == 5

    def test_keyboard_interrupt_is_130(self, monkeypatch: pytest.MonkeyPatch) -> None:
        async def interrupted(self: Any, content_id: int) -> Any:
            raise KeyboardInterrupt

        monkeypatch.setattr(StubMangaToon, "get_detail", interrupted)
        assert run(["detail", "1"]) == 130
