"""Tests for recurring schedule execution.

ScheduledTask rows could be created and listed, but nothing ever ran them
— the dashboard counted "active schedules" that would never fire. These
cover the executor that closes that gap.
"""

import uuid
from datetime import datetime, timedelta, timezone

import pytest

from app.config import settings
from app.core import scheduler as scheduler_module
from app.core.scheduler import compute_next_run, start_scheduler, stop_scheduler
from app.models.scheduled_task import ScheduledTask


def _aware(value: datetime | None) -> datetime | None:
    """SQLite hands back naive datetimes; normalise before comparing."""
    if value is None or value.tzinfo is not None:
        return value
    return value.replace(tzinfo=timezone.utc)


NOW = datetime(2026, 1, 1, 12, 0, tzinfo=timezone.utc)


class TestNextRunComputation:
    @pytest.mark.parametrize("schedule_type,expected", [
        ("hourly", datetime(2026, 1, 1, 13, 0, tzinfo=timezone.utc)),
        ("daily", datetime(2026, 1, 2, 12, 0, tzinfo=timezone.utc)),
        ("weekly", datetime(2026, 1, 8, 12, 0, tzinfo=timezone.utc)),
    ])
    def test_interval_shorthand(self, schedule_type, expected):
        assert compute_next_run(schedule_type, after=NOW) == expected

    def test_case_insensitive(self):
        assert compute_next_run("DAILY", after=NOW) == compute_next_run("daily", after=NOW)

    def test_cron_takes_precedence(self):
        # 9am daily, so from noon the next fire is tomorrow morning.
        assert compute_next_run("weekly", "0 9 * * *", after=NOW) == datetime(
            2026, 1, 2, 9, 0, tzinfo=timezone.utc
        )

    def test_invalid_cron_falls_back_to_schedule_type(self):
        assert compute_next_run("daily", "not a cron", after=NOW) == datetime(
            2026, 1, 2, 12, 0, tzinfo=timezone.utc
        )

    def test_unknown_type_returns_none(self):
        """None means 'never due', which is safer than guessing an interval."""
        assert compute_next_run("nonsense", after=NOW) is None
        assert compute_next_run("", after=NOW) is None
        assert compute_next_run(None, after=NOW) is None

    def test_naive_reference_is_treated_as_utc(self):
        naive = datetime(2026, 1, 1, 12, 0)
        assert compute_next_run("daily", after=naive) == datetime(
            2026, 1, 2, 12, 0, tzinfo=timezone.utc
        )


@pytest.mark.asyncio
class TestDueScheduleExecution:
    async def _seed(self, db, name, *, active=True, minutes=-5, next_run=True):
        user_id = uuid.uuid4()
        from app.models.user import User

        db.add(User(id=user_id, email=f"{user_id}@example.com",
                    hashed_password="x", full_name="T", role="user"))
        task = ScheduledTask(
            user_id=user_id, name=name, query="Sony WH-1000XM5",
            schedule_type="daily", sources=["amazon"], is_active=active,
            next_run_at=(datetime.now(timezone.utc) + timedelta(minutes=minutes))
            if next_run else None,
        )
        db.add(task)
        await db.commit()
        return task

    async def test_only_due_active_schedules_fire(self, monkeypatch):
        from sqlalchemy import select

        from app.models.workflow import Workflow
        from tests.conftest import TestSessionLocal

        # Keep the triggered workflow offline and instant.
        monkeypatch.setattr(settings, "DEBUG", True)
        monkeypatch.setattr(scheduler_module, "async_session_factory", TestSessionLocal,
                            raising=False)

        launched = []

        async def fake_launch(schedule):
            launched.append(schedule.name)

        monkeypatch.setattr(scheduler_module, "_launch", fake_launch)

        async with TestSessionLocal() as db:
            await self._seed(db, "due", minutes=-5)
            await self._seed(db, "future", minutes=1440)
            await self._seed(db, "inactive", active=False, minutes=-1440)
            await self._seed(db, "never", next_run=False)

        import app.database as database_module
        monkeypatch.setattr(database_module, "async_session_factory", TestSessionLocal)

        triggered = await scheduler_module.run_due_schedules()

        assert triggered == 1
        assert launched == ["due"]

        async with TestSessionLocal() as db:
            rows = {r.name: r for r in
                    (await db.execute(select(ScheduledTask))).scalars().all()}

        assert rows["due"].last_run_at is not None
        assert _aware(rows["due"].next_run_at) > datetime.now(timezone.utc)
        # Untouched schedules must not have their clocks advanced.
        assert rows["future"].last_run_at is None
        assert rows["inactive"].last_run_at is None
        assert rows["never"].last_run_at is None

    async def test_a_second_poll_does_not_refire(self, monkeypatch):
        from tests.conftest import TestSessionLocal
        import app.database as database_module

        monkeypatch.setattr(settings, "DEBUG", True)
        monkeypatch.setattr(database_module, "async_session_factory", TestSessionLocal)

        calls = []

        async def fake_launch(schedule):
            calls.append(schedule.name)

        monkeypatch.setattr(scheduler_module, "_launch", fake_launch)

        async with TestSessionLocal() as db:
            await self._seed(db, "due", minutes=-5)

        assert await scheduler_module.run_due_schedules() == 1
        assert await scheduler_module.run_due_schedules() == 0
        assert calls == ["due"]

    async def test_a_failing_schedule_still_advances_its_clock(self, monkeypatch):
        """Otherwise one broken schedule fires on every single poll."""
        from sqlalchemy import select

        from tests.conftest import TestSessionLocal
        import app.database as database_module

        monkeypatch.setattr(database_module, "async_session_factory", TestSessionLocal)

        async def exploding_launch(schedule):
            raise RuntimeError("workflow could not be created")

        monkeypatch.setattr(scheduler_module, "_launch", exploding_launch)

        async with TestSessionLocal() as db:
            await self._seed(db, "broken", minutes=-5)

        triggered = await scheduler_module.run_due_schedules()
        assert triggered == 0, "a failed launch is not a trigger"

        async with TestSessionLocal() as db:
            row = (await db.execute(select(ScheduledTask))).scalar_one()

        assert _aware(row.next_run_at) > datetime.now(timezone.utc)

    async def test_poll_never_raises(self, monkeypatch):
        """A scheduler that dies on one bad query stops running everything."""
        import app.database as database_module

        def explode(*args, **kwargs):
            raise ConnectionError("database is gone")

        monkeypatch.setattr(database_module, "async_session_factory", explode)

        assert await scheduler_module.run_due_schedules() == 0


class TestLifecycle:
    def test_disabled_scheduler_does_not_start(self, monkeypatch):
        monkeypatch.setattr(settings, "SCHEDULER_ENABLED", False)
        monkeypatch.setattr(scheduler_module, "_scheduler", None)

        start_scheduler()
        assert scheduler_module._scheduler is None

    def test_stop_is_safe_when_never_started(self, monkeypatch):
        monkeypatch.setattr(scheduler_module, "_scheduler", None)
        stop_scheduler()  # must not raise
