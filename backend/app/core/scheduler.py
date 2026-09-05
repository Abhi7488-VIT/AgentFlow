"""Executes recurring analysis schedules.

``ScheduledTask`` rows could be created, listed and deactivated, but
nothing ever ran them - the dashboard counted "active schedules" that
would never fire. This is the executor.

Design note: rather than registering one APScheduler job per schedule,
a single interval job polls the database for anything due. The database
stays the single source of truth, so schedules survive a restart with no
re-registration, and a schedule created on one instance is honoured by
whichever instance polls next.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone

from sqlalchemy import select

from app.config import settings
from app.core.logging import get_logger
from app.models.scheduled_task import ScheduledTask
from app.models.workflow import Workflow

logger = get_logger(__name__)

# How often to look for due schedules.
POLL_SECONDS = 60

# Fixed intervals for the schedule_type shorthand.
_INTERVALS: dict[str, timedelta] = {
    "hourly": timedelta(hours=1),
    "daily": timedelta(days=1),
    "weekly": timedelta(weeks=1),
    "monthly": timedelta(days=30),
}

_scheduler = None


def compute_next_run(
    schedule_type: str,
    cron_expression: str | None = None,
    after: datetime | None = None,
) -> datetime | None:
    """When should this schedule next fire?

    A cron expression wins when present; otherwise the schedule_type
    shorthand is used. Returns None if neither can be interpreted, which
    the caller treats as "never run this".
    """
    reference = after or datetime.now(timezone.utc)
    if reference.tzinfo is None:
        reference = reference.replace(tzinfo=timezone.utc)

    if cron_expression:
        try:
            from apscheduler.triggers.cron import CronTrigger

            trigger = CronTrigger.from_crontab(cron_expression, timezone=timezone.utc)
            return trigger.get_next_fire_time(None, reference)
        except Exception as e:
            logger.warning(
                f"Invalid cron expression {cron_expression!r}, "
                f"falling back to schedule_type: {e}"
            )

    interval = _INTERVALS.get((schedule_type or "").lower())
    if interval is None:
        logger.warning(f"Unknown schedule_type {schedule_type!r}; schedule will not run")
        return None

    return reference + interval


async def _launch(schedule: ScheduledTask) -> None:
    """Create a workflow for one due schedule and start it."""
    # Imported here to avoid a circular import at module load.
    from app.database import async_session_factory
    from app.workers.tasks import execute_workflow_task

    sources = schedule.sources or ["amazon", "youtube", "reddit"]
    if isinstance(sources, dict):
        # Older rows stored {"amazon": true, ...}
        sources = [name for name, enabled in sources.items() if enabled]

    async with async_session_factory() as db:
        workflow = Workflow(
            user_id=schedule.user_id,
            query=schedule.query,
            sources=sources,
            status="pending",
        )
        db.add(workflow)
        await db.commit()
        await db.refresh(workflow)

    logger.info(
        f"Schedule '{schedule.name}' triggered workflow {workflow.id}"
    )

    # Fire and forget: the task updates the workflow row itself, and a
    # failure there must not stop the scheduler loop.
    asyncio.create_task(
        execute_workflow_task(
            workflow.id, schedule.query, sources, schedule.user_id
        )
    )


async def run_due_schedules() -> int:
    """Run every active schedule whose next_run_at has passed.

    Returns the number triggered. Never raises - a scheduler that dies on
    one bad row stops running everything else.
    """
    from app.database import async_session_factory

    triggered = 0
    now = datetime.now(timezone.utc)

    try:
        async with async_session_factory() as db:
            result = await db.execute(
                select(ScheduledTask).where(
                    ScheduledTask.is_active.is_(True),
                    ScheduledTask.next_run_at.is_not(None),
                    ScheduledTask.next_run_at <= now,
                )
            )
            due = list(result.scalars().all())

            for schedule in due:
                try:
                    await _launch(schedule)
                    triggered += 1
                except Exception as e:
                    logger.error(f"Schedule {schedule.id} failed to launch: {e}")

                # Advance the clock even on failure, so one broken schedule
                # cannot fire on every single poll.
                schedule.last_run_at = now
                schedule.next_run_at = compute_next_run(
                    schedule.schedule_type, schedule.cron_expression, after=now
                )

            if due:
                await db.commit()

    except Exception as e:
        logger.error(f"Scheduler poll failed: {e}")

    return triggered


def start_scheduler() -> None:
    """Start the poller. Safe to call when APScheduler is unavailable."""
    global _scheduler

    if not settings.SCHEDULER_ENABLED:
        logger.info("Scheduler disabled by configuration")
        return
    if _scheduler is not None:
        return

    try:
        from apscheduler.schedulers.asyncio import AsyncIOScheduler

        _scheduler = AsyncIOScheduler(timezone="UTC")
        _scheduler.add_job(
            run_due_schedules,
            "interval",
            seconds=POLL_SECONDS,
            id="run_due_schedules",
            # If the process was busy, run once on catch-up rather than
            # firing repeatedly for every missed interval.
            coalesce=True,
            max_instances=1,
        )
        _scheduler.start()
        logger.info(f"Scheduler started, polling every {POLL_SECONDS}s")
    except Exception as e:
        _scheduler = None
        logger.warning(f"Scheduler could not start, schedules will not run: {e}")


def stop_scheduler() -> None:
    """Stop the poller on application shutdown."""
    global _scheduler

    if _scheduler is None:
        return
    try:
        _scheduler.shutdown(wait=False)
        logger.info("Scheduler stopped")
    except Exception as e:
        logger.warning(f"Scheduler shutdown error: {e}")
    finally:
        _scheduler = None
