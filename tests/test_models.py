"""Model mapping against recorded API responses."""

from __future__ import annotations

import pytest

from mangatoon import BrowsePage, ContentType, Episode, Series, SeriesSummary

from conftest import load_json


class TestContentType:
    def test_known_codes(self) -> None:
        assert ContentType.COMIC == 1
        assert ContentType.NOVEL == 2
        assert ContentType.CHAT_STORY == 4

    def test_text_types(self) -> None:
        assert ContentType.NOVEL.is_text
        assert ContentType.CHAT_STORY.is_text
        assert not ContentType.COMIC.is_text

    def test_coerce_handles_unknown(self) -> None:
        assert ContentType.coerce(4) is ContentType.CHAT_STORY
        assert ContentType.coerce("2") is ContentType.NOVEL
        assert ContentType.coerce(99) is None
        assert ContentType.coerce(None) is None
        assert ContentType.coerce("nope") is None


class TestSeries:
    @pytest.mark.parametrize(
        "fixture,expected_type,expected_id",
        [
            ("detail_chat.json", ContentType.CHAT_STORY, 6067953),
            ("detail_novel.json", ContentType.NOVEL, 6067943),
            ("detail_comic.json", ContentType.COMIC, 6121145),
        ],
    )
    def test_maps_each_type(self, fixture: str, expected_type: ContentType, expected_id: int) -> None:
        series = Series.from_api(load_json(fixture)["data"])
        assert series.id == expected_id
        assert series.type is expected_type
        assert series.title
        assert series.author is not None and series.author.name
        assert series.episode_count
        assert series.tags

    def test_chat_story_detail_fields(self) -> None:
        series = Series.from_api(load_json("detail_chat.json")["data"])


        assert "\u2019" in series.title
        # Note the U+2019 apostrophe in the upstream data.
        assert series.title == "The Legitimate Heir Doesn\u2019T Want Their Love"
        assert series.category_name == "CP Idol"
        assert series.episode_count == 362
        assert series.first_episode is not None
        assert series.first_episode.id == 4209230
        assert series.cover_url and series.cover_url.startswith("http")
        assert series.tag_names == ("Taekook", "Boys\u2019 Love")

    def test_first_fee_episode_index_exposed(self) -> None:
        series = Series.from_api(load_json("detail_comic.json")["data"])
        assert series.first_fee_episode_index is not None

    def test_missing_fields_become_none_not_errors(self) -> None:
        series = Series.from_api({"id": 1, "title": "Minimal", "type": 2})
        assert series.description is None
        assert series.tags == ()
        assert series.author is None
        assert series.episode_count is None

    def test_unknown_keys_are_ignored(self) -> None:
        payload = dict(load_json("detail_chat.json")["data"], surprise_field={"a": 1})
        assert Series.from_api(payload).id == 6067953


class TestEpisode:
    @pytest.mark.parametrize("fixture", ["episodes_chat.json", "episodes_novel.json", "episodes_comic.json"])
    def test_maps_episode_lists(self, fixture: str) -> None:
        payload = load_json(fixture)["data"]
        episodes = [Episode.from_api(item) for item in payload]
        assert len(episodes) == len(payload)
        assert all(e.id > 0 for e in episodes)
        assert all(e.title for e in episodes)
        assert all(e.weight for e in episodes)

    def test_chat_story_episode_list_is_complete(self) -> None:
        """The website hides these; the API returns all of them."""
        episodes = [Episode.from_api(e) for e in load_json("episodes_chat.json")["data"]]
        assert len(episodes) == 362
        assert episodes[0].id == 4209230
        assert episodes[0].title == "Chapter 1~"

    def test_free_episode(self) -> None:
        episode = Episode.from_api(load_json("episodes_novel.json")["data"][0])
        assert episode.is_fee is False
        assert episode.file_size

    def test_paid_episodes_are_flagged(self) -> None:
        episodes = [Episode.from_api(e) for e in load_json("episodes_comic.json")["data"]]
        assert any(e.is_fee for e in episodes)

    def test_mature_flag_is_coerced_to_bool(self) -> None:
        """The API sends 0/1 here, not true/false."""
        episode = Episode.from_api(load_json("episodes_chat.json")["data"][0])
        assert episode.is_mature is False
        assert episode.has_video is False


class TestBrowsePage:
    def test_search_envelope(self) -> None:
        page = BrowsePage.from_api(load_json("search_chat.json"), page=1)
        assert len(page) == 20
        assert page.total_count == 233
        assert page.page_count == 12
        assert page.next_page == 2
        assert page.per_page == 20
        assert page.has_next
        assert all(isinstance(i, SeriesSummary) for i in page.items)

    def test_browse_envelope(self) -> None:
        page = BrowsePage.from_api(load_json("list_chat.json"), page=1)
        assert page.total_count == 103815
        assert page.has_next

    def test_iteration_yields_items(self) -> None:
        page = BrowsePage.from_api(load_json("search_chat.json"), page=1)
        assert [i.id for i in page] == [i.id for i in page.items]

    def test_last_page_reports_no_next(self) -> None:
        page = BrowsePage(page_count=3, page=3, next_page=0)
        assert not page.has_next

    def test_falls_back_to_page_count_when_next_missing(self) -> None:
        page = BrowsePage(page_count=5, page=2, next_page=None)
        assert page.has_next

    def test_empty_page(self) -> None:
        page = BrowsePage.from_api({"data": []}, page=1)
        assert len(page) == 0
        assert not page.has_next

    def test_search_returns_matching_types(self) -> None:
        page = BrowsePage.from_api(load_json("search_chat.json"), page=1)
        assert all(item.type is ContentType.CHAT_STORY for item in page.items)
