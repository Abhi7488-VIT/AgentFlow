"""Dashboard service - aggregation queries for overview metrics."""

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, desc
from app.models.workflow import Workflow
from app.models.report import Report
from app.models.scraped_data import ScrapedData
from app.models.analytics import Analytics
from app.models.scheduled_task import ScheduledTask
from app.nlp.trends import TrendAnalyzer

# Cap how much raw data an aggregation pulls into memory.
_MAX_ROWS = 5000

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
        "avg_sentiment_score": round(float(avg_sent.scalar() or 0.0), 4),
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

async def _load_scraped(db: AsyncSession, user_id) -> list[ScrapedData]:
    """Most recent scraped rows belonging to this user, across all workflows."""
    result = await db.execute(
        select(ScrapedData)
        .join(Workflow, ScrapedData.workflow_id == Workflow.id)
        .where(Workflow.user_id == user_id)
        .order_by(desc(ScrapedData.created_at))
        .limit(_MAX_ROWS)
    )
    return list(result.scalars().all())


async def get_trend_data(db: AsyncSession, user_id) -> list[dict]:
    """Sentiment volume over time, binned by the same analyzer the agents use."""
    rows = await _load_scraped(db, user_id)
    if not rows:
        return []

    items = [
        {
            "content": row.content,
            "metadata": row.metadata_ or {},
            "sentiment_label": row.sentiment_label,
            "sentiment_score": row.sentiment_score,
        }
        for row in rows
    ]

    timeline = TrendAnalyzer().analyze_trends(items).get("timeline", [])
    return [
        {
            "date": point["date"],
            "positive": float(point["positive"]),
            "negative": float(point["negative"]),
            "neutral": float(point["neutral"]),
        }
        for point in timeline
    ]


async def get_keyword_data(db: AsyncSession, user_id) -> list[dict]:
    """Keywords the NLP agent extracted, merged across the user's workflows."""
    result = await db.execute(
        select(Analytics.metric_data)
        .join(Workflow, Analytics.workflow_id == Workflow.id)
        .where(Workflow.user_id == user_id, Analytics.metric_type == "keyword_frequency")
        .order_by(desc(Analytics.created_at))
        .limit(50)
    )

    merged: dict[str, dict] = {}
    for (metric_data,) in result.all():
        for entry in (metric_data or {}).get("keywords", []):
            term = entry.get("keyword")
            if not term:
                continue

            frequency = int(entry.get("frequency", 0) or 0)
            sentiment = float(entry.get("sentiment", 0.0) or 0.0)

            if term in merged:
                existing = merged[term]
                total = existing["frequency"] + frequency
                # Frequency-weighted mean so busier workflows count for more.
                if total:
                    existing["sentiment"] = round(
                        (existing["sentiment"] * existing["frequency"]
                         + sentiment * frequency) / total, 4
                    )
                existing["frequency"] = total
            else:
                merged[term] = {
                    "keyword": term,
                    "frequency": frequency,
                    "sentiment": round(sentiment, 4),
                }

    ranked = sorted(merged.values(), key=lambda k: k["frequency"], reverse=True)
    return ranked[:20]


def _looks_like_company_name(value) -> bool:
    """Reject LLM prose that landed in a field meant to hold a brand name."""
    if not isinstance(value, str):
        return False

    name = value.strip()
    if not (2 <= len(name) <= 40):
        return False
    if len(name.split()) > 4:
        return False
    # Sentences, not names.
    if any(ch in name for ch in ".:;?"):
        return False
    return True


async def get_competitor_data(db: AsyncSession, user_id) -> list[dict]:
    """Competitors named by the insight agent, scored against real mentions."""
    result = await db.execute(
        select(Analytics.metric_data)
        .join(Workflow, Analytics.workflow_id == Workflow.id)
        .where(Workflow.user_id == user_id, Analytics.metric_type == "competitor_score")
        .order_by(desc(Analytics.created_at))
        .limit(20)
    )

    names: list[str] = []
    strengths: list[str] = []
    weaknesses: list[str] = []

    for (metric_data,) in result.all():
        data = metric_data or {}
        for name in data.get("top_competitors", []) or []:
            # The LLM occasionally answers with a sentence instead of a name
            # ("No specific competitors were mentioned..."); those must not
            # be rendered as competitor cards.
            if _looks_like_company_name(name) and name.strip() not in names:
                names.append(name.strip())
        strengths.extend(s for s in (data.get("strengths") or []) if isinstance(s, str))
        weaknesses.extend(w for w in (data.get("weaknesses") or []) if isinstance(w, str))

    if not names:
        return []

    # Score each competitor by how the corpus actually talks about it.
    rows = await _load_scraped(db, user_id)
    competitors = []

    for name in names[:10]:
        needle = name.lower()
        mentions = [
            row for row in rows
            if row.content and needle in row.content.lower()
        ]
        scores = [
            row.sentiment_score for row in mentions
            if isinstance(row.sentiment_score, (int, float))
        ]

        competitors.append({
            "name": name,
            "sentiment_score": round(sum(scores) / len(scores), 4) if scores else 0.0,
            "mention_count": len(mentions),
            "strengths": strengths[:3],
            "weaknesses": weaknesses[:3],
        })

    competitors.sort(key=lambda c: c["mention_count"], reverse=True)
    return competitors
