"""Tests for the Phase-0 timing instrumentation (app/core/perf.py).

All offline: Gemini responses are fakes and scrapers are stubs.
"""

import asyncio
from types import SimpleNamespace

import pytest
from sqlalchemy import text

import app.agents.graph as graph_module
from app.config import settings
from app.core import perf
from app.scrapers.base import BaseScraper
from tests.conftest import TestSessionLocal


class TestTraceBasics:
    def test_span_is_a_noop_without_an_active_trace(self):
        assert perf.current() is None
        with perf.span("anything"):
            pass
        perf.incr("anything")  # must not raise
        assert perf.current() is None

    def test_span_and_counter_are_recorded(self):
        with perf.trace("t") as t:
            with perf.span("stage", detail="x"):
                pass
            perf.incr("calls")
            perf.incr("calls", 2)

        summary = t.summary()
        assert summary["spans"]["stage"]["count"] == 1
        assert summary["counters"]["calls"] == 3
        assert t.spans[0]["detail"] == "x"

    def test_trace_is_reset_after_the_block(self):
        with perf.trace("outer") as outer:
            with perf.trace("inner") as inner:
                assert perf.current() is inner
            assert perf.current() is outer
        assert perf.current() is None

    async def test_spans_from_gathered_tasks_land_in_one_trace(self):
        """Concurrent scrapers run in copied contexts; their spans must merge."""
        async def work(name):
            with perf.span(name):
                await asyncio.sleep(0)

        with perf.trace("wf") as t:
            await asyncio.gather(work("a"), work("b"), work("c"))

        assert set(t.totals()) == {"a", "b", "c"}


class TestSqlCounter:
    async def test_statements_are_counted_per_trace(self):
        with perf.trace("q") as t:
            async with TestSessionLocal() as db:
                await db.execute(text("SELECT 1"))
                await db.execute(text("SELECT 2"))

        assert t.counters["sql.queries"] == 2


class TestLlmTiming:
    async def test_successful_call_records_latency_and_tokens(self):
        meta = SimpleNamespace(
            prompt_token_count=100, candidates_token_count=40, total_token_count=640
        )

        async def fake_call():
            return SimpleNamespace(usage_metadata=meta, text="{}")

        with perf.trace("wf") as t:
            await perf.timed_llm_call("report", fake_call())

        assert t.counters["gemini.calls"] == 1
        assert t.counters["gemini.calls.report"] == 1
        # 640 - 100 - 40: thinking tokens show up as the unexplained remainder.
        assert t.counters["gemini.tokens.thoughts"] == 500
        assert "gemini.report.call" in t.totals()

    async def test_failed_call_is_counted_and_reraised(self):
        async def failing():
            raise RuntimeError("429 quota")

        with perf.trace("wf") as t:
            with pytest.raises(RuntimeError):
                await perf.timed_llm_call("insights", failing())

        assert t.counters["gemini.calls"] == 1
        assert t.counters["gemini.errors"] == 1


class _FlakyScraper(BaseScraper):
    """Fails twice, then returns one live and one mock item."""

    def __init__(self):
        super().__init__(max_retries=3, request_delay=0, backoff_factor=2.0)
        self.calls = 0

    async def _scrape_impl(self, query, max_results):
        self.calls += 1
        if self.calls < 3:
            raise RuntimeError("transient")
        return [
            {"content": "a", "metadata": {"is_mock": False}},
            {"content": "b", "metadata": {"is_mock": True}},
        ]


class TestScraperTiming:
    async def test_retries_and_backoff_sleeps_are_visible(self, monkeypatch):
        slept = []

        async def no_sleep(seconds):
            slept.append(seconds)

        monkeypatch.setattr("app.scrapers.base.asyncio.sleep", no_sleep)

        with perf.trace("wf") as t:
            items = await _FlakyScraper().scrape("q")

        totals = t.totals()
        assert len(items) == 2
        assert t.counters["scrape._flaky.attempts"] == 3
        assert totals["scrape._flaky.attempt"]["count"] == 3
        # Two backoff sleeps (2s, 4s) before the third attempt succeeds.
        assert slept == [2.0, 4.0]
        assert totals["scrape._flaky.sleep"]["count"] == 2
        assert t.counters["scrape._flaky.mock_items"] == 1
        assert "scrape._flaky.total" in totals


class TestGraphTiming:
    async def test_each_node_pass_is_a_span(self, monkeypatch):
        async def passthrough(state):
            return state

        async def reviewer(state):
            state["revision_count"] = state.get("revision_count", 0) + 1
            state["review_feedback"] = {"approved": True}
            return state

        for name in ("research_node", "cleaning_node", "nlp_node", "insight_node", "report_node"):
            monkeypatch.setattr(graph_module, name, passthrough)
        monkeypatch.setattr(graph_module, "reviewer_node", reviewer)

        with perf.trace("wf") as t:
            await graph_module.run_workflow("q", ["reddit"], "wf-perf")

        totals = t.totals()
        for node in ("research", "cleaning", "nlp_analysis", "insights", "report", "reviewer"):
            assert f"agent.{node}" in totals
        assert t.counters["agent.report.passes"] == 1


class TestRequestHeaders:
    async def test_headers_hidden_by_default(self, client):
        response = await client.get("/")
        assert "server-timing" not in response.headers
        assert "x-sql-queries" not in response.headers

    async def test_debug_flag_exposes_server_timing(self, client, monkeypatch):
        monkeypatch.setattr(settings, "PERF_DEBUG", True)
        response = await client.get("/api/monitoring/health")

        assert "total;dur=" in response.headers["server-timing"]
        assert int(response.headers["x-sql-queries"]) >= 1

    async def test_login_is_split_into_lookup_bcrypt_and_token(self, client, monkeypatch):
        await client.post("/api/auth/register", json={
            "email": "perf@example.com", "password": "Correct-Horse-Battery9", "full_name": "P",
        })
        monkeypatch.setattr(settings, "PERF_DEBUG", True)

        response = await client.post(
            "/api/auth/login",
            data={"username": "perf@example.com", "password": "Correct-Horse-Battery9"},
        )

        assert response.status_code == 200
        timing = response.headers["server-timing"]
        for metric in ("auth-db_lookup", "auth-bcrypt_verify", "auth-token_create"):
            assert metric in timing
