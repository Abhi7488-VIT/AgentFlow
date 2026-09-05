"""Tests for MLflow experiment tracking.

Tracking is a reporting sink, not part of the workflow contract, so the
behaviour that matters most is that it never raises.
"""

import pytest

import app.core.tracking as tracking
from app.config import settings


@pytest.fixture(autouse=True)
def reset_tracking_state(monkeypatch):
    """Each test starts with the lazy MLflow import un-cached."""
    monkeypatch.setattr(tracking, "_mlflow", None)
    monkeypatch.setattr(tracking, "_init_failed", False)


SAMPLE_STATE = {
    "cleaned_data": [
        {"content": "a", "metadata": {"is_mock": False}},
        {"content": "b", "metadata": {"is_mock": True}},
    ],
    "topics": [{"topic_id": 0}],
    "keywords": [{"keyword": "battery"}],
    "trends": {"average_sentiment": 0.2, "overall_positive_percentage": 50.0},
    "agent_logs": [{"agent_name": "research", "execution_time_ms": 100}],
    "revision_count": 1,
    "status": "completed",
    "review_feedback": {"approved": True, "quality_score": 0.9},
}


class TestGracefulDegradation:
    def test_disabled_tracking_is_a_no_op(self, monkeypatch):
        monkeypatch.setattr(settings, "MLFLOW_ENABLED", False)

        tracking.log_workflow_run("wf", "q", ["amazon"], SAMPLE_STATE, {})
        assert tracking._get_mlflow() is None

    def test_unimportable_mlflow_does_not_raise(self, monkeypatch):
        def explode(*args, **kwargs):
            raise ImportError("mlflow is not installed")

        monkeypatch.setattr(settings, "MLFLOW_ENABLED", True)
        monkeypatch.setattr(tracking, "_get_mlflow", lambda: explode())

        with pytest.raises(ImportError):
            tracking._get_mlflow()

    def test_logging_failure_is_swallowed(self, monkeypatch):
        """An unreachable tracking server must not fail the workflow."""
        class BrokenMlflow:
            def start_run(self, **kwargs):
                raise ConnectionError("tracking server unreachable")

        monkeypatch.setattr(settings, "MLFLOW_ENABLED", True)
        monkeypatch.setattr(tracking, "_mlflow", BrokenMlflow())

        # Must return normally rather than propagating.
        tracking.log_workflow_run("wf", "q", ["amazon"], SAMPLE_STATE, {})

    def test_malformed_state_does_not_raise(self, monkeypatch):
        monkeypatch.setattr(settings, "MLFLOW_ENABLED", False)

        for state in ({}, {"cleaned_data": None}, {"agent_logs": [{"bad": 1}]}):
            tracking.log_workflow_run("wf", "q", [], state, None)


class TestRecordedValues:
    def test_metrics_and_params_are_captured(self, monkeypatch):
        recorded = {"params": {}, "metrics": {}, "tags": {}}

        class FakeRun:
            def __enter__(self): return self
            def __exit__(self, *exc): return False

        class FakeMlflow:
            def start_run(self, **kwargs): return FakeRun()
            def log_params(self, params): recorded["params"].update(params)
            def log_metrics(self, metrics): recorded["metrics"].update(metrics)
            def log_metric(self, key, value): recorded["metrics"][key] = value
            def set_tags(self, tags): recorded["tags"].update(tags)

        monkeypatch.setattr(settings, "MLFLOW_ENABLED", True)
        monkeypatch.setattr(tracking, "_mlflow", FakeMlflow())

        tracking.log_workflow_run(
            "wf-1", "Sony WH-1000XM5", ["amazon", "youtube"],
            SAMPLE_STATE, {"chunks": 156, "embedding_model": "gemini-embedding-001"},
        )

        assert recorded["params"]["query"] == "Sony WH-1000XM5"
        assert recorded["params"]["sources"] == "amazon,youtube"

        metrics = recorded["metrics"]
        assert metrics["items_collected"] == 2.0
        assert metrics["items_live"] == 1.0
        assert metrics["items_mock"] == 1.0
        assert metrics["live_data_ratio"] == 0.5
        assert metrics["chunks_indexed"] == 156.0
        assert metrics["agent_research_ms"] == 100.0
        assert metrics["report_quality_score"] == 0.9
        assert recorded["tags"]["status"] == "completed"

    def test_long_values_are_truncated_for_params(self, monkeypatch):
        recorded = {}

        class FakeRun:
            def __enter__(self): return self
            def __exit__(self, *exc): return False

        class FakeMlflow:
            def start_run(self, **kwargs): return FakeRun()
            def log_params(self, params): recorded.update(params)
            def log_metrics(self, m): pass
            def log_metric(self, k, v): pass
            def set_tags(self, t): pass

        monkeypatch.setattr(settings, "MLFLOW_ENABLED", True)
        monkeypatch.setattr(tracking, "_mlflow", FakeMlflow())

        tracking.log_workflow_run("wf", "x" * 5000, ["amazon"], SAMPLE_STATE, {})

        assert len(recorded["query"]) <= 250

    def test_empty_corpus_gives_zero_ratio_not_division_error(self, monkeypatch):
        recorded = {}

        class FakeRun:
            def __enter__(self): return self
            def __exit__(self, *exc): return False

        class FakeMlflow:
            def start_run(self, **kwargs): return FakeRun()
            def log_params(self, p): pass
            def log_metrics(self, m): recorded.update(m)
            def log_metric(self, k, v): pass
            def set_tags(self, t): pass

        monkeypatch.setattr(settings, "MLFLOW_ENABLED", True)
        monkeypatch.setattr(tracking, "_mlflow", FakeMlflow())

        tracking.log_workflow_run("wf", "q", ["amazon"], {"cleaned_data": []}, {})

        assert recorded["live_data_ratio"] == 0.0
