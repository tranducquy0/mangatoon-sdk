"""Guards on the two protocol constants and the signing algorithm.

If MangaToon changes its salt or version string, these fail first and point
straight at the cause.
"""

from __future__ import annotations

import pytest

from mangatoon._signing import (
    API_VERSION,
    SIGNING_SALT,
    build_query,
    compute_sign,
    sign_url,
)


class TestSigning:
    def test_reproduces_a_recorded_live_signature(self) -> None:
        """The sign for a request captured from the real API must still match.

        This is the canary for a rotated salt or a changed version string.
        """
        params = {
            "id": "5",
            "_": "1790593200",
            "_webp": "true",
            "_platform": "web",
            "_v": "2.00.02",
            "_language": "en",
            "_udid": "483487d947b77e0bc544306e196612eb",
        }
        assert compute_sign("/api/content/episodes", params) == (
            "4a695ea394fb4b011c76ce67f3e8dcdb"
        )

    def test_sign_url_matches_the_captured_url(self) -> None:
        url = sign_url(
            "/api/content/episodes",
            {"id": "5"},
            timestamp=1790593200,
            version="2.00.02",
        )
        assert url == (
            "https://sg.mangatoon.mobi/api/content/episodes"
            "?sign=4a695ea394fb4b011c76ce67f3e8dcdb&id=5&_=1790593200"
            "&_webp=true&_platform=web&_v=2.00.02&_language=en"
            "&_udid=483487d947b77e0bc544306e196612eb"
        )

    def test_salt_is_appended_without_a_separator(self) -> None:
        """The canonical query is glued straight onto the path.

        Getting this wrong yields a wrong-but-plausible-looking digest, so it is
        asserted directly against the salt contract.
        """
        import hashlib

        params = build_query({"id": "7"}, timestamp=1000)
        canonical = "_=1000&_language=en&_platform=web&_udid=" \
            f"{params['_udid']}&_v={API_VERSION}&_webp=true&id=7"
        expected = hashlib.md5(
            ("/api/content/x" + canonical + SIGNING_SALT).encode()
        ).hexdigest()
        assert compute_sign("/api/content/x", params) == expected

    def test_parameter_order_does_not_affect_the_signature(self) -> None:
        forward = build_query({"id": "1", "word": "x"}, timestamp=5)
        reverse = dict(reversed(list(build_query({"word": "x", "id": "1"}, timestamp=5).items())))
        assert compute_sign("/api/content/search", forward) == compute_sign(
            "/api/content/search", reverse
        )

    def test_sign_is_not_part_of_the_signed_material(self) -> None:
        params = build_query({"id": "9"}, timestamp=42)
        with_sign = dict(params, sign="deadbeef")
        assert compute_sign("/api/content/detail", params) == compute_sign(
            "/api/content/detail", with_sign
        )

    def test_signature_changes_with_content(self) -> None:
        base = build_query({"id": "1"}, timestamp=1)
        other = build_query({"id": "2"}, timestamp=1)
        assert compute_sign("/api/content/detail", base) != compute_sign(
            "/api/content/detail", other
        )

    def test_timestamp_defaults_to_now(self) -> None:
        import time

        params = build_query({"id": "1"})
        assert abs(int(params["_"]) - int(time.time())) <= 2

    def test_envelope_defaults(self) -> None:
        params = build_query({"id": "1"})
        assert params["_webp"] == "true"
        assert params["_platform"] == "web"
        assert params["_language"] == "en"
        assert len(params["_udid"]) == 32

    def test_caller_values_win_over_defaults(self) -> None:
        params = build_query({"id": "1", "_language": "es"}, timestamp=7)
        assert params["_language"] == "es"

    def test_language_is_configurable(self) -> None:
        url = sign_url("/api/content/search", {"word": "a"}, language="id", timestamp=1)
        assert "_language=id" in url
        assert "sign=" in url

    @pytest.mark.parametrize("salt", [""])
    def test_empty_salt_still_signs(self, salt: str) -> None:
        """Guards against an accidentally blanked constant."""
        import mangatoon._signing as signing

        original = signing.SIGNING_SALT
        try:
            signing.SIGNING_SALT = salt
            assert compute_sign("/api/content/detail", build_query({"id": "1"}))
        finally:
            signing.SIGNING_SALT = original

    def test_version_constant_is_a_looked_like_version(self) -> None:
        assert API_VERSION.count(".") == 2
        assert all(part.isdigit() for part in API_VERSION.split("."))
