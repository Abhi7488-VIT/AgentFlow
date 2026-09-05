"""
Amazon product-review scraper.

Amazon publishes no public product API and actively blocks automation, so
this module is a real scraper: it warms a browser-like session, rotates
fingerprints, walks several marketplaces, and detects block pages rather
than parsing them as results.

Reviews come from the product detail page - Amazon's dedicated
``/product-reviews/`` endpoint now redirects anonymous visitors to a
sign-in wall, while the detail page still embeds a dozen or so reviews.

Synthetic data is the last resort and is always flagged ``is_mock``.
"""

from __future__ import annotations

import asyncio
import random
import re
from datetime import datetime, timedelta, timezone
from typing import Any
from urllib.parse import quote_plus

import httpx
import structlog
from bs4 import BeautifulSoup

from app.config import settings
from app.scrapers.base import BaseScraper
from app.scrapers.web import browser_headers, new_client, parse_count

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
        review_date = (datetime.now(timezone.utc) - timedelta(days=days_ago)).strftime("%Y-%m-%d")
        verified = random.random() > 0.25  # 75% verified

        reviews.append(
            {
                "source": "amazon",
                "content": content,
                "metadata": {
                    "is_mock": True,
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
#  Page parsing helpers
# ---------------------------------------------------------------------------

# Phrases Amazon serves instead of content when it decides you are a bot.
_BLOCK_MARKERS: tuple[str, ...] = (
    "sorry, something went wrong",
    "enter the characters you see",
    "automated access",
    "api-services-support@amazon.com",
    "robot check",
    "amazon sign-in",
)

_MONTHS: dict[str, int] = {
    "january": 1, "february": 2, "march": 3, "april": 4, "may": 5, "june": 6,
    "july": 7, "august": 8, "september": 9, "october": 10, "november": 11,
    "december": 12,
}


def _is_blocked(html: str) -> str | None:
    """Return the marker that identifies a block page, if any."""
    lowered = html.lower()
    for marker in _BLOCK_MARKERS:
        if marker in lowered:
            return marker
    return None


def _parse_review_date(text: str) -> str:
    """Parse 'Reviewed in India on 26 August 2025' into '2025-08-26'.

    Amazon localises this string per marketplace, so the country is
    skipped and only the trailing date is read.
    """
    if not text:
        return datetime.now(timezone.utc).strftime("%Y-%m-%d")

    match = re.search(r"(\d{1,2})\s+([A-Za-z]+)\s+(\d{4})", text)
    if match:
        day, month_name, year = match.groups()
        month = _MONTHS.get(month_name.lower())
        if month:
            try:
                return datetime(int(year), month, int(day)).strftime("%Y-%m-%d")
            except ValueError:
                pass

    # US format: "Reviewed in the United States on August 26, 2025"
    match = re.search(r"([A-Za-z]+)\s+(\d{1,2}),\s*(\d{4})", text)
    if match:
        month_name, day, year = match.groups()
        month = _MONTHS.get(month_name.lower())
        if month:
            try:
                return datetime(int(year), month, int(day)).strftime("%Y-%m-%d")
            except ValueError:
                pass

    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def _parse_rating(text: str) -> float | None:
    """'4.0 out of 5 stars' -> 4.0"""
    if not text:
        return None
    match = re.search(r"([\d.]+)\s*out of\s*5", text)
    if not match:
        return None
    try:
        return max(1.0, min(5.0, float(match.group(1))))
    except ValueError:
        return None


# ---------------------------------------------------------------------------
#  Scraper implementation
# ---------------------------------------------------------------------------

class AmazonScraper(BaseScraper):
    """Scrapes Amazon product search results and customer reviews.

    Amazon has no public product API and actively blocks automation, so
    this is a genuine scraper and is written accordingly:

    * a session is warmed on the marketplace home page first, so search
      requests carry the cookies a real browser would have;
    * headers rotate across a pool of real browser fingerprints, and a
      ``Referer`` is set so navigation looks like it came from the site;
    * several marketplaces are tried in turn, because a block is usually
      per-domain rather than global;
    * block pages are detected explicitly instead of being parsed as if
      they were results.

    Reviews are read from the **product detail page**. Amazon's dedicated
    ``/product-reviews/`` endpoint now redirects to a sign-in wall, while
    the detail page still embeds a dozen or so reviews for anonymous
    visitors.
    """

    # Tried in order. A block tends to be per-marketplace.
    MARKETPLACES: tuple[str, ...] = ("amazon.com", "amazon.in", "amazon.co.uk")

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(request_delay=2.0, **kwargs)
        self.logger = log.bind(scraper="AmazonScraper")

    # ------------------------------------------------------------------ #
    #  Fetching
    # ------------------------------------------------------------------ #

    async def _get(
        self,
        client: httpx.AsyncClient,
        url: str,
        params: dict[str, Any] | None = None,
        referer: str | None = None,
    ) -> str | None:
        """Fetch a page, returning HTML only if it is not a block page."""
        try:
            response = await client.get(
                url, params=params, headers=browser_headers(referer=referer)
            )
        except Exception as exc:  # noqa: BLE001
            self.logger.warning("amazon_fetch_error", url=url, error=str(exc)[:120])
            return None

        if response.status_code != 200:
            self.logger.warning(
                "amazon_http_error", url=url, status=response.status_code
            )
            return None

        marker = _is_blocked(response.text)
        if marker:
            self.logger.warning("amazon_blocked", url=url, marker=marker)
            return None

        return response.text

    # ------------------------------------------------------------------ #
    #  Parsing
    # ------------------------------------------------------------------ #

    def _parse_search_results(self, html: str, limit: int = 5) -> list[dict[str, str]]:
        """Extract ASINs and titles from a search results page."""
        soup = BeautifulSoup(html, "lxml")
        products: list[dict[str, str]] = []
        seen: set[str] = set()

        for card in soup.select("div[data-asin]"):
            asin = (card.get("data-asin") or "").strip()
            if not asin or asin in seen:
                continue

            title_el = (
                card.select_one("h2 a span")
                or card.select_one("a.a-link-normal span")
                or card.select_one("h2")
            )
            title = title_el.get_text(" ", strip=True) if title_el else ""
            if not title:
                continue

            seen.add(asin)
            products.append({"asin": asin, "title": title})

            if len(products) >= limit:
                break

        return products

    def _parse_reviews(
        self,
        html: str,
        product_title: str,
        marketplace: str,
    ) -> list[dict[str, Any]]:
        """Extract reviews embedded in a product detail page.

        Amazon renders each review twice - once inline and once inside a
        modal popover - so reviews are de-duplicated on their text.
        """
        soup = BeautifulSoup(html, "lxml")
        reviews: list[dict[str, Any]] = []
        seen_bodies: set[str] = set()

        for block in soup.select("div[data-hook='review']"):
            body_el = (
                block.select_one("[data-hook='reviewRichContentContainer']")
                or block.select_one("[data-hook='reviewText']")
                or block.select_one("[data-hook='review-body']")
            )
            if body_el is None:
                continue

            content = body_el.get_text(" ", strip=True)
            # Amazon injects this when a review is truncated in the DOM.
            content = re.sub(
                r"(Brief content visible.*?full content\.?|Read more|Read less)",
                "", content, flags=re.IGNORECASE,
            ).strip()

            if len(content) < 15:
                continue

            fingerprint = content[:120].lower()
            if fingerprint in seen_bodies:
                continue
            seen_bodies.add(fingerprint)

            title_el = (
                block.select_one("[data-hook='reviewTitle']")
                or block.select_one("[data-hook='review-title']")
            )
            rating_el = block.select_one("[data-hook='review-star-rating']") \
                or block.select_one("[data-hook='cmps-review-star-rating']")
            date_el = block.select_one("[data-hook='review-date']")
            author_el = block.select_one("span.a-profile-name")
            helpful_el = block.select_one("[data-hook='helpful-vote-statement']")

            review_title = title_el.get_text(" ", strip=True) if title_el else ""
            # The title element also carries the rating text; strip it.
            review_title = re.sub(r"^[\d.]+ out of 5 stars\s*", "", review_title).strip()

            reviews.append({
                "source": "amazon",
                "content": content,
                "metadata": {
                    "is_mock": False,
                    "rating": _parse_rating(
                        rating_el.get_text(" ", strip=True) if rating_el else ""
                    ),
                    "title": review_title,
                    "date": _parse_review_date(
                        date_el.get_text(" ", strip=True) if date_el else ""
                    ),
                    "product_name": product_title,
                    "verified": block.select_one("[data-hook='avp-badge']") is not None,
                    "author": author_el.get_text(strip=True) if author_el else "Anonymous",
                    "helpful_votes": parse_count(
                        re.sub(r"[^\d,]", "", helpful_el.get_text())
                        if helpful_el else ""
                    ),
                    "marketplace": marketplace,
                    "collection_method": "detail_page_scrape",
                },
            })

        return reviews

    # ------------------------------------------------------------------ #
    #  Live collection
    # ------------------------------------------------------------------ #

    async def _collect_from(
        self,
        marketplace: str,
        query: str,
        max_results: int,
    ) -> list[dict[str, Any]]:
        """Search one marketplace and gather reviews from its top products."""
        base = f"https://www.{marketplace}"

        async with new_client() as client:
            # Warm the session: search requests from a cookie-less client are
            # the first thing Amazon's bot detection rejects.
            await self._get(client, f"{base}/")
            await asyncio.sleep(self.request_delay)

            search_html = await self._get(
                client, f"{base}/s", params={"k": query}, referer=f"{base}/"
            )
            if not search_html:
                return []

            products = self._parse_search_results(search_html)
            if not products:
                self.logger.warning("amazon_no_products", marketplace=marketplace)
                return []

            self.logger.info(
                "amazon_products_found",
                marketplace=marketplace, count=len(products),
            )

            collected: list[dict[str, Any]] = []
            for product in products:
                if len(collected) >= max_results:
                    break

                await asyncio.sleep(self.request_delay)
                detail_html = await self._get(
                    client,
                    f"{base}/dp/{product['asin']}",
                    referer=f"{base}/s?k={quote_plus(query)}",
                )
                if not detail_html:
                    continue

                reviews = self._parse_reviews(
                    detail_html, product["title"], marketplace
                )
                collected.extend(reviews)
                self.logger.info(
                    "amazon_reviews_parsed",
                    asin=product["asin"], count=len(reviews),
                )

            return collected[:max_results]

    # ------------------------------------------------------------------ #
    #  Main implementation
    # ------------------------------------------------------------------ #

    def _mock(self, query: str, max_results: int, reason: str) -> list[dict[str, Any]]:
        """Labelled synthetic data, or a hard failure if mocks are disabled."""
        if not settings.ALLOW_MOCK_DATA:
            raise RuntimeError(
                f"Amazon scraping unavailable ({reason}) and ALLOW_MOCK_DATA is False"
            )
        self.logger.info("amazon_fallback_mock", reason=reason)
        count = random.randint(30, max(30, min(50, max_results)))
        return _generate_mock_reviews(query, count)

    async def _scrape_impl(
        self,
        query: str,
        max_results: int,
    ) -> list[dict[str, Any]]:
        if settings.DEBUG:
            return self._mock(query, max_results, "DEBUG=True")

        for marketplace in self.MARKETPLACES:
            try:
                results = await self._collect_from(marketplace, query, max_results)
            except Exception as exc:  # noqa: BLE001
                self.logger.warning(
                    "amazon_marketplace_error",
                    marketplace=marketplace, error=str(exc)[:140],
                )
                continue

            if results:
                self.logger.info(
                    "amazon_results_collected",
                    marketplace=marketplace, count=len(results),
                )
                return results

            self.logger.info("amazon_marketplace_empty", marketplace=marketplace)

        return self._mock(query, max_results, "all_marketplaces_blocked_or_empty")
