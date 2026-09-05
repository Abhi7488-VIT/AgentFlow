"""Tests for the scraping layer.

Parsing is tested against HTML/JSON fixtures shaped like what the real
sites return, so these run offline and stay meaningful even when a site is
blocking us. Network paths are covered by their fallback behaviour.
"""

import pytest

from app.config import settings
from app.scrapers.amazon import (
    AmazonScraper,
    _is_blocked,
    _parse_rating,
    _parse_review_date,
)
from app.scrapers.web import (
    browser_headers,
    extract_embedded_json,
    first,
    parse_count,
    walk,
)
from app.scrapers.youtube import YouTubeScraper, _relative_to_date


class TestWebHelpers:
    def test_headers_look_like_a_browser(self):
        headers = browser_headers()
        for required in ("User-Agent", "Accept", "Accept-Language", "Sec-Fetch-Mode"):
            assert required in headers
        assert "Mozilla" in headers["User-Agent"]

    def test_referer_changes_fetch_site(self):
        assert browser_headers()["Sec-Fetch-Site"] == "none"
        with_ref = browser_headers(referer="https://example.com/")
        assert with_ref["Sec-Fetch-Site"] == "same-origin"
        assert with_ref["Referer"] == "https://example.com/"

    def test_only_advertises_decodable_encodings(self):
        """Claiming brotli without the decoder returns undecodable bytes."""
        encoding = browser_headers()["Accept-Encoding"]
        if "br" in encoding:
            import brotli  # noqa: F401  - must be importable if advertised

    def test_extract_embedded_json_handles_braces_in_strings(self):
        html = 'var ytInitialData = {"a": "text with } brace", "b": {"c": 1}};</script>'
        assert extract_embedded_json(html, "ytInitialData") == {
            "a": "text with } brace", "b": {"c": 1},
        }

    def test_extract_embedded_json_handles_escaped_quotes(self):
        html = r'ytInitialData = {"a": "he said \"hi\"", "b": 2};'
        assert extract_embedded_json(html, "ytInitialData")["b"] == 2

    def test_extract_embedded_json_missing_marker(self):
        assert extract_embedded_json("<html></html>", "ytInitialData") is None

    def test_walk_finds_keys_at_any_depth(self):
        tree = {"a": [{"target": 1}, {"b": {"target": 2}}], "target": 3}
        assert sorted(walk(tree, "target")) == [1, 2, 3]

    def test_first_returns_default_when_absent(self):
        assert first({"a": 1}, "missing", "fallback") == "fallback"

    @pytest.mark.parametrize("raw,expected", [
        ("1.1K", 1100), ("15K", 15000), ("2M", 2000000),
        ("2,340", 2340), (42, 42), ("", 0), ("nonsense", 0), (None, 0),
    ])
    def test_parse_count(self, raw, expected):
        assert parse_count(raw) == expected


class TestYouTubeParsing:
    @pytest.mark.parametrize("relative,delta_days", [
        ("1 day ago", 1), ("3 weeks ago", 21), ("2 months ago", 60),
    ])
    def test_relative_dates_resolve(self, relative, delta_days):
        from datetime import datetime, timedelta, timezone

        expected = (datetime.now(timezone.utc) - timedelta(days=delta_days)).strftime("%Y-%m-%d")
        assert _relative_to_date(relative) == expected

    def test_unparseable_relative_date_uses_today(self):
        from datetime import datetime, timezone

        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        assert _relative_to_date("") == today
        assert _relative_to_date("some time ago") == today

    def test_comment_payload_shape(self):
        """The innertube response nests comments under commentEntityPayload."""
        payload = {
            "frameworkUpdates": {
                "entityBatchUpdate": {
                    "mutations": [{
                        "payload": {
                            "commentEntityPayload": {
                                "properties": {
                                    "content": {"content": "Great battery life"},
                                    "publishedTime": "2 months ago",
                                },
                                "author": {"displayName": "@someone"},
                                "toolbar": {"likeCountNotliked": "1.1K"},
                            }
                        }
                    }]
                }
            }
        }
        entities = list(walk(payload, "commentEntityPayload"))

        assert len(entities) == 1
        entity = entities[0]
        assert entity["properties"]["content"]["content"] == "Great battery life"
        assert parse_count(entity["toolbar"]["likeCountNotliked"]) == 1100


class TestAmazonParsing:
    @pytest.mark.parametrize("text,expected", [
        ("Reviewed in India on 26 August 2025", "2025-08-26"),
        ("Reviewed in the United States on August 26, 2025", "2025-08-26"),
        ("Reviewed in the United Kingdom on 1 January 2024", "2024-01-01"),
    ])
    def test_review_dates(self, text, expected):
        assert _parse_review_date(text) == expected

    def test_invalid_date_falls_back_to_today(self):
        from datetime import datetime, timezone

        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        assert _parse_review_date("nonsense") == today
        assert _parse_review_date("Reviewed on 99 Foobar 2025") == today

    @pytest.mark.parametrize("text,expected", [
        ("5.0 out of 5 stars", 5.0), ("4 out of 5 stars", 4.0),
        ("1.0 out of 5 stars", 1.0), ("no rating", None), ("", None),
    ])
    def test_rating_parsing(self, text, expected):
        assert _parse_rating(text) == expected

    @pytest.mark.parametrize("html,blocked", [
        ("<p>Sorry, something went wrong</p>", True),
        ("<title>Amazon Sign-In</title>", True),
        ("<p>Enter the characters you see below</p>", True),
        ("<div data-asin='B01'>Real page</div>", False),
    ])
    def test_block_detection(self, html, blocked):
        assert (_is_blocked(html) is not None) == blocked

    def test_search_results_parse(self):
        html = """
        <div data-asin="B09XS7JWHH"><h2><a><span>Sony WH-1000XM5 Headphones</span></a></h2></div>
        <div data-asin="B0C9L8ZR6Q"><h2><a><span>Bose QuietComfort</span></a></h2></div>
        <div data-asin=""><h2><a><span>No ASIN</span></a></h2></div>
        <div data-asin="B09XS7JWHH"><h2><a><span>Duplicate</span></a></h2></div>
        """
        products = AmazonScraper()._parse_search_results(html)

        assert [p["asin"] for p in products] == ["B09XS7JWHH", "B0C9L8ZR6Q"]
        assert products[0]["title"] == "Sony WH-1000XM5 Headphones"

    def test_reviews_parse_with_current_hooks(self):
        """Amazon renamed its hooks to reviewTitle / reviewRichContentContainer."""
        html = """
        <div data-hook="review">
          <span class="a-profile-name">Nishant</span>
          <i data-hook="review-star-rating"><span>5.0 out of 5 stars</span></i>
          <h5 data-hook="reviewTitle"><span>Absolutely brilliant</span></h5>
          <span data-hook="review-date">Reviewed in India on 26 August 2025</span>
          <span data-hook="avp-badge">Verified Purchase</span>
          <div data-hook="reviewRichContentContainer">
            Battery life is outstanding and the noise cancelling is superb.
          </div>
          <span data-hook="helpful-vote-statement">38 people found this helpful</span>
        </div>
        """
        reviews = AmazonScraper()._parse_reviews(html, "Sony WH-1000XM5", "amazon.in")

        assert len(reviews) == 1
        review, meta = reviews[0], reviews[0]["metadata"]
        assert "noise cancelling is superb" in review["content"]
        assert meta["rating"] == 5.0
        assert meta["date"] == "2025-08-26"
        assert meta["verified"] is True
        assert meta["author"] == "Nishant"
        assert meta["helpful_votes"] == 38
        assert meta["is_mock"] is False
        assert meta["marketplace"] == "amazon.in"

    def test_duplicate_reviews_are_collapsed(self):
        """Amazon renders each review twice - inline and in a modal."""
        block = """
        <div data-hook="review">
          <div data-hook="reviewRichContentContainer">
            The very same review text repeated in the modal popover markup.
          </div>
        </div>
        """
        reviews = AmazonScraper()._parse_reviews(block * 2, "Product", "amazon.com")
        assert len(reviews) == 1

    def test_truncation_boilerplate_is_stripped(self):
        html = """
        <div data-hook="review">
          <div data-hook="reviewText">
            Brief content visible, double tap to read full content.
            Genuinely excellent headphones with superb battery life.
            Read more
          </div>
        </div>
        """
        content = AmazonScraper()._parse_reviews(html, "P", "amazon.com")[0]["content"]

        assert "Brief content visible" not in content
        assert "Read more" not in content
        assert "Genuinely excellent headphones" in content

    def test_reviews_without_a_body_are_skipped(self):
        html = '<div data-hook="review"><span class="a-profile-name">X</span></div>'
        assert AmazonScraper()._parse_reviews(html, "P", "amazon.com") == []


@pytest.mark.asyncio
class TestFallbackBehaviour:
    """Every scraper must degrade to labelled mock data, never silently fake."""

    async def test_debug_mode_returns_labelled_mock(self, monkeypatch):
        monkeypatch.setattr(settings, "DEBUG", True)

        for scraper in (AmazonScraper(), YouTubeScraper()):
            items = await scraper.scrape("test product", max_results=10)
            assert items
            assert all(i["metadata"]["is_mock"] is True for i in items)

    async def test_mock_can_be_disabled(self, monkeypatch):
        monkeypatch.setattr(settings, "DEBUG", True)
        monkeypatch.setattr(settings, "ALLOW_MOCK_DATA", False)

        with pytest.raises(RuntimeError):
            await AmazonScraper(max_retries=1).scrape("test", max_results=5)
