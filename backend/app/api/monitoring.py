"""Monitoring API routes - health check, system stats, agent logs."""

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import text, select, desc, func
import psutil
import os

from app.database import get_db
from app.core.security import require_role
from app.models.agent_log import AgentLog

router = APIRouter()

@router.get("/health")
async def health_check(db: AsyncSession = Depends(get_db)):
    try:
        await db.execute(text("SELECT 1"))
        db_status = "ok"
    except Exception:
        db_status = "error"
        
    return {
        "status": "ok" if db_status == "ok" else "degraded",
        "database": db_status
    }

@router.get("/system", dependencies=[Depends(require_role("admin"))])
async def get_system_stats():
    return {
        "cpu_percent": psutil.cpu_percent(),
        "memory_percent": psutil.virtual_memory().percent,
        "pid": os.getpid()
    }
    
@router.get("/agents", dependencies=[Depends(require_role("admin"))])
async def get_agent_logs(
    db: AsyncSession = Depends(get_db),
    limit: int = Query(50, ge=1, le=500),
):
    """Recent agent executions, newest first, with per-agent timing."""
    recent = await db.execute(
        select(AgentLog).order_by(desc(AgentLog.started_at)).limit(limit)
    )
    logs = list(recent.scalars().all())

    # Per-agent aggregates make slow nodes obvious at a glance.
    summary_rows = await db.execute(
        select(
            AgentLog.agent_name,
            func.count(AgentLog.id),
            func.avg(AgentLog.execution_time_ms),
        ).group_by(AgentLog.agent_name)
    )

    return {
        "summary": [
            {
                "agent_name": name,
                "runs": runs,
                "avg_execution_time_ms": round(float(avg_ms), 2) if avg_ms else 0.0,
            }
            for name, runs, avg_ms in summary_rows.all()
        ],
        "recent": [
            {
                "id": str(log.id),
                "workflow_id": str(log.workflow_id) if log.workflow_id else None,
                "agent_name": log.agent_name,
                "status": log.status,
                "execution_time_ms": log.execution_time_ms,
                "started_at": log.started_at.isoformat() if log.started_at else None,
            }
            for log in logs
        ],
    }
