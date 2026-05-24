from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func
from app.models.workflow import Workflow
from app.models.report import Report
from app.models.scraped_data import ScrapedData
from app.models.analytics import Analytics
from app.models.agent_log import AgentLog
from app.models.scheduled_task import ScheduledTask

async def get_overview_metrics(db: AsyncSession, user_id) -> dict:
    wf_count = await db.execute(select(func.count(Workflow.id)).where(Workflow.user_id == user_id))
    comp_wf_count = await db.execute(select(func.count(Workflow.id)).where(Workflow.user_id == user_id, Workflow.status == 'completed'))
    rep_count = await db.execute(select(func.count(Report.id)).where(Report.user_id == user_id))
    
    # Needs a join if we want to filter by user_id for scraped_data
    data_count = await db.execute(
        select(func.count(ScrapedData.id))
        .join(Workflow, ScrapedData.workflow_id == Workflow.id)
        .where(Workflow.user_id == user_id)
    )
    
    sched_count = await db.execute(select(func.count(ScheduledTask.id)).where(ScheduledTask.user_id == user_id, ScheduledTask.is_active == True))

    avg_sent = await db.execute(
        select(func.avg(ScrapedData.sentiment_score))
        .join(Workflow, ScrapedData.workflow_id == Workflow.id)
        .where(Workflow.user_id == user_id)
    )
    
    return {
        "total_workflows": wf_count.scalar() or 0,
        "completed_workflows": comp_wf_count.scalar() or 0,
        "total_reports": rep_count.scalar() or 0,
        "avg_sentiment_score": float(avg_sent.scalar() or 0.5),
        "total_data_points": data_count.scalar() or 0,
        "active_schedules": sched_count.scalar() or 0
    }

async def get_sentiment_distribution(db: AsyncSession, user_id) -> list[dict]:
    # Group by label
    result = await db.execute(
        select(ScrapedData.sentiment_label, func.count(ScrapedData.id))
        .join(Workflow, ScrapedData.workflow_id == Workflow.id)
        .where(Workflow.user_id == user_id, ScrapedData.sentiment_label.is_not(None))
        .group_by(ScrapedData.sentiment_label)
    )
    
    counts = {row[0]: row[1] for row in result.all()}
    total = sum(counts.values())
    
    if total == 0:
        return [
            {"label": "POSITIVE", "count": 0, "percentage": 0.0},
            {"label": "NEGATIVE", "count": 0, "percentage": 0.0},
            {"label": "NEUTRAL", "count": 0, "percentage": 0.0}
        ]
        
    return [
        {"label": k, "count": v, "percentage": (v/total)*100}
        for k, v in counts.items()
    ]

async def get_recent_activity(db: AsyncSession, user_id) -> list[dict]:
    result = await db.execute(
        select(Workflow)
        .where(Workflow.user_id == user_id)
        .order_by(Workflow.created_at.desc())
        .limit(5)
    )
    return [
        {
            "type": "workflow",
            "id": str(w.id),
            "status": w.status,
            "query": w.query,
            "date": w.created_at.isoformat()
        }
        for w in result.scalars().all()
    ]

# Mock implementation for these complex aggregations for now
async def get_trend_data(db: AsyncSession, user_id) -> list[dict]:
    return [
        {"date": "Mon", "positive": 4000, "negative": 2400, "neutral": 2400},
        {"date": "Tue", "positive": 3000, "negative": 1398, "neutral": 2210},
        {"date": "Wed", "positive": 2000, "negative": 9800, "neutral": 2290},
        {"date": "Thu", "positive": 2780, "negative": 3908, "neutral": 2000},
        {"date": "Fri", "positive": 1890, "negative": 4800, "neutral": 2181},
        {"date": "Sat", "positive": 2390, "negative": 3800, "neutral": 2500},
        {"date": "Sun", "positive": 3490, "negative": 4300, "neutral": 2100},
    ]

async def get_keyword_data(db: AsyncSession, user_id) -> list[dict]:
    return [
        {"keyword": "battery life", "frequency": 120, "sentiment": 0.2},
        {"keyword": "camera quality", "frequency": 95, "sentiment": 0.8},
        {"keyword": "screen size", "frequency": 80, "sentiment": 0.6},
        {"keyword": "price", "frequency": 150, "sentiment": 0.3},
        {"keyword": "software update", "frequency": 60, "sentiment": 0.4},
    ]

async def get_competitor_data(db: AsyncSession, user_id) -> list[dict]:
    return [
        {
            "name": "Apple",
            "sentiment_score": 0.75,
            "mention_count": 500,
            "strengths": ["Ecosystem", "Build Quality"],
            "weaknesses": ["Price", "Customization"]
        },
        {
            "name": "Samsung",
            "sentiment_score": 0.68,
            "mention_count": 450,
            "strengths": ["Display", "Features"],
            "weaknesses": ["Bloatware", "Updates"]
        }
    ]
