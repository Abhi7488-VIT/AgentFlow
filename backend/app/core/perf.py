"""Lightweight timing instrumentation.

One ``PerfTrace`` collects named spans (durations) and counters for a unit
of work: an HTTP request or a workflow run. The active trace lives in a
``ContextVar``; tasks created by ``asyncio.gather`` and LangGraph copy the
context, and the copy still points at the same trace object, so spans from
concurrent scrapers all land in the workflow's trace.

Everything here is cheap (a ``perf_counter`` pair and a list append) and a
no-op when no trace is active, so instrumented code runs unchanged in tests.

* ``span("name")`` - time a block (sync ``with``, usable around ``await``).
* ``incr("counter")`` - bump a counter, e.g. ``gemini.calls``.
* SQL statements are counted per trace via an engine event listener.
* ``PerfMiddleware`` gives every request a trace and, when
  ``settings.PERF_DEBUG`` is on, returns it as ``Server-Timing`` and
  ``X-SQL-Queries`` headers so browser devtools show the split.
"""

from __future__ import annotations

import time
from collections import defaultdict
from contextlib import contextmanager
from contextvars import ContextVar
from typing import Any, Iterator

from sqlalchemy import event
from sqlalchemy.engine import Engine

from app.config import settings


class PerfTrace:
    """Spans and counters for one request or workflow."""

    def __init__(self, name: str) -> None:
        self.name = name
        self.started = time.perf_counter()
        self.spans: list[dict[str, Any]] = []
        self.counters: dict[str, int] = defaultdict(int)

    def add(self, name: str, ms: float, **tags: Any) -> None:
        self.spans.append({"name": name, "ms": round(ms, 2), **tags})

    def incr(self, key: str, n: int = 1) -> None:
        self.counters[key] += n

    @property
    def elapsed_ms(self) -> float:
        return (time.perf_counter() - self.started) * 1000

    def totals(self) -> dict[str, dict[str, float]]:
        """Sum and count per span name."""
        out: dict[str, dict[str, float]] = {}
        for s in self.spans:
            agg = out.setdefault(s["name"], {"ms": 0.0, "count": 0})
            agg["ms"] = round(agg["ms"] + s["ms"], 2)
            agg["count"] += 1
        return out

    def summary(self) -> dict[str, Any]:
        return {
            "trace": self.name,
            "total_ms": round(self.elapsed_ms, 2),
            "spans": self.totals(),
            "counters": dict(self.counters),
        }


_current: ContextVar[PerfTrace | None] = ContextVar("perf_trace", default=None)


def current() -> PerfTrace | None:
    return _current.get()


@contextmanager
def trace(name: str) -> Iterator[PerfTrace]:
    """Make a new trace active for the duration of the block."""
    t = PerfTrace(name)
    token = _current.set(t)
    try:
        yield t
    finally:
        _current.reset(token)


@contextmanager
def span(name: str, **tags: Any) -> Iterator[None]:
    """Record how long the block took on the active trace (if any)."""
    t = _current.get()
    if t is None:
        yield
        return
    start = time.perf_counter()
    try:
        yield
    finally:
        t.add(name, (time.perf_counter() - start) * 1000, **tags)


def incr(key: str, n: int = 1) -> None:
    t = _current.get()
    if t is not None:
        t.incr(key, n)


def record(name: str, ms: float, **tags: Any) -> None:
    t = _current.get()
    if t is not None:
        t.add(name, ms, **tags)


# --------------------------------------------------------------------- #
#  LLM calls
# --------------------------------------------------------------------- #

def _usage(response: Any) -> dict[str, int]:
    """Token counts from a Gemini response, tolerant of SDK differences.

    ``thoughts`` is derived as total - prompt - output when the SDK does not
    report it, which is how thinking overhead shows up on 2.5+ models.
    """
    meta = getattr(response, "usage_metadata", None)
    if meta is None:
        return {}
    prompt = int(getattr(meta, "prompt_token_count", 0) or 0)
    output = int(getattr(meta, "candidates_token_count", 0) or 0)
    total = int(getattr(meta, "total_token_count", 0) or 0)
    thoughts = int(getattr(meta, "thoughts_token_count", 0) or 0)
    if not thoughts and total:
        thoughts = max(total - prompt - output, 0)
    return {"prompt": prompt, "output": output, "thoughts": thoughts, "total": total}


async def timed_llm_call(agent: str, coro: Any, kind: str = "generate") -> Any:
    """Await a Gemini call, recording latency, count, errors and tokens."""
    incr("gemini.calls")
    incr(f"gemini.calls.{agent}")
    start = time.perf_counter()
    try:
        response = await coro
    except Exception:
        incr("gemini.errors")
        record(f"gemini.{agent}.call", (time.perf_counter() - start) * 1000, kind=kind, ok=False)
        raise
    usage = _usage(response)
    record(f"gemini.{agent}.call", (time.perf_counter() - start) * 1000, kind=kind, ok=True, **usage)
    for key, value in usage.items():
        incr(f"gemini.tokens.{key}", value)
    return response


# --------------------------------------------------------------------- #
#  SQL statement counter
# --------------------------------------------------------------------- #

_sql_listener_installed = False


def _count_statement(conn, cursor, statement, parameters, context, executemany):  # noqa: ARG001
    t = _current.get()
    if t is not None:
        t.incr("sql.queries")
        if settings.PERF_DEBUG and settings.PERF_LOG_SQL:
            t.spans.append({"name": "sql.statement", "ms": 0.0, "sql": statement[:160]})


def install_sql_counter() -> None:
    """Count every SQL statement on any engine (async engines included).

    Registered on the ``Engine`` class so the app engine, the worker and
    the test engine are all covered. Idempotent.
    """
    global _sql_listener_installed
    if _sql_listener_installed:
        return
    event.listen(Engine, "before_cursor_execute", _count_statement)
    _sql_listener_installed = True


install_sql_counter()


# --------------------------------------------------------------------- #
#  Request middleware
# --------------------------------------------------------------------- #

def _server_timing(t: PerfTrace) -> str:
    parts = [f'total;dur={t.elapsed_ms:.1f}']
    for name, agg in t.totals().items():
        if name == "sql.statement":
            continue
        metric = name.replace(".", "-")
        parts.append(f'{metric};dur={agg["ms"]:.1f}')
    queries = t.counters.get("sql.queries", 0)
    parts.append(f'sql;desc="{queries} queries"')
    return ", ".join(parts)


class PerfMiddleware:
    """Pure ASGI middleware: one trace per HTTP request.

    Pure ASGI (not ``BaseHTTPMiddleware``) so the trace is set in the same
    context the endpoint runs in and headers can be added before they are
    sent. Headers are only exposed with ``PERF_DEBUG`` - they reveal
    internal timings, e.g. how long bcrypt took, which is a side channel.
    """

    def __init__(self, app) -> None:
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        with trace(f'{scope.get("method")} {scope.get("path")}') as t:
            async def send_wrapper(message):
                if message["type"] == "http.response.start" and settings.PERF_DEBUG:
                    headers = list(message.get("headers", []))
                    headers.append((b"server-timing", _server_timing(t).encode()))
                    headers.append(
                        (b"x-sql-queries", str(t.counters.get("sql.queries", 0)).encode())
                    )
                    message = {**message, "headers": headers}
                await send(message)

            await self.app(scope, receive, send_wrapper)
