"""
Reddit scraper using the official Reddit OAuth2 API.

Reddit blocks unauthenticated access to its ``.json`` endpoints, so live
collection requires an app registered at https://www.reddit.com/prefs/apps
(type "script"). Authentication uses the application-only
``client_credentials`` grant, which needs no user login, and the bearer
token is cached on the class until shortly before it expires.

When no credentials are configured the scraper falls back to clearly
labelled synthetic data (every item carries ``metadata.is_mock = True``)
so demo output can never be mistaken for real Reddit content.
"""

from __future__ import annotations

import asyncio
import base64
import random
import time
from datetime import datetime, timedelta, timezone
from typing import Any

import httpx
import structlog

from app.config import settings
from app.scrapers.base import BaseScraper

log: structlog.stdlib.BoundLogger = structlog.get_logger(__name__)

# Reddit OAuth2 endpoints
_TOKEN_URL = "https://www.reddit.com/api/v1/access_token"
_API_BASE = "https://oauth.reddit.com"
_TOKEN_TTL_MARGIN = 60  # refresh this many seconds before expiry

# ---------------------------------------------------------------------------
#  Default subreddits to search when no product-specific sub is obvious
# ---------------------------------------------------------------------------
_DEFAULT_SUBREDDITS: list[str] = [
    "technology", "gadgets", "BuyItForLife", "productreviews",
    "hardware", "consumerelectronics", "techdeals",
]

# ---------------------------------------------------------------------------
#  Mock data
# ---------------------------------------------------------------------------

_POSITIVE_POSTS: list[str] = [
    "Just got the {product} and it's amazing! Highly recommend to anyone considering it.",
    "PSA: The {product} is on sale right now and it's 100% worth the full price, let alone discounted.",
    "My {product} review after 6 months of daily use - still going strong!",
    "Switched from the competitor to {product} and the difference is night and day.",
    "Can we talk about how underrated the {product} is? Seriously one of the best in its category.",
    "Finally pulled the trigger on the {product}. Why did I wait so long?",
    "The {product} community doesn't talk enough about how good the build quality is.",
    "Three months in with my {product} - here are my detailed impressions (spoiler: it's great).",
    "If you're on the fence about the {product}, just buy it. You won't regret it.",
    "The {product} is hands down the best purchase I've made this year. Fight me.",
]

_NEGATIVE_POSTS: list[str] = [
    "Warning: My {product} died after only 2 months of use. Quality control seems terrible.",
    "Am I the only one having issues with the {product}? Multiple defects out of the box.",
    "Returned my {product} today. It's nowhere near as good as the marketing suggests.",
    "The {product} has a serious overheating problem that nobody is talking about.",
    "Buyer beware: The {product} customer support is absolutely terrible. Here's my experience.",
    "Hot take: The {product} is the most overrated product of the year. Here's why.",
    "Don't buy the {product} - there's a known firmware issue causing data loss.",
    "My {product} started making a clicking noise after 3 weeks. Anyone else?",
]

_NEUTRAL_POSTS: list[str] = [
    "Looking for opinions: {product} vs alternatives? Can't decide.",
    "Honest question - is the {product} worth the price or should I wait for next gen?",
    "The {product} is a solid B-tier option. Here's my balanced review with pros and cons.",
    "For those asking about the {product}: it's fine for most people. Not amazing, not terrible.",
    "Comparing {product} with its main competitor - they're surprisingly similar.",
    "Quick question about the {product}: does anyone know if the new version fixed the old issues?",
    "Got the {product} for a reasonable price. AMA about my experience so far.",
    "The {product} does what it says. Nothing more, nothing less. Mid-range at its finest.",
]

_REPLY_TEMPLATES: list[str] = [
    "I agree with this. The {product} is exactly as you described.",
    "Had a completely different experience with the {product}. Mine works flawlessly.",
    "This is spot on. I've been saying the same thing about the {product} for months.",
    "Can confirm. The {product} is solid but not without its quirks.",
    "Depends on the use case. For my workflow, the {product} is perfect.",
    "I returned mine too. The {product} just wasn't for me.",
    "Interesting perspective. I'll keep this in mind when my {product} arrives.",
    "The {product} community is really helpful. Thanks for sharing your experience!",
    "As a long-time {product} user, I can say the quality has gone downhill recently.",
    "Just ordered the {product} based on this thread. Fingers crossed!",
]

_SUBREDDITS: list[str] = [
    "technology", "gadgets", "BuyItForLife", "productreviews",
    "AskTechnology", "hardware", "TechSupport", "deals",
    "SuggestAProduct", "ProductTesting",
]

_AUTHORS: list[str] = [
    "tech_enthusiast_42", "honest_reviewer", "budget_conscious",
    "daily_driver_user", "early_adopter_99", "critical_eye_2024",
    "power_user_pro", "casual_consumer", "gadget_guru_x",
    "minimalist_buyer", "quality_matters", "return_specialist",
    "first_timer", "long_term_user", "skeptic_shopper",
    "deal_hunter", "pro_tester", "avg_joe_tech",
    "smart_money", "weekend_warrior",
]


def _generate_mock_data(query: str, count: int) -> list[dict[str, Any]]:
    """Generate realistic mock Reddit posts and comments.

    Every item is flagged ``is_mock`` so downstream consumers - and anyone
    reading a report - can tell synthetic data from live data.
    """
    product_name = query.replace("+", " ").title()
    items: list[dict[str, Any]] = []

    all_templates = (
        _POSITIVE_POSTS * 2
        + _NEGATIVE_POSTS
        + _NEUTRAL_POSTS
        + _REPLY_TEMPLATES * 2
    )

    for i in range(count):
        template = random.choice(all_templates)
        content = template.format(product=product_name)

        days_ago = random.randint(1, 365)
        post_date = (
            datetime.now(timezone.utc) - timedelta(days=days_ago)
        ).strftime("%Y-%m-%d")

        is_post = random.random() > 0.4  # 60% posts, 40% comments

        items.append(
            {
                "source": "reddit",
                "content": content,
                "metadata": {
                    "is_mock": True,
                    "subreddit": random.choice(_SUBREDDITS),
                    "score": random.randint(-5, 5000),
                    "author": random.choice(_AUTHORS),
                    "date": post_date,
                    "post_title": (
                        template.format(product=product_name)[:80]
                        if is_post
                        else f"Re: {product_name} discussion"
                    ),
                    "num_comments": random.randint(0, 500) if is_post else 0,
                    "type": "post" if is_post else "comment",
                },
            }
        )

    return items


# ---------------------------------------------------------------------------
#  Scraper implementation
# ---------------------------------------------------------------------------

class RedditScraper(BaseScraper):
    """Collects Reddit posts and comments through the official OAuth2 API.

    Falls back to clearly labelled synthetic data when credentials are
    missing, when ``settings.DEBUG`` is ``True``, or when live access
    fails - unless ``settings.ALLOW_MOCK_DATA`` is ``False``, in which case
    the failure is raised so the caller sees it.
    """

    # Token is cached on the class so parallel scrapes share one login.
    _token: str | None = None
    _token_expires_at: float = 0.0
    _token_lock: asyncio.Lock | None = None

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(request_delay=1.5, **kwargs)
        self.logger = log.bind(scraper="RedditScraper")

    # ------------------------------------------------------------------ #
    #  OAuth2 (application-only / client_credentials)
    # ------------------------------------------------------------------ #

    @property
    def _has_credentials(self) -> bool:
        return bool(settings.REDDIT_CLIENT_ID and settings.REDDIT_CLIENT_SECRET)

    @classmethod
    def _get_lock(cls) -> asyncio.Lock:
        if cls._token_lock is None:
            cls._token_lock = asyncio.Lock()
        return cls._token_lock

    async def _get_access_token(self) -> str | None:
        """Fetch (or reuse) an application-only bearer token."""
        if not self._has_credentials:
            return None

        if RedditScraper._token and time.monotonic() < RedditScraper._token_expires_at:
            return RedditScraper._token

        async with self._get_lock():
            # Another coroutine may have refreshed the token while we waited.
            if RedditScraper._token and time.monotonic() < RedditScraper._token_expires_at:
                return RedditScraper._token

            basic = base64.b64encode(
                f"{settings.REDDIT_CLIENT_ID}:{settings.REDDIT_CLIENT_SECRET}".encode()
            ).decode()

            try:
                async with httpx.AsyncClient(timeout=20) as client:
                    response = await client.post(
                        _TOKEN_URL,
                        data={"grant_type": "client_credentials"},
                        headers={
                            "Authorization": f"Basic {basic}",
                            "User-Agent": settings.REDDIT_USER_AGENT,
                        },
                    )

                if response.status_code != 200:
                    self.logger.error(
                        "reddit_auth_failed",
                        status=response.status_code,
                        body=response.text[:200],
                    )
                    return None

                payload = response.json()
                token = payload.get("access_token")
                expires_in = int(payload.get("expires_in", 3600))

                RedditScraper._token = token
                RedditScraper._token_expires_at = (
                    time.monotonic() + max(expires_in - _TOKEN_TTL_MARGIN, 60)
                )
                self.logger.info("reddit_auth_success", expires_in=expires_in)
                return token

            except Exception as exc:  # noqa: BLE001
                self.logger.error("reddit_auth_error", error=str(exc))
                return None

    # ------------------------------------------------------------------ #
    #  Live collection
    # ------------------------------------------------------------------ #

    async def _get(
        self,
        client: httpx.AsyncClient,
        path: str,
        params: dict[str, Any],
    ) -> Any:
        """GET an oauth.reddit.com path, honouring the API rate limit."""
        try:
            response = await client.get(f"{_API_BASE}{path}", params=params)

            if response.status_code == 429:
                self.logger.warning("reddit_rate_limited", path=path)
                await asyncio.sleep(5)
                return None
            if response.status_code != 200:
                self.logger.warning(
                    "reddit_api_error", path=path, status=response.status_code
                )
                return None

            # Back off proactively when the quota is nearly spent.
            remaining = response.headers.get("x-ratelimit-remaining")
            if remaining is not None:
                try:
                    if float(remaining) < 5:
                        reset = float(response.headers.get("x-ratelimit-reset", 10))
                        self.logger.info("reddit_quota_low", sleeping=reset)
                        await asyncio.sleep(min(reset, 60))
                except ValueError:
                    pass

            return response.json()

        except Exception as exc:  # noqa: BLE001
            self.logger.warning("reddit_request_failed", path=path, error=str(exc))
            return None

    @staticmethod
    def _post_item(data: dict[str, Any]) -> dict[str, Any]:
        """Map a Reddit submission onto the common scraped-item shape."""
        title = data.get("title") or ""
        selftext = data.get("selftext") or ""
        content = f"{title}\n\n{selftext}" if selftext else title

        return {
            "source": "reddit",
            "content": content.strip(),
            "metadata": {
                "is_mock": False,
                "subreddit": data.get("subreddit", ""),
                "score": data.get("score", 0),
                "author": data.get("author") or "[deleted]",
                "date": datetime.fromtimestamp(
                    data.get("created_utc", 0), tz=timezone.utc
                ).strftime("%Y-%m-%d"),
                "post_title": title,
                "num_comments": data.get("num_comments", 0),
                "permalink": data.get("permalink", ""),
                "type": "post",
            },
        }

    @staticmethod
    def _comment_item(
        data: dict[str, Any],
        post_title: str,
        subreddit: str,
    ) -> dict[str, Any]:
        """Map a Reddit comment onto the common scraped-item shape."""
        return {
            "source": "reddit",
            "content": data.get("body", ""),
            "metadata": {
                "is_mock": False,
                "subreddit": subreddit,
                "score": data.get("score", 0),
                "author": data.get("author") or "[deleted]",
                "date": datetime.fromtimestamp(
                    data.get("created_utc", 0), tz=timezone.utc
                ).strftime("%Y-%m-%d"),
                "post_title": post_title,
                "num_comments": 0,
                "type": "comment",
            },
        }

    async def _fetch_comments(
        self,
        client: httpx.AsyncClient,
        post: dict[str, Any],
        limit: int = 5,
    ) -> list[dict[str, Any]]:
        """Fetch the top comments on one submission."""
        post_id = post.get("id")
        if not post_id:
            return []

        payload = await self._get(
            client,
            f"/comments/{post_id}",
            {"limit": limit, "sort": "top", "depth": 1, "raw_json": 1},
        )
        # The comments endpoint returns [post_listing, comment_listing].
        if not isinstance(payload, list) or len(payload) < 2:
            return []

        children = payload[1].get("data", {}).get("children", [])
        items: list[dict[str, Any]] = []

        for child in children[:limit]:
            if child.get("kind") != "t1":  # skip "load more" stubs
                continue
            data = child.get("data", {})
            body = data.get("body", "")
            if len(body) > 10 and body not in ("[deleted]", "[removed]"):
                items.append(
                    self._comment_item(
                        data, post.get("title", ""), post.get("subreddit", "")
                    )
                )

        return items

    async def _search_reddit(
        self,
        token: str,
        query: str,
        max_results: int,
    ) -> list[dict[str, Any]]:
        """Search Reddit site-wide and in topical subreddits, plus top comments."""
        headers = {
            "Authorization": f"Bearer {token}",
            "User-Agent": settings.REDDIT_USER_AGENT,
        }
        results: list[dict[str, Any]] = []
        seen_ids: set[str] = set()

        # Site-wide search first, then narrow topical subreddits.
        searches: list[tuple[str, dict[str, Any]]] = [
            ("/search", {"q": query, "sort": "relevance", "t": "year",
                         "limit": 25, "type": "link", "raw_json": 1})
        ]
        searches += [
            (f"/r/{sub}/search",
             {"q": query, "restrict_sr": 1, "sort": "relevance",
              "t": "year", "limit": 10, "raw_json": 1})
            for sub in _DEFAULT_SUBREDDITS
        ]

        async with httpx.AsyncClient(headers=headers, timeout=25) as client:
            for path, params in searches:
                if len(results) >= max_results:
                    break

                payload = await self._get(client, path, params)
                if not isinstance(payload, dict):
                    continue

                for child in payload.get("data", {}).get("children", []):
                    if len(results) >= max_results:
                        break

                    data = child.get("data", {})
                    post_id = data.get("id")
                    if not post_id or post_id in seen_ids:
                        continue
                    seen_ids.add(post_id)

                    results.append(self._post_item(data))

                    # Comments are where the real opinions live.
                    if len(results) < max_results:
                        results.extend(await self._fetch_comments(client, data))

                await asyncio.sleep(self.request_delay)

        self.logger.info("reddit_results_collected", count=len(results))
        return results[:max_results]

    # ------------------------------------------------------------------ #
    #  Main implementation
    # ------------------------------------------------------------------ #

    def _mock(self, query: str, max_results: int, reason: str) -> list[dict[str, Any]]:
        """Return labelled synthetic data, or fail loudly if mocks are disabled."""
        if not settings.ALLOW_MOCK_DATA:
            raise RuntimeError(
                f"Reddit scraping unavailable ({reason}) and ALLOW_MOCK_DATA is False"
            )
        self.logger.info("reddit_fallback_mock", reason=reason)
        count = random.randint(30, max(30, min(50, max_results)))
        return _generate_mock_data(query, count)

    async def _scrape_impl(
        self,
        query: str,
        max_results: int,
    ) -> list[dict[str, Any]]:
        if settings.DEBUG:
            return self._mock(query, max_results, "DEBUG=True")

        if not self._has_credentials:
            return self._mock(query, max_results, "no_credentials")

        token = await self._get_access_token()
        if token is None:
            return self._mock(query, max_results, "auth_failed")

        results = await self._search_reddit(token, query, max_results)
        if not results:
            return self._mock(query, max_results, "no_results")

        return results
