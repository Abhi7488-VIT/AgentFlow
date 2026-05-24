"""
Amazon product-review scraper with realistic demo/mock mode.
"""

from __future__ import annotations

import asyncio
import random
import re
from datetime import datetime, timedelta
from typing import Any
from urllib.parse import quote_plus

import structlog

from app.scrapers.base import BaseScraper

log: structlog.stdlib.BoundLogger = structlog.get_logger(__name__)

# ---------------------------------------------------------------------------
#  Rotating user-agent pool
# ---------------------------------------------------------------------------
_USER_AGENTS: list[str] = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_5) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.4 Safari/605.1.15",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:126.0) Gecko/20100101 Firefox/126.0",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 14.5; rv:126.0) Gecko/20100101 Firefox/126.0",
    "Mozilla/5.0 (X11; Ubuntu; Linux x86_64; rv:126.0) Gecko/20100101 Firefox/126.0",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36 Edg/125.0.0.0",
]


def _random_ua() -> str:
    return random.choice(_USER_AGENTS)


# ---------------------------------------------------------------------------
#  Mock data generator
# ---------------------------------------------------------------------------

_POSITIVE_TEMPLATES: list[str] = [
    "Absolutely love this {product}! The build quality is exceptional and it exceeded my expectations.",
    "Best {product} I've ever purchased. Works exactly as described and the performance is outstanding.",
    "Five stars all the way. The {product} arrived quickly and the quality is top-notch. Highly recommend!",
    "I was skeptical at first, but this {product} is genuinely impressive. Great value for money.",
    "After using the {product} for two months, I can say it's a game changer. Very satisfied with my purchase.",
    "The {product} is exactly what I needed. Setup was easy and it works flawlessly every day.",
    "Outstanding quality! The {product} looks and feels premium. Worth every penny.",
    "I've recommended this {product} to everyone I know. It's reliable, well-designed, and performs beautifully.",
    "This {product} surpassed all my expectations. The attention to detail is remarkable.",
    "Incredible {product}! Fast shipping, perfect packaging, and the product itself is amazing.",
    "Can't believe how good this {product} is at this price point. It rivals products twice the cost.",
    "My third time buying this {product} as gifts. Everyone loves it. Consistent quality every time.",
]

_NEGATIVE_TEMPLATES: list[str] = [
    "Disappointed with this {product}. It stopped working after just two weeks of normal use.",
    "The {product} looks nothing like the pictures. Cheap materials and poor build quality overall.",
    "Returned the {product} immediately. It arrived damaged and customer support was unhelpful.",
    "Save your money. This {product} is overpriced for what you get. There are far better alternatives.",
    "The {product} constantly malfunctions. I've had to restart it multiple times a day. Very frustrating.",
    "Not worth the hype. The {product} has a noticeable design flaw that makes daily use annoying.",
    "After three months, the {product} started showing serious quality issues. Definitely won't buy again.",
    "Terrible {product}. The instructions were confusing and the product failed to deliver on its promises.",
    "I regret buying this {product}. It's loud, inefficient, and the software is buggy.",
    "Very underwhelming {product}. Expected much more based on the reviews and marketing.",
]

_NEUTRAL_TEMPLATES: list[str] = [
    "The {product} is okay for the price. Nothing extraordinary but gets the job done adequately.",
    "Average {product}. It has some nice features but also a few drawbacks that are worth mentioning.",
    "Decent {product} overall. Build quality is acceptable but could be better in some areas.",
    "The {product} works as advertised, but don't expect anything more. It's a budget option and it shows.",
    "Mixed feelings about this {product}. Some aspects are great while others need improvement.",
    "It's a functional {product}. Not the best I've used, but certainly not the worst either.",
    "The {product} met my basic needs. I wouldn't call it premium but it's serviceable for everyday use.",
    "Reasonable {product} for the money. Has some quirks but nothing that's a deal-breaker for me.",
]

_MOCK_TITLES: list[str] = [
    "Great purchase!", "Not what I expected", "Works perfectly", "Decent for the price",
    "Amazing quality!", "Would not recommend", "Solid product", "Good value",
    "Exceeded expectations", "Needs improvement", "Love it!", "Meh, it's okay",
    "Fantastic!", "Complete waste", "Pretty good overall", "Best purchase this year",
    "Disappointing quality", "Highly recommended", "Just average", "Outstanding product",
]

_MOCK_AUTHORS: list[str] = [
    "TechEnthusiast42", "BargainHunter", "QualityMatters", "EarlyAdopter99",
    "CasualUser", "ProReviewer", "GadgetGuru", "ValueSeeker",
    "PowerUser2024", "MinimalistBuyer", "DetailOriented", "SmartShopper",
    "TechSavvyMom", "DailyDriver", "FirstTimeBuyer", "LongTermUser",
    "CriticalEye", "HappyCustomer", "ReturnKing", "SilentMajority",
]


def _generate_mock_reviews(query: str, count: int) -> list[dict[str, Any]]:
    """Generate realistic mock Amazon reviews for the given product query."""
    reviews: list[dict[str, Any]] = []
    product_name = query.replace("+", " ").title()

    # Distribution: ~50% positive, ~25% negative, ~25% neutral
    sentiments: list[tuple[list[str], float, float]] = [
        (_POSITIVE_TEMPLATES, 4.0, 5.0),
        (_POSITIVE_TEMPLATES, 4.0, 5.0),
        (_NEGATIVE_TEMPLATES, 1.0, 2.0),
        (_NEUTRAL_TEMPLATES, 3.0, 3.5),
    ]

    for i in range(count):
        templates, rating_lo, rating_hi = sentiments[i % len(sentiments)]
        template = random.choice(templates)
        content = template.format(product=product_name)

        rating = round(random.uniform(rating_lo, rating_hi), 1)
        rating = min(5.0, max(1.0, rating))

        days_ago = random.randint(1, 365)
        review_date = (datetime.utcnow() - timedelta(days=days_ago)).strftime("%Y-%m-%d")
        verified = random.random() > 0.25  # 75% verified

        reviews.append(
            {
                "source": "amazon",
                "content": content,
                "metadata": {
                    "rating": rating,
                    "title": random.choice(_MOCK_TITLES),
                    "date": review_date,
                    "product_name": product_name,
                    "verified": verified,
                    "author": random.choice(_MOCK_AUTHORS),
                },
            }
        )

    return reviews


# ---------------------------------------------------------------------------
#  Scraper implementation
# ---------------------------------------------------------------------------

class AmazonScraper(BaseScraper):
    """Scrapes Amazon product search results and reviews.

    Falls back to realistic mock data when ``settings.DEBUG`` is ``True``
    or when live scraping encounters errors (anti-bot, network issues, etc.).
    """

    SEARCH_URL = "https://www.amazon.com/s?k={query}"

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(request_delay=2.0, **kwargs)
        self.logger = log.bind(scraper="AmazonScraper")

    # ------------------------------------------------------------------ #
    #  Live scraping helpers
    # ------------------------------------------------------------------ #

    @staticmethod
    def _build_headers() -> dict[str, str]:
        return {
            "User-Agent": _random_ua(),
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.9",
            "Accept-Encoding": "gzip, deflate, br",
            "DNT": "1",
            "Connection": "keep-alive",
            "Upgrade-Insecure-Requests": "1",
        }

    async def _fetch_page(self, url: str) -> str | None:
        """Fetch a page via httpx, returning HTML or None on failure."""
        try:
            import httpx

            async with httpx.AsyncClient(
                headers=self._build_headers(),
                follow_redirects=True,
                timeout=20.0,
            ) as client:
                await asyncio.sleep(random.uniform(1.0, 3.0))  # human-like delay
                resp = await client.get(url)
                if resp.status_code == 200:
                    return resp.text
                self.logger.warning(
                    "amazon_http_error",
                    status=resp.status_code,
                    url=url,
                )
        except Exception as exc:  # noqa: BLE001
            self.logger.warning("amazon_fetch_error", error=str(exc), url=url)
        return None

    def _parse_search_results(self, html: str) -> list[dict[str, str]]:
        """Extract product ASINs and titles from search-results HTML."""
        try:
            from bs4 import BeautifulSoup
        except ImportError:
            self.logger.warning("beautifulsoup4_not_installed")
            return []

        soup = BeautifulSoup(html, "html.parser")
        products: list[dict[str, str]] = []

        for item in soup.select('[data-asin]'):
            asin = item.get("data-asin", "")
            if not asin or len(asin) < 5:
                continue
            title_tag = item.select_one("h2 a span") or item.select_one("h2 span")
            title = title_tag.get_text(strip=True) if title_tag else "Unknown Product"
            products.append({"asin": asin, "title": title})

        return products

    def _parse_reviews(
        self, html: str, product_name: str
    ) -> list[dict[str, Any]]:
        """Extract reviews from a product-review page."""
        try:
            from bs4 import BeautifulSoup
        except ImportError:
            return []

        soup = BeautifulSoup(html, "html.parser")
        reviews: list[dict[str, Any]] = []

        for review_el in soup.select('[data-hook="review"]'):
            # Title
            title_tag = review_el.select_one('[data-hook="review-title"] span')
            title = title_tag.get_text(strip=True) if title_tag else ""

            # Body
            body_tag = review_el.select_one('[data-hook="review-body"] span')
            body = body_tag.get_text(strip=True) if body_tag else ""
            if not body:
                continue

            # Rating
            rating_tag = review_el.select_one('[data-hook="review-star-rating"] span')
            rating = 0.0
            if rating_tag:
                match = re.search(r"([\d.]+)", rating_tag.get_text())
                if match:
                    rating = float(match.group(1))

            # Date
            date_tag = review_el.select_one('[data-hook="review-date"]')
            date_text = date_tag.get_text(strip=True) if date_tag else ""

            # Verified
            verified_tag = review_el.select_one('[data-hook="avp-badge"]')
            verified = verified_tag is not None

            reviews.append(
                {
                    "source": "amazon",
                    "content": body,
                    "metadata": {
                        "rating": rating,
                        "title": title,
                        "date": date_text,
                        "product_name": product_name,
                        "verified": verified,
                    },
                }
            )

        return reviews

    # ------------------------------------------------------------------ #
    #  Main implementation
    # ------------------------------------------------------------------ #

    async def _scrape_impl(
        self,
        query: str,
        max_results: int,
    ) -> list[dict[str, Any]]:
        # Check DEBUG flag
        try:
            from app.config import settings

            if getattr(settings, "DEBUG", False):
                self.logger.info("amazon_demo_mode", reason="DEBUG=True")
                count = random.randint(30, min(50, max_results))
                return _generate_mock_reviews(query, count)
        except ImportError:
            pass

        # Attempt live scraping
        all_reviews: list[dict[str, Any]] = []
        encoded_query = quote_plus(query)
        search_url = self.SEARCH_URL.format(query=encoded_query)

        search_html = await self._fetch_page(search_url)
        if not search_html:
            self.logger.info("amazon_fallback_mock", reason="search_page_failed")
            count = random.randint(30, min(50, max_results))
            return _generate_mock_reviews(query, count)

        products = self._parse_search_results(search_html)
        if not products:
            self.logger.info("amazon_fallback_mock", reason="no_products_found")
            count = random.randint(30, min(50, max_results))
            return _generate_mock_reviews(query, count)

        self.logger.info("amazon_products_found", count=len(products))

        for product in products[:5]:  # limit to first 5 products
            review_url = (
                f"https://www.amazon.com/product-reviews/{product['asin']}"
                f"?sortBy=recent&pageNumber=1"
            )
            review_html = await self._fetch_page(review_url)
            if review_html:
                parsed = self._parse_reviews(review_html, product["title"])
                all_reviews.extend(parsed)
                self.logger.debug(
                    "amazon_reviews_parsed",
                    asin=product["asin"],
                    count=len(parsed),
                )
            if len(all_reviews) >= max_results:
                break

        if not all_reviews:
            self.logger.info("amazon_fallback_mock", reason="no_reviews_parsed")
            count = random.randint(30, min(50, max_results))
            return _generate_mock_reviews(query, count)

        return all_reviews[:max_results]
