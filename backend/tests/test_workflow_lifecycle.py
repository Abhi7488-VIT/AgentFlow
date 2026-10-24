"""Tests for workflow status bookkeeping in the background task.

Regression: the task used to build its own engine from the raw
DATABASE_URL, which crashes on hosted-Postgres URLs (Neon's
``postgresql://...?sslmode=require``) before the workflow is marked
running, so workflows sat in "pending" forever in production.
"""

import pytest
from sqlalchemy import select

from app.models.user import User
from app.models.workflow import Workflow
from app.schemas.workflow import WorkflowCreate
from app.services import workflow_service
from app.workers import tasks
from tests.conftest import TestSessionLocal


async def _make_workflow(status: str = "pending") -> Workflow:
    async with TestSessionLocal() as db:
        user = User(email="owner@example.com", hashed_password="x", full_name="O", role="admin")
        db.add(user)
        await db.commit()
        await db.refresh(user)
        wf = await workflow_service.create_workflow(
            db, user.id, WorkflowCreate(query="e-bikes", sources=["youtube"])
        )
        if status != "pending":
            wf.status = status
            await db.commit()
        return wf


async def _status(workflow_id) -> Workflow:
    async with TestSessionLocal() as db:
        return (await db.execute(select(Workflow).where(Workflow.id == workflow_id))).scalar_one()


@pytest.mark.asyncio
class TestBackgroundTask:
    async def test_task_uses_the_shared_session_factory(self, monkeypatch):
        """The task must not build its own engine from the raw URL."""
        assert not hasattr(tasks, "create_async_engine")
        monkeypatch.setattr(tasks, "async_session_factory", TestSessionLocal)
        wf = await _make_workflow()

        async def boom(*args, **kwargs):
            raise RuntimeError("pipeline exploded")

        monkeypatch.setattr(tasks, "run_workflow", boom)
        await tasks.execute_workflow_task(
            workflow_id=wf.id, query="e-bikes", sources=["youtube"], user_id=wf.user_id
        )

        saved = await _status(wf.id)
        assert saved.status == "failed"
        assert "pipeline exploded" in saved.result_summary


@pytest.mark.asyncio
class TestInterruptedWorkflows:
    @pytest.mark.parametrize("status", ["pending", "running"])
    async def test_in_flight_workflows_are_failed_on_startup(self, status):
        wf = await _make_workflow(status)

        async with TestSessionLocal() as db:
            count = await workflow_service.fail_interrupted_workflows(db)

        saved = await _status(wf.id)
        assert count == 1
        assert saved.status == "failed"
        assert "restart" in saved.result_summary

    async def test_finished_workflows_are_left_alone(self):
        wf = await _make_workflow("completed")

        async with TestSessionLocal() as db:
            assert await workflow_service.fail_interrupted_workflows(db) == 0

        assert (await _status(wf.id)).status == "completed"
