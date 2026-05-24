from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.core.security import get_current_user
from app.models.user import User
from app.schemas.dashboard import OverviewMetrics, SentimentData, TrendPoint, KeywordData, CompetitorData
from app.services import dashboard_service

router = APIRouter()

@router.get("/overview", response_model=OverviewMetrics)
async def get_overview(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    return await dashboard_service.get_overview_metrics(db, current_user.id)

@router.get("/sentiment", response_model=list[SentimentData])
async def get_sentiment(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    return await dashboard_service.get_sentiment_distribution(db, current_user.id)

@router.get("/trends", response_model=list[TrendPoint])
async def get_trends(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    return await dashboard_service.get_trend_data(db, current_user.id)

@router.get("/keywords", response_model=list[KeywordData])
async def get_keywords(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    return await dashboard_service.get_keyword_data(db, current_user.id)

@router.get("/competitors", response_model=list[CompetitorData])
async def get_competitors(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    return await dashboard_service.get_competitor_data(db, current_user.id)

@router.get("/recent-activity")
async def get_recent_activity(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    return await dashboard_service.get_recent_activity(db, current_user.id)
