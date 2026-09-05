"""MLflow experiment tracking for agent workflow runs.

Each workflow execution is logged as one MLflow run: the query and sources
as parameters, and the things worth comparing between runs as metrics -
how much data was collected, how much of it was live rather than
synthetic, sentiment distribution, per-agent latency, and how many
revisions the reviewer demanded.

Tracking is strictly best-effort. MLflow is a reporting sink, not part of
the workflow's contract, so every call here swallows its own errors: a
missing or unreachable tracking server must never fail a workflow that
otherwise succeeded.

``MLFLOW_TRACKING_URI`` defaults to a local ``./mlruns`` directory, so this
works with no server running; the Docker stack points it at the MLflow
container instead.
"""

from __future__ import annotations

from typing import Any

from app.config import settings
from app.core.logging import get_logger

logger = get_logger(__name__)

EXPERIMENT_NAME = "agentflow-workflows"

# MLflow imports pull in a large dependency tree, so it is loaded on first
# use rather than at application startup.
_mlflow: Any = None
_init_failed = False


def _get_mlflow() -> Any:
    """Import and configure MLflow once, or return None if unavailable."""
    global _mlflow, _init_failed

    if _mlflow is not None or _init_failed:
        return _mlflow

    if not settings.MLFLOW_ENABLED:
        _init_failed = True
        return None

    try:
        import mlflow

        mlflow.set_tracking_uri(settings.MLFLOW_TRACKING_URI)
        mlflow.set_experiment(EXPERIMENT_NAME)
        _mlflow = mlflow
        logger.info(f"MLflow tracking enabled at {settings.MLFLOW_TRACKING_URI}")
        return _mlflow
    except Exception as e:
        _init_failed = True
        logger.warning(f"MLflow tracking unavailable, continuing without it: {e}")
        return None


def _sanitize(value: Any) -> str:
    """MLflow parameters must be short strings."""
    text = str(value)
    return text[:250]


def log_workflow_run(
    workflow_id: Any,
    query: str,
    sources: list[str],
    final_state: dict,
    index_stats: dict | None = None,
) -> None:
    """Record one completed workflow as an MLflow run.

    Never raises: tracking failures are logged and ignored.
    """
    mlflow = _get_mlflow()
    if mlflow is None:
        return

    try:
        cleaned = final_state.get("cleaned_data", []) or []
        trends = final_state.get("trends", {}) or {}
        agent_logs = final_state.get("agent_logs", []) or []

        live = sum(
            1 for item in cleaned
            if not (item.get("metadata") or {}).get("is_mock", False)
        )

        with mlflow.start_run(run_name=f"workflow-{workflow_id}"):
            mlflow.log_params({
                "workflow_id": _sanitize(workflow_id),
                "query": _sanitize(query),
                "sources": _sanitize(",".join(sources)),
                "embedding_model": _sanitize(
                    (index_stats or {}).get("embedding_model", "none")
                ),
            })

            metrics: dict[str, float] = {
                "items_collected": float(len(cleaned)),
                "items_live": float(live),
                "items_mock": float(len(cleaned) - live),
                # The share of the corpus that is real data is the single
                # most important quality signal for a run.
                "live_data_ratio": round(live / len(cleaned), 4) if cleaned else 0.0,
                "topics_found": float(len(final_state.get("topics", []) or [])),
                "keywords_found": float(len(final_state.get("keywords", []) or [])),
                "revision_count": float(final_state.get("revision_count", 0) or 0),
                "chunks_indexed": float((index_stats or {}).get("chunks", 0)),
            }

            if "average_sentiment" in trends:
                metrics["average_sentiment"] = float(trends["average_sentiment"])
            if "overall_positive_percentage" in trends:
                metrics["positive_percentage"] = float(trends["overall_positive_percentage"])

            # Per-agent latency makes a slow node obvious across runs.
            total_ms = 0
            for entry in agent_logs:
                name = entry.get("agent_name")
                elapsed = entry.get("execution_time_ms")
                if name and isinstance(elapsed, (int, float)):
                    metrics[f"agent_{name}_ms"] = float(elapsed)
                    total_ms += elapsed
            metrics["total_agent_ms"] = float(total_ms)

            mlflow.log_metrics(metrics)

            review = final_state.get("review_feedback", {}) or {}
            if isinstance(review.get("quality_score"), (int, float)):
                mlflow.log_metric("report_quality_score", float(review["quality_score"]))

            mlflow.set_tags({
                "status": _sanitize(final_state.get("status", "unknown")),
                "approved": _sanitize(review.get("approved", False)),
            })

        logger.info(f"Logged workflow {workflow_id} to MLflow")

    except Exception as e:
        logger.warning(f"MLflow logging failed for workflow {workflow_id}: {e}")
