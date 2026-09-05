"""Trend analysis over time-binned sentiment.

The previous implementation sorted by date and then split the list in
half by *position*, which measures nothing about time - 200 comments from
one busy week and 3 from the following year would split straight down the
middle of the busy week.

This version bins items into real calendar periods (weekly for short
ranges, monthly otherwise), computes sentiment per period, and fits a
least-squares line through those period averages. The slope is the trend;
its magnitude says how fast sentiment is moving.
"""

from collections import defaultdict
from datetime import datetime
from typing import Any

import numpy as np

from app.core.logging import get_logger

logger = get_logger(__name__)

# Date formats the scrapers emit.
_DATE_FORMATS = ("%Y-%m-%d", "%Y-%m-%dT%H:%M:%SZ", "%Y-%m-%dT%H:%M:%S", "%Y/%m/%d")

# Slope of average compound sentiment per period.
_TREND_THRESHOLD = 0.02

# Below this many periods a slope is not meaningful.
_MIN_PERIODS_FOR_TREND = 3

# Switch from weekly to monthly bins past this span.
_WEEKLY_MAX_DAYS = 60


class TrendAnalyzer:
    """Aggregates sentiment into a time series and detects its direction."""

    def analyze_trends(self, data: list[dict[str, Any]]) -> dict[str, Any]:
        """Build a sentiment timeline from scraped items.

        Each item is expected to carry ``metadata.date`` and the
        ``sentiment_label`` / ``sentiment_score`` set by the NLP agent.
        """
        if not data:
            return {"status": "insufficient_data", "total_analyzed": 0}

        try:
            dated, undated = self._parse_dates(data)

            counts = {"POSITIVE": 0, "NEGATIVE": 0, "NEUTRAL": 0}
            for item in data:
                label = (item.get("sentiment_label") or "NEUTRAL").upper()
                counts[label] = counts.get(label, 0) + 1

            total = len(data)
            scores = [
                item.get("sentiment_score", 0.0) or 0.0
                for item in data
                if isinstance(item.get("sentiment_score"), (int, float))
            ]
            average_sentiment = round(float(np.mean(scores)), 4) if scores else 0.0

            timeline = self._build_timeline(dated)
            direction, slope = self._trend_direction(timeline)

            return {
                "total_analyzed": total,
                "dated_items": len(dated),
                "undated_items": undated,
                "positive_count": counts["POSITIVE"],
                "negative_count": counts["NEGATIVE"],
                "neutral_count": counts["NEUTRAL"],
                "overall_positive_percentage": round(
                    (counts["POSITIVE"] / total) * 100, 2
                ) if total else 0.0,
                "overall_negative_percentage": round(
                    (counts["NEGATIVE"] / total) * 100, 2
                ) if total else 0.0,
                "average_sentiment": average_sentiment,
                "trend_direction": direction,
                "trend_slope": slope,
                "timeline": timeline,
                "period": self._period_label(dated),
            }

        except Exception as e:
            logger.error(f"Error analyzing trends: {e}")
            return {"status": "error", "message": str(e), "total_analyzed": len(data)}

    # ------------------------------------------------------------------ #
    #  Helpers
    # ------------------------------------------------------------------ #

    @staticmethod
    def _parse_date(raw: str) -> datetime | None:
        if not raw:
            return None
        for fmt in _DATE_FORMATS:
            try:
                return datetime.strptime(raw, fmt)
            except (ValueError, TypeError):
                continue
        return None

    def _parse_dates(self, data: list[dict]) -> tuple[list[tuple], int]:
        """Split items into (datetime, item) pairs and a count of undated ones."""
        dated: list[tuple[datetime, dict]] = []
        undated = 0

        for item in data:
            metadata = item.get("metadata") or {}
            parsed = self._parse_date(metadata.get("date"))
            if parsed is None:
                undated += 1
            else:
                dated.append((parsed, item))

        dated.sort(key=lambda pair: pair[0])
        return dated, undated

    def _bin_key(self, moment: datetime, weekly: bool) -> str:
        if weekly:
            year, week, _ = moment.isocalendar()
            return f"{year}-W{week:02d}"
        return moment.strftime("%Y-%m")

    def _use_weekly_bins(self, dated: list[tuple]) -> bool:
        if len(dated) < 2:
            return False
        span = (dated[-1][0] - dated[0][0]).days
        return span <= _WEEKLY_MAX_DAYS

    def _period_label(self, dated: list[tuple]) -> str:
        if not dated:
            return "none"
        return "weekly" if self._use_weekly_bins(dated) else "monthly"

    def _build_timeline(self, dated: list[tuple]) -> list[dict]:
        """Aggregate items into calendar buckets."""
        if not dated:
            return []

        weekly = self._use_weekly_bins(dated)
        buckets: dict[str, list[dict]] = defaultdict(list)

        for moment, item in dated:
            buckets[self._bin_key(moment, weekly)].append(item)

        timeline = []
        for period in sorted(buckets):
            items = buckets[period]
            scores = [
                item.get("sentiment_score", 0.0) or 0.0
                for item in items
                if isinstance(item.get("sentiment_score"), (int, float))
            ]

            timeline.append({
                "date": period,
                "volume": len(items),
                "positive": sum(
                    1 for i in items
                    if (i.get("sentiment_label") or "").upper() == "POSITIVE"
                ),
                "negative": sum(
                    1 for i in items
                    if (i.get("sentiment_label") or "").upper() == "NEGATIVE"
                ),
                "neutral": sum(
                    1 for i in items
                    if (i.get("sentiment_label") or "NEUTRAL").upper() == "NEUTRAL"
                ),
                "average_sentiment": round(float(np.mean(scores)), 4) if scores else 0.0,
            })

        return timeline

    def _trend_direction(self, timeline: list[dict]) -> tuple[str, float]:
        """Least-squares slope of average sentiment across periods."""
        if len(timeline) < _MIN_PERIODS_FOR_TREND:
            return "INSUFFICIENT_HISTORY", 0.0

        x = np.arange(len(timeline), dtype=float)
        y = np.array([point["average_sentiment"] for point in timeline], dtype=float)

        try:
            slope = float(np.polyfit(x, y, 1)[0])
        except Exception as e:
            logger.warning(f"Could not fit trend line: {e}")
            return "STABLE", 0.0

        slope = round(slope, 5)
        if slope > _TREND_THRESHOLD:
            return "IMPROVING", slope
        if slope < -_TREND_THRESHOLD:
            return "DECLINING", slope
        return "STABLE", slope
