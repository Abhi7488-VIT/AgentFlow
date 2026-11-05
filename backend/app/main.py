"""AgentFlow AI - FastAPI application entry point."""

import time as _time

_BOOT_STARTED = _time.perf_counter()

import asyncio  # noqa: E402
from contextlib import asynccontextmanager  # noqa: E402

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from prometheus_client import make_asgi_app
from sqlalchemy import text

from app.database import async_session_factory
from app.core.exceptions import AppError, app_error_handler
from app.core.middleware import RequestLoggingMiddleware, PrometheusMiddleware
from app.core import startup
from app.core.perf import PerfMiddleware
from app.config import settings
from app.core.scheduler import stop_scheduler
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
    # Serve immediately; DB setup, reaper and scheduler run in the
    # background (app/core/startup.py). /health/ready reports when done.
    logger.info(
        "Starting up application...",
        import_ms=round((_BOOT_READY - _BOOT_STARTED) * 1000, 1),
    )
    background = [
        asyncio.create_task(startup.run_startup()),
        asyncio.create_task(startup.preload_heavy_modules()),
    ]
    yield
    logger.info("Shutting down application...")
    for task in background:
        task.cancel()
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


@app.get("/health", include_in_schema=False)
@app.get("/api/health", include_in_schema=False)
async def health():
    """Liveness: the process is up. No database access, so keep-alive pings
    and cold-start wake-ups never wake Neon or hold a pool connection."""
    return {"status": "ok"}


@app.get("/health/ready", include_in_schema=False)
@app.get("/api/health/ready", include_in_schema=False)
async def health_ready():
    """Readiness: startup work finished and the database answers."""
    if not startup.state.ready:
        return JSONResponse(
            status_code=503,
            content={"status": "starting", "attempts": startup.state.attempts,
                     "error": startup.state.error},
        )
    try:
        async with async_session_factory() as db:
            await db.execute(text("SELECT 1"))
    except Exception:  # noqa: BLE001
        return JSONResponse(status_code=503, content={"status": "degraded", "database": "error"})
    return {"status": "ready", "database": "ok"}
