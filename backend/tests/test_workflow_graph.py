"""Tests for LangGraph wiring and the report/reviewer revision loop.

The agent nodes are replaced with stubs so the graph's control flow is
tested on its own, without network calls.
"""

import pytest

import app.agents.graph as graph_module
from app.config import settings


@pytest.fixture
def stub_nodes(monkeypatch):
    """Replace every agent node with a counting stub."""
    calls = {"report": 0, "reviewer": 0, "research": 0}

    async def research(state):
        calls["research"] += 1
        state["raw_data"] = [{"source": "reddit", "content": "x"}]
        return state

    async def passthrough(state):
        state["cleaned_data"] = [{"source": "reddit", "content": "x"}]
        return state

    async def report(state):
        calls["report"] += 1
        state["report"] = {"title": "T", "executive_summary": "S"}
        return state

    monkeypatch.setattr(graph_module, "research_node", research)
    monkeypatch.setattr(graph_module, "cleaning_node", passthrough)
    monkeypatch.setattr(graph_module, "nlp_node", passthrough)
    monkeypatch.setattr(graph_module, "insight_node", passthrough)
    monkeypatch.setattr(graph_module, "report_node", report)

    return calls, monkeypatch


def _reviewer(calls, feedback):
    """Build a reviewer stub that returns a fixed feedback payload."""
    async def reviewer(state):
        calls["reviewer"] += 1
        state["revision_count"] = state.get("revision_count", 0) + 1
        state["review_feedback"] = feedback
        return state
    return reviewer


class TestGraphStructure:
    def test_graph_has_six_nodes(self):
        graph = graph_module.create_workflow_graph()
        nodes = set(graph.get_graph().nodes) - {"__start__", "__end__"}

        assert nodes == {
            "research", "cleaning", "nlp_analysis",
            "insights", "report", "reviewer",
        }


@pytest.mark.asyncio
class TestRevisionLoop:
    async def test_approved_report_ends_immediately(self, stub_nodes):
        calls, monkeypatch = stub_nodes
        monkeypatch.setattr(
            graph_module, "reviewer_node",
            _reviewer(calls, {"approved": True, "quality_score": 0.9}),
        )

        await graph_module.run_workflow("q", ["reddit"], "wf-approved")

        assert calls["report"] == 1
        assert calls["reviewer"] == 1

    async def test_rejection_loops_back_to_report_then_stops(self, stub_nodes):
        calls, monkeypatch = stub_nodes
        monkeypatch.setattr(
            graph_module, "reviewer_node",
            _reviewer(calls, {"approved": False, "feedback": "needs work"}),
        )

        await graph_module.run_workflow("q", ["reddit"], "wf-rejected")

        # It must revise at least once, but never run away.
        assert calls["report"] > 1
        assert calls["report"] <= settings.MAX_REPORT_REVISIONS + 1
        assert calls["reviewer"] <= settings.MAX_REPORT_REVISIONS + 1

    async def test_malformed_review_feedback_still_terminates(self, stub_nodes):
        """The worst case: the reviewer returns JSON with no 'approved' key."""
        calls, monkeypatch = stub_nodes
        monkeypatch.setattr(graph_module, "reviewer_node", _reviewer(calls, {}))

        final = await graph_module.run_workflow("q", ["reddit"], "wf-malformed")

        assert calls["reviewer"] <= settings.MAX_REPORT_REVISIONS + 1
        assert final["revision_count"] <= settings.MAX_REPORT_REVISIONS + 1

    async def test_none_review_feedback_does_not_crash_the_router(self, stub_nodes):
        calls, monkeypatch = stub_nodes
        monkeypatch.setattr(graph_module, "reviewer_node", _reviewer(calls, None))

        await graph_module.run_workflow("q", ["reddit"], "wf-none")

        assert calls["reviewer"] <= settings.MAX_REPORT_REVISIONS + 1


@pytest.mark.asyncio
class TestMockDataLabelling:
    async def test_reddit_mock_items_are_flagged(self, monkeypatch):
        """Synthetic data must never be indistinguishable from real data."""
        from app.scrapers.reddit import RedditScraper

        monkeypatch.setattr(settings, "REDDIT_CLIENT_ID", "")
        monkeypatch.setattr(settings, "REDDIT_CLIENT_SECRET", "")

        items = await RedditScraper().scrape("test product", max_results=10)

        assert items
        assert all(item["metadata"]["is_mock"] is True for item in items)
        assert all(item["source"] == "reddit" for item in items)

    async def test_mock_can_be_disabled_so_failures_surface(self, monkeypatch):
        from app.scrapers.reddit import RedditScraper

        monkeypatch.setattr(settings, "REDDIT_CLIENT_ID", "")
        monkeypatch.setattr(settings, "REDDIT_CLIENT_SECRET", "")
        monkeypatch.setattr(settings, "ALLOW_MOCK_DATA", False)

        scraper = RedditScraper(max_retries=1)
        with pytest.raises(RuntimeError):
            await scraper.scrape("test product", max_results=10)

    async def test_live_response_mappers_flag_data_as_real(self):
        from app.scrapers.reddit import RedditScraper

        post = RedditScraper._post_item({
            "title": "Review", "selftext": "Body text", "subreddit": "gadgets",
            "score": 10, "author": "u1", "created_utc": 1700000000,
            "num_comments": 3, "permalink": "/r/gadgets/x", "id": "abc",
        })

        assert post["metadata"]["is_mock"] is False
        assert post["content"] == "Review\n\nBody text"
        assert post["metadata"]["subreddit"] == "gadgets"

    async def test_deleted_author_is_handled(self):
        from app.scrapers.reddit import RedditScraper

        comment = RedditScraper._comment_item(
            {"body": "text", "score": 1, "author": None, "created_utc": 1700000000},
            "title", "gadgets",
        )

        assert comment["metadata"]["author"] == "[deleted]"
