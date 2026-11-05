"""AgentFlow AI - FastAPI application entry point."""

import time as _time

_BOOT_STARTED = _time.perf_counter()

from contextlib import asynccontextmanager  # noqa: E402

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from prometheus_client import make_asgi_app

from app.database import async_session_factory, init_db
from app.services.workflow_service import fail_interrupted_workflows
from app.core.exceptions import AppError, app_error_handler
from app.core.middleware import RequestLoggingMiddleware, PrometheusMiddleware
from app.core import perf
from app.core.perf import PerfMiddleware
from app.config import settings
from app.core.scheduler import start_scheduler, stop_scheduler
from app.core.logging import get_logger

from app.api.auth import router as auth_router
from app.api.workflows import router as workflows_router
from app.api.reports import router as reports_router
from app.api.dashboard import router as dashboard_router
from app.api.rag import router as rag_router
from app.api.schedule import router as schedule_router
from app.api.monitoring import router as monitoring_router
from app.api.admin import router as admin_router

logger = get_logger(__name__)

# Imports above are the bulk of boot time on a cold start.
_BOOT_READY = _time.perf_counter()


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Starting up application...")
    with perf.trace("startup") as boot:
        with perf.span("startup.init_db"):
            await init_db()
        with perf.span("startup.reaper"):
            async with async_session_factory() as db:
                interrupted = await fail_interrupted_workflows(db)
        if interrupted:
            logger.warning(f"Marked {interrupted} interrupted workflow(s) as failed")
        with perf.span("startup.scheduler"):
            start_scheduler()
    logger.info(
        "startup_perf",
        import_ms=round((_BOOT_READY - _BOOT_STARTED) * 1000, 1),
        **boot.summary(),
    )
    yield
    logger.info("Shutting down application...")
    stop_scheduler()


app = FastAPI(title=settings.APP_NAME, version="1.0.0", lifespan=lifespan)

# Origins come from CORS_ORIGINS. Browsers reject a wildcard origin when
# credentials are sent, so the two settings are kept consistent here rather
# than shipping a combination that silently fails in the browser.
_cors_origins = settings.cors_origins
_allow_credentials = "*" not in _cors_origins

if not _allow_credentials:
    logger.warning("CORS is set to '*'; credentialed requests are disabled")

app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins,
    allow_origin_regex=settings.CORS_ORIGIN_REGEX or None,
    allow_credentials=_allow_credentials,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.add_middleware(RequestLoggingMiddleware)
app.add_middleware(PrometheusMiddleware)
# Added last so it is outermost: the trace covers the whole request.
app.add_middleware(PerfMiddleware)

app.add_exception_handler(AppError, app_error_handler)

metrics_app = make_asgi_app()
app.mount("/metrics", metrics_app)

app.include_router(auth_router, prefix="/api/auth", tags=["auth"])
app.include_router(workflows_router, prefix="/api/workflows", tags=["workflows"])
app.include_router(reports_router, prefix="/api/reports", tags=["reports"])
app.include_router(dashboard_router, prefix="/api/dashboard", tags=["dashboard"])
app.include_router(rag_router, prefix="/api/rag", tags=["rag"])
app.include_router(schedule_router, prefix="/api/schedules", tags=["schedules"])
app.include_router(monitoring_router, prefix="/api/monitoring", tags=["monitoring"])
app.include_router(admin_router, prefix="/api/admin", tags=["admin"])


@app.get("/")
async def root():
    return {"name": settings.APP_NAME, "version": "1.0.0", "status": "ok"}
