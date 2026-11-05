"""Non-blocking startup.

Before this, the lifespan awaited table creation, the interrupted-workflow
reaper and the scheduler before uvicorn accepted a single request. On a
Render cold start that time is added to the wake-up the user is already
waiting through. Now uvicorn starts serving immediately and this work runs in
a background task:

* ``GET /health`` answers as soon as the process is up (keep-alive pings,
  Render's health check). It never touches the database.
* ``GET /health/ready`` returns 503 until startup work has finished and the
  database answers, so a deploy check or the frontend can tell "awake" from
  "ready".

Two consequences are handled here:

* The reaper must not fail a workflow that a user created *during* the
  startup window, so it only touches rows created before this process
  started (``PROCESS_STARTED_AT``).
* If the database is unreachable at boot (Neon waking up), the work is
  retried with backoff instead of crashing the process.
"""

from __future__ import annotations

import asyncio
import importlib
import time
from datetime import datetime, timezone

from app.config import settings
from app.core import perf
from app.core.logging import get_logger

logger = get_logger(__name__)

PROCESS_STARTED_AT = datetime.now(timezone.utc)

# Modules kept off the boot path (see app/api/workflows.py, app/api/rag.py).
HEAVY_MODULES = ("app.workers.tasks", "app.services.rag_service")


class StartupState:
    def __init__(self) -> None:
        self.ready = False
        self.error: str | None = None
        self.attempts = 0
        self.finished_at: float | None = None


state = StartupState()


async def _initialise_once() -> int:
    from app.core.scheduler import start_scheduler
    from app.database import async_session_factory, init_db
    from app.services.workflow_service import fail_interrupted_workflows

    if settings.DB_CREATE_ALL_ON_STARTUP:
        with perf.span("startup.init_db"):
            await init_db()
    with perf.span("startup.reaper"):
        async with async_session_factory() as db:
            interrupted = await fail_interrupted_workflows(
                db, created_before=PROCESS_STARTED_AT
            )
    with perf.span("startup.scheduler"):
        start_scheduler()
    return interrupted


async def run_startup(max_backoff: float = 30.0) -> None:
    """Run startup work until it succeeds. Never raises."""
    delay = 1.0
    with perf.trace("startup") as t:
        while True:
            state.attempts += 1
            try:
                interrupted = await _initialise_once()
                break
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # noqa: BLE001 - keep retrying, never crash boot
                state.error = str(exc)
                logger.warning(
                    "startup_retry", attempt=state.attempts, error=str(exc), retry_in=delay
                )
                await asyncio.sleep(delay)
                delay = min(delay * 2, max_backoff)

    state.ready = True
    state.error = None
    state.finished_at = time.perf_counter()
    if interrupted:
        logger.warning(f"Marked {interrupted} interrupted workflow(s) as failed")
    logger.info("startup_perf", attempts=state.attempts, **t.summary())


async def preload_heavy_modules(delay: float | None = None) -> None:
    """Import the agent / RAG stack in a thread after a delay.

    The first workflow would otherwise pay several seconds of imports
    (much more on a 0.1 vCPU host). The delay keeps the import from
    competing for CPU with the login that usually follows a cold start.
    """
    delay = settings.PRELOAD_DELAY_SECONDS if delay is None else delay
    if delay < 0:
        return
    await asyncio.sleep(delay)
    start = time.perf_counter()
    for name in HEAVY_MODULES:
        try:
            await asyncio.to_thread(importlib.import_module, name)
        except Exception as exc:  # noqa: BLE001 - first use will raise properly
            logger.warning("preload_failed", module=name, error=str(exc))
    logger.info("preload_done", ms=round((time.perf_counter() - start) * 1000))
