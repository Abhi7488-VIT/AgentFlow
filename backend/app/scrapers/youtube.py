"""
YouTube comment scraper.

Prefers the official Data API v3 when ``YOUTUBE_API_KEY`` is configured.
Without a key it falls back to innertube - the JSON API that youtube.com's
own front-end calls - which needs no credentials: the search page ships
its ``INNERTUBE_API_KEY`` and client version, and each watch page carries
the continuation token that loads its comment thread.

Synthetic data is the last resort and is always flagged ``is_mock``.
"""

from __future__ import annotations

import asyncio
import random
import re
from datetime import datetime, timedelta, timezone
from typing import Any

import httpx
import structlog

from app.config import settings
from app.scrapers.base import BaseScraper
from app.scrapers.web import (
    extract_embedded_json,
    first,
    new_client,
    parse_count,
    walk,
)

log: structlog.stdlib.BoundLogger = structlog.get_logger(__name__)

# ---------------------------------------------------------------------------
#  Mock data
# ---------------------------------------------------------------------------

_POSITIVE_COMMENTS: list[str] = [
    "This {product} is absolutely incredible! Best purchase I've made this year 🔥",
    "Been using the {product} for a month now and I'm blown away by the quality.",
    "Thanks for this review! I just ordered the {product} because of this video.",
    "The {product} is a game changer. Totally worth the investment.",
    "I've tried many alternatives and the {product} is by far the best option.",
    "Love my {product}! Everything about it is perfect for my needs.",
    "Great video! The {product} looks amazing. Definitely adding to my wishlist.",
    "Already have the {product} and can confirm everything said here. 10/10.",
    "The {product} exceeded my expectations in every way possible!",
    "Finally someone who understands why the {product} is so good! Great review.",
    "Bought the {product} after watching this. Best decision ever 👍",
    "My {product} arrived yesterday and I'm already in love with it.",
]

_NEGATIVE_COMMENTS: list[str] = [
    "I had the {product} and returned it after a week. Terrible quality.",
    "Sponsored much? The {product} has way too many issues you didn't mention.",
    "Don't waste your money on the {product}. I learned the hard way.",
    "The {product} broke within 3 days. Total garbage. Save your money.",
    "Worst {product} I've ever owned. Nothing like what was shown in this video.",
    "This video is misleading. The {product} has serious design flaws.",
    "Had the {product} for two months. Multiple defects. Very disappointed.",
    "The {product} overheats constantly. Not recommended at all.",
]

_NEUTRAL_COMMENTS: list[str] = [
    "The {product} is decent but there are better options at this price range.",
    "Interesting review of the {product}. I'm still on the fence about buying it.",
    "The {product} has pros and cons. Might work for some people but not for me.",
    "Does anyone know how the {product} compares to last year's model?",
    "I wish you compared the {product} with its main competitor.",
    "Decent {product} but the software needs a lot of work.",
    "The {product} is fine for casual use but falls short for professionals.",
    "Okay video but I wish you covered more about the {product} battery life.",
]

_VIDEO_TITLES: list[str] = [
    "{product} Review - Is It Worth It in 2025?",
    "I Tested the {product} for 30 Days - Honest Opinion",
    "{product} vs Competition - ULTIMATE Comparison",
    "Why Everyone is Buying the {product} Right Now",
    "The Truth About the {product} Nobody Tells You",
    "{product} Unboxing & First Impressions",
    "Don't Buy the {product} Before Watching This!",
    "Is the {product} Really That Good? Deep Dive Review",
    "{product} - 6 Months Later (Long Term Review)",
    "TOP 5 Reasons to Get the {product}",
]

_AUTHORS: list[str] = [
    "TechReviewer", "GadgetFan99", "SmartConsumer", "EarlyAdopter",
    "CriticalThinker", "BudgetBuyer", "ProTester", "DailyUser42",
    "HonestReview", "TechMom", "DigitalNomad", "PCMasterRace",
    "AppleFanBoy", "AndroidUser", "NeutralObserver", "CasualViewer",
    "PowerUserPro", "MinimalistTech", "GamerDude", "WorkFromHome",
]

_VIDEO_IDS: list[str] = [
    "dQw4w9WgXcQ", "kJQP7kiw5Fk", "JGwWNGJdvx8", "RgKAFK5djSk",
    "9bZkp7q19f0", "CevxZvSJLk8", "hT_nvWreIhg", "OPf0YbXqDm0",
    "fJ9rUzIMcZQ", "2Vv-BfVoq4g", "YQHsXMglC9A", "60ItHLz5WEA",
]


def _generate_mock_comments(query: str, count: int) -> list[dict[str, Any]]:
    """Generate realistic mock YouTube comments."""
    product_name = query.replace("+", " ").title()
    comments: list[dict[str, Any]] = []

    all_templates = (
        [(_POSITIVE_COMMENTS, "positive")] * 5
        + [(_NEGATIVE_COMMENTS, "negative")] * 2
        + [(_NEUTRAL_COMMENTS, "neutral")] * 3
    )

    video_title_templates = random.sample(
        _VIDEO_TITLES, min(len(_VIDEO_TITLES), 5)
    )
    video_titles = [t.format(product=product_name) for t in video_title_templates]

    for i in range(count):
        templates, _ = random.choice(all_templates)
        template = random.choice(templates)
        content = template.format(product=product_name)

        days_ago = random.randint(1, 180)
        comment_date = (datetime.now(timezone.utc) - timedelta(days=days_ago)).strftime(
            "%Y-%m-%dT%H:%M:%SZ"
        )

        comments.append(
            {
                "source": "youtube",
                "content": content,
                "metadata": {
                    "is_mock": True,
                    "author": random.choice(_AUTHORS),
                    "likes": random.randint(0, 2500),
                    "date": comment_date,
                    "video_title": random.choice(video_titles),
                    "video_id": random.choice(_VIDEO_IDS),
                },
            }
        )

    return comments


# ---------------------------------------------------------------------------
#  Relative-date handling
# ---------------------------------------------------------------------------

_RELATIVE_UNITS: dict[str, int] = {
    "second": 0, "minute": 0, "hour": 0,
    "day": 1, "week": 7, "month": 30, "year": 365,
}


def _relative_to_date(text: str) -> str:
    """Turn YouTube's '3 months ago' into an absolute date.

    The trend analyzer bins by calendar period, so a relative string is
    useless to it. Anything unparseable falls back to today rather than a
    fixed epoch, which would pile every such comment into one fake bucket.
    """
    now = datetime.now(timezone.utc)
    if not text:
        return now.strftime("%Y-%m-%d")

    match = re.search(r"(\d+)\s+(second|minute|hour|day|week|month|year)s?\s+ago", text.lower())
    if not match:
        return now.strftime("%Y-%m-%d")

    amount = int(match.group(1))
    days = _RELATIVE_UNITS.get(match.group(2), 0) * amount
    return (now - timedelta(days=days)).strftime("%Y-%m-%d")


# ---------------------------------------------------------------------------
#  Scraper implementation
# ---------------------------------------------------------------------------

class YouTubeScraper(BaseScraper):
    """Collects YouTube comments for videos matching a query.

    Two live strategies, tried in order:

    1. **Data API v3** when ``YOUTUBE_API_KEY`` is set. Officially supported
       and quota-metered, so it is always preferred when available.
    2. **innertube**, the JSON API youtube.com's own front-end calls. It
       needs no key: the page ships its ``INNERTUBE_API_KEY`` and client
       version, and the comment thread is fetched with the continuation
       token embedded in the watch page.

    Synthetic data is the last resort and is always flagged ``is_mock``.
    """

    _YOUTUBE = "https://www.youtube.com"

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(request_delay=1.0, **kwargs)
        self.logger = log.bind(scraper="YouTubeScraper")

    # ------------------------------------------------------------------ #
    #  Official Data API v3
    # ------------------------------------------------------------------ #

    def _get_youtube_service(self) -> Any | None:
        """Build a Data API client, or None when no key is configured."""
        if not settings.YOUTUBE_API_KEY:
            return None
        try:
            from googleapiclient.discovery import build

            return build(
                "youtube", "v3",
                developerKey=settings.YOUTUBE_API_KEY,
                cache_discovery=False,
            )
        except Exception as exc:  # noqa: BLE001
            self.logger.warning("youtube_service_init_failed", error=str(exc))
            return None

    async def _api_collect(
        self,
        service: Any,
        query: str,
        max_results: int,
    ) -> list[dict[str, Any]]:
        """Search and fetch comment threads through the official API."""

        def _run() -> list[dict[str, Any]]:
            search = service.search().list(
                q=query, part="id,snippet", type="video",
                maxResults=5, relevanceLanguage="en", order="relevance",
            ).execute()

            videos = [
                {
                    "video_id": item["id"]["videoId"],
                    "title": item["snippet"]["title"],
                    "channel": item["snippet"].get("channelTitle", ""),
                }
                for item in search.get("items", [])
                if item.get("id", {}).get("videoId")
            ]
            if not videos:
                return []

            collected: list[dict[str, Any]] = []
            per_video = max(max_results // len(videos), 10)

            for video in videos:
                try:
                    threads = service.commentThreads().list(
                        part="snippet", videoId=video["video_id"],
                        maxResults=min(per_video, 100),
                        order="relevance", textFormat="plainText",
                    ).execute()
                except Exception as exc:  # noqa: BLE001
                    # Comments disabled on a video is normal, not fatal.
                    self.logger.info(
                        "youtube_comments_unavailable",
                        video_id=video["video_id"], error=str(exc)[:120],
                    )
                    continue

                for item in threads.get("items", []):
                    snippet = item["snippet"]["topLevelComment"]["snippet"]
                    collected.append({
                        "source": "youtube",
                        "content": snippet.get("textDisplay", ""),
                        "metadata": {
                            "is_mock": False,
                            "author": snippet.get("authorDisplayName", ""),
                            "likes": snippet.get("likeCount", 0),
                            "date": (snippet.get("publishedAt", "") or "")[:10],
                            "video_title": video["title"],
                            "video_id": video["video_id"],
                            "channel": video["channel"],
                            "collection_method": "data_api_v3",
                        },
                    })

                if len(collected) >= max_results:
                    break

            return collected[:max_results]

        return await asyncio.to_thread(_run)

    # ------------------------------------------------------------------ #
    #  innertube (no API key required)
    # ------------------------------------------------------------------ #

    async def _innertube_context(
        self,
        client: httpx.AsyncClient,
        query: str,
    ) -> tuple[str | None, str, list[dict[str, str]]]:
        """Search YouTube and read the page's own API credentials from it."""
        response = await client.get(
            f"{self._YOUTUBE}/results", params={"search_query": query}
        )
        if response.status_code != 200:
            self.logger.warning("youtube_search_failed", status=response.status_code)
            return None, "", []

        html = response.text
        key_match = re.search(r'"INNERTUBE_API_KEY":"([\w-]+)"', html)
        version_match = re.search(r'"clientVersion":"([\d.]+)"', html)
        client_version = version_match.group(1) if version_match else "2.20240101.00.00"

        data = extract_embedded_json(html, "ytInitialData")
        videos: list[dict[str, str]] = []
        seen: set[str] = set()

        if data:
            for renderer in walk(data, "videoRenderer"):
                video_id = renderer.get("videoId")
                if not video_id or video_id in seen:
                    continue
                seen.add(video_id)

                title = first(renderer.get("title", {}), "text", "")
                channel = first(renderer.get("ownerText", {}), "text", "")
                videos.append({
                    "video_id": video_id,
                    "title": title or "",
                    "channel": channel or "",
                })

        return (key_match.group(1) if key_match else None), client_version, videos

    async def _innertube_comments(
        self,
        client: httpx.AsyncClient,
        api_key: str,
        client_version: str,
        video: dict[str, str],
        limit: int,
    ) -> list[dict[str, Any]]:
        """Fetch a video's top comments through the continuation endpoint."""
        watch = await client.get(
            f"{self._YOUTUBE}/watch", params={"v": video["video_id"]}
        )
        if watch.status_code != 200:
            return []

        data = extract_embedded_json(watch.text, "ytInitialData")
        if not data:
            return []

        # The watch page holds several continuations; only the one on the
        # comment-item-section loads comments rather than related videos.
        token = None
        for section in walk(data, "itemSectionRenderer"):
            if section.get("sectionIdentifier") == "comment-item-section":
                token = first(section, "token")
                if token:
                    break
        if not token:
            self.logger.info(
                "youtube_no_comment_section", video_id=video["video_id"]
            )
            return []

        payload = {
            "context": {
                "client": {
                    "clientName": "WEB",
                    "clientVersion": client_version,
                    "hl": "en",
                    "gl": "US",
                }
            },
            "continuation": token,
        }
        response = await client.post(
            f"{self._YOUTUBE}/youtubei/v1/next",
            params={"key": api_key},
            json=payload,
            headers={"Content-Type": "application/json", "Origin": self._YOUTUBE},
        )
        if response.status_code != 200:
            self.logger.warning(
                "youtube_innertube_failed", status=response.status_code
            )
            return []

        comments: list[dict[str, Any]] = []
        for entity in walk(response.json(), "commentEntityPayload"):
            properties = entity.get("properties", {})
            content = (properties.get("content") or {}).get("content")
            if not content:
                continue

            author = (entity.get("author") or {}).get("displayName", "")
            toolbar = entity.get("toolbar") or {}

            comments.append({
                "source": "youtube",
                "content": content,
                "metadata": {
                    "is_mock": False,
                    "author": author,
                    "likes": parse_count(toolbar.get("likeCountNotliked", 0)),
                    "date": _relative_to_date(properties.get("publishedTime", "")),
                    "published_relative": properties.get("publishedTime", ""),
                    "video_title": video["title"],
                    "video_id": video["video_id"],
                    "channel": video["channel"],
                    "collection_method": "innertube",
                },
            })

            if len(comments) >= limit:
                break

        return comments

    async def _innertube_collect(
        self,
        query: str,
        max_results: int,
    ) -> list[dict[str, Any]]:
        """Search, then walk the top videos collecting their comments."""
        async with new_client() as client:
            api_key, client_version, videos = await self._innertube_context(client, query)

            if not api_key or not videos:
                self.logger.warning(
                    "youtube_innertube_context_missing",
                    has_key=bool(api_key), videos=len(videos),
                )
                return []

            self.logger.info("youtube_videos_found", count=len(videos))

            collected: list[dict[str, Any]] = []
            targets = videos[:5]
            per_video = max(max_results // max(len(targets), 1), 10)

            for video in targets:
                if len(collected) >= max_results:
                    break

                comments = await self._innertube_comments(
                    client, api_key, client_version, video, per_video
                )
                collected.extend(comments)
                await asyncio.sleep(self.request_delay)

            return collected[:max_results]

    # ------------------------------------------------------------------ #
    #  Main implementation
    # ------------------------------------------------------------------ #

    def _mock(self, query: str, max_results: int, reason: str) -> list[dict[str, Any]]:
        """Labelled synthetic data, or a hard failure if mocks are disabled."""
        if not settings.ALLOW_MOCK_DATA:
            raise RuntimeError(
                f"YouTube collection unavailable ({reason}) and ALLOW_MOCK_DATA is False"
            )
        self.logger.info("youtube_fallback_mock", reason=reason)
        count = random.randint(30, max(30, min(50, max_results)))
        return _generate_mock_comments(query, count)

    async def _scrape_impl(
        self,
        query: str,
        max_results: int,
    ) -> list[dict[str, Any]]:
        if settings.DEBUG:
            return self._mock(query, max_results, "DEBUG=True")

        # 1. Official API when a key is configured.
        service = self._get_youtube_service()
        if service is not None:
            try:
                results = await self._api_collect(service, query, max_results)
                if results:
                    self.logger.info("youtube_api_results", count=len(results))
                    return results
                self.logger.info("youtube_api_empty_falling_back")
            except Exception as exc:  # noqa: BLE001
                self.logger.warning("youtube_api_error", error=str(exc)[:160])

        # 2. innertube, which needs no credentials.
        try:
            results = await self._innertube_collect(query, max_results)
            if results:
                self.logger.info("youtube_innertube_results", count=len(results))
                return results
        except Exception as exc:  # noqa: BLE001
            self.logger.error("youtube_innertube_error", error=str(exc)[:160])

        return self._mock(query, max_results, "all_live_strategies_failed")
