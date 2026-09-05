"""Tests for dashboard aggregations.

These endpoints previously returned hardcoded fixtures (Mon-Sun sentiment
counts, Apple/Samsung competitors). They now aggregate real rows, so the
tests assert the data actually comes from the database.
"""

import uuid

import pytest

from app.models.analytics import Analytics
from app.models.scraped_data import ScrapedData
from app.models.user import User
from app.models.workflow import Workflow
from app.services import dashboard_service
from app.services.dashboard_service import _looks_like_company_name
from tests.conftest import TestSessionLocal


async def _seed(db, *, keywords=None, competitors=None, scraped=None):
    """Create a user with one workflow plus optional analytics and rows."""
    user_id, workflow_id = uuid.uuid4(), uuid.uuid4()

    db.add(User(id=user_id, email=f"{user_id}@example.com",
                hashed_password="x", full_name="T", role="user"))
    db.add(Workflow(id=workflow_id, user_id=user_id, query="test",
                    sources=["reddit"], status="completed"))
    await db.flush()

    if keywords is not None:
        db.add(Analytics(workflow_id=workflow_id, metric_type="keyword_frequency",
                         metric_data={"keywords": keywords}))
    if competitors is not None:
        db.add(Analytics(workflow_id=workflow_id, metric_type="competitor_score",
                         metric_data=competitors))
    for row in (scraped or []):
        db.add(ScrapedData(workflow_id=workflow_id, source="reddit", **row))

    await db.commit()
    return user_id


class TestCompanyNameFilter:
    @pytest.mark.parametrize("value", ["Apple", "Bose", "Sony WH-1000XM4"])
    def test_accepts_real_names(self, value):
        assert _looks_like_company_name(value)

    @pytest.mark.parametrize("value", [
        "Specific competitor names are not mentioned in the provided data.",
        "No competitors found.",
        "", "A", None, 123, ["Apple"],
    ])
    def test_rejects_prose_and_junk(self, value):
        assert not _looks_like_company_name(value)


@pytest.mark.asyncio
class TestKeywordAggregation:
    async def test_keywords_come_from_analytics(self):
        async with TestSessionLocal() as db:
            user_id = await _seed(db, keywords=[
                {"keyword": "battery life", "frequency": 10, "sentiment": -0.5},
                {"keyword": "sound quality", "frequency": 5, "sentiment": 0.8},
            ])
            result = await dashboard_service.get_keyword_data(db, user_id)

        assert [k["keyword"] for k in result] == ["battery life", "sound quality"]
        assert result[0]["frequency"] == 10

    async def test_no_data_returns_empty_not_fixtures(self):
        async with TestSessionLocal() as db:
            user_id = await _seed(db)
            result = await dashboard_service.get_keyword_data(db, user_id)

        assert result == []

    async def test_users_do_not_see_each_others_keywords(self):
        async with TestSessionLocal() as db:
            mine = await _seed(db, keywords=[
                {"keyword": "mine", "frequency": 1, "sentiment": 0.0}])
            await _seed(db, keywords=[
                {"keyword": "theirs", "frequency": 99, "sentiment": 0.0}])

            result = await dashboard_service.get_keyword_data(db, mine)

        assert [k["keyword"] for k in result] == ["mine"]


@pytest.mark.asyncio
class TestTrendAggregation:
    async def test_trend_points_are_real_dates(self):
        """A span beyond 60 days is binned by calendar month."""
        async with TestSessionLocal() as db:
            user_id = await _seed(db, scraped=[
                {"content": "great", "metadata_": {"date": "2024-01-10"},
                 "sentiment_label": "POSITIVE", "sentiment_score": 0.6},
                {"content": "bad", "metadata_": {"date": "2024-02-10"},
                 "sentiment_label": "NEGATIVE", "sentiment_score": -0.6},
                {"content": "fine", "metadata_": {"date": "2024-04-10"},
                 "sentiment_label": "NEUTRAL", "sentiment_score": 0.0},
            ])
            result = await dashboard_service.get_trend_data(db, user_id)

        dates = [p["date"] for p in result]
        assert dates == ["2024-01", "2024-02", "2024-04"]
        # The old stub returned weekday names.
        assert not any(d in ("Mon", "Tue", "Wed") for d in dates)

    async def test_short_span_is_binned_weekly(self):
        """Within 60 days, monthly bins would be too coarse to show anything."""
        async with TestSessionLocal() as db:
            user_id = await _seed(db, scraped=[
                {"content": "great", "metadata_": {"date": "2024-01-08"},
                 "sentiment_label": "POSITIVE", "sentiment_score": 0.6},
                {"content": "bad", "metadata_": {"date": "2024-01-22"},
                 "sentiment_label": "NEGATIVE", "sentiment_score": -0.6},
            ])
            result = await dashboard_service.get_trend_data(db, user_id)

        assert all(p["date"].startswith("2024-W") for p in result)

    async def test_no_data_returns_empty(self):
        async with TestSessionLocal() as db:
            user_id = await _seed(db)
            assert await dashboard_service.get_trend_data(db, user_id) == []


@pytest.mark.asyncio
class TestCompetitorAggregation:
    async def test_competitors_scored_from_real_mentions(self):
        async with TestSessionLocal() as db:
            user_id = await _seed(
                db,
                competitors={"top_competitors": ["Bose", "Apple"],
                             "strengths": ["ANC"], "weaknesses": ["Price"]},
                scraped=[
                    {"content": "Bose is more comfortable and sounds great",
                     "metadata_": {}, "sentiment_label": "POSITIVE",
                     "sentiment_score": 0.7},
                    {"content": "Bose broke after a month, terrible",
                     "metadata_": {}, "sentiment_label": "NEGATIVE",
                     "sentiment_score": -0.6},
                ],
            )
            result = await dashboard_service.get_competitor_data(db, user_id)

        by_name = {c["name"]: c for c in result}
        assert by_name["Bose"]["mention_count"] == 2
        # Mean of +0.7 and -0.6.
        assert by_name["Bose"]["sentiment_score"] == pytest.approx(0.05, abs=0.01)
        assert by_name["Apple"]["mention_count"] == 0

    async def test_prose_is_not_rendered_as_a_competitor(self):
        async with TestSessionLocal() as db:
            user_id = await _seed(db, competitors={
                "top_competitors": [
                    "Specific competitor names are not mentioned in the data.",
                    "Bose",
                ],
                "strengths": [], "weaknesses": [],
            })
            result = await dashboard_service.get_competitor_data(db, user_id)

        assert [c["name"] for c in result] == ["Bose"]

    async def test_no_analytics_returns_empty_not_apple_samsung(self):
        async with TestSessionLocal() as db:
            user_id = await _seed(db)
            result = await dashboard_service.get_competitor_data(db, user_id)

        assert result == []
