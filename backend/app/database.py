"""
AgentFlow AI - Database Configuration

Async SQLAlchemy engine, session factory, declarative base, and dependency injection.
"""

from collections.abc import AsyncGenerator
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase

from app.config import settings

def normalize_db_url(url: str) -> tuple[str, dict]:
    """Accept hosted-Postgres URLs (Neon, Render, Supabase) exactly as pasted.

    Providers hand out ``postgres://`` / ``postgresql://`` URLs carrying libpq
    params like ``sslmode=require``. asyncpg needs the ``postgresql+asyncpg``
    scheme and rejects ``sslmode``/``channel_binding``, so rewrite the scheme
    and translate sslmode into ``connect_args``.
    """
    if url.startswith("postgres://"):
        url = "postgresql://" + url[len("postgres://"):]
    if url.startswith("postgresql://"):
        url = "postgresql+asyncpg://" + url[len("postgresql://"):]
    if not url.startswith("postgresql+asyncpg://"):
        return url, {}

    parts = urlsplit(url)
    params = dict(parse_qsl(parts.query))
    connect_args: dict = {}
    sslmode = params.pop("sslmode", None)
    params.pop("channel_binding", None)
    if sslmode and sslmode != "disable":
        connect_args["ssl"] = "require"
    return urlunsplit(parts._replace(query=urlencode(params))), connect_args


_db_url, _connect_args = normalize_db_url(settings.DATABASE_URL)

# SQLite's async driver does not accept QueuePool sizing arguments, so only
# apply them for server-backed databases (PostgreSQL in Docker/production).
# Kept small: free-tier Postgres (Neon) caps concurrent connections.
engine_kwargs = {"echo": settings.DEBUG}
if "sqlite" not in _db_url:
    engine_kwargs.update(
        {
            "pool_size": 5,
            "max_overflow": 5,
            "pool_pre_ping": True,
            "connect_args": _connect_args,
        }
    )

engine = create_async_engine(_db_url, **engine_kwargs)

async_session_factory = async_sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False,
)


class Base(DeclarativeBase):
    """Declarative base class for all SQLAlchemy models."""
    pass


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """FastAPI dependency that provides a database session per request.

    Commits on success, rolls back on exception, and always closes the session.
    """
    async with async_session_factory() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()


async def init_db() -> None:
    """Create all database tables from the ORM metadata.

    Should be called once at application startup.
    """
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
