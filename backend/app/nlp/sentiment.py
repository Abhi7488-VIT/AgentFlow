"""Sentiment analysis using VADER.

VADER (Valence Aware Dictionary and sEntiment Reasoner) is a lexicon and
rule-based analyser tuned for exactly the kind of text this project
collects - product reviews, Reddit comments, YouTube comments. Unlike a
bag-of-words count it understands:

    * negation           "not good"          -> negative
    * intensifiers       "very good"         -> stronger positive
    * contrast           "good but pricey"   -> weights the second clause
    * emphasis           "GREAT!!!"          -> stronger positive
    * emoji and slang    ":)", "meh"

It needs no model download and no torch, which keeps the container small
enough to run on a memory-constrained host.

The ``score`` returned is VADER's ``compound`` value in [-1, 1], so scores
can be averaged directly to get net sentiment for a corpus.
"""

import asyncio

from vaderSentiment.vaderSentiment import SentimentIntensityAnalyzer

from app.core.logging import get_logger

logger = get_logger(__name__)

# VADER's documented thresholds for classifying the compound score.
POSITIVE_THRESHOLD = 0.05
NEGATIVE_THRESHOLD = -0.05

# Above this many texts, analysis moves off the event loop.
_THREAD_THRESHOLD = 200


class SentimentAnalyzer:
    """Singleton VADER analyser. The lexicon is loaded once and reused."""

    _instance = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super(SentimentAnalyzer, cls).__new__(cls)
            cls._instance.analyzer = SentimentIntensityAnalyzer()
            logger.info("SentimentAnalyzer ready (VADER lexicon)")
        return cls._instance

    async def analyze(self, texts: list[str]) -> list[dict]:
        """Score every text. Always returns one result per input."""
        if not texts:
            return []

        if len(texts) > _THREAD_THRESHOLD:
            return await asyncio.to_thread(self._analyze_all, texts)
        return self._analyze_all(texts)

    def _analyze_all(self, texts: list[str]) -> list[dict]:
        return [self.analyze_one(text) for text in texts]

    def analyze_one(self, text: str) -> dict:
        """Score a single text.

        Returns the compound score plus the positive/neutral/negative
        proportions, so callers can show *why* something was classified
        the way it was rather than just a bare label.
        """
        if not text or not text.strip():
            return {
                "label": "NEUTRAL",
                "score": 0.0,
                "confidence": 0.0,
                "positive": 0.0,
                "neutral": 1.0,
                "negative": 0.0,
            }

        try:
            scores = self.analyzer.polarity_scores(text)
        except Exception as e:
            logger.error(f"Sentiment scoring failed: {e}")
            return {
                "label": "NEUTRAL", "score": 0.0, "confidence": 0.0,
                "positive": 0.0, "neutral": 1.0, "negative": 0.0,
            }

        compound = scores["compound"]

        if compound >= POSITIVE_THRESHOLD:
            label = "POSITIVE"
        elif compound <= NEGATIVE_THRESHOLD:
            label = "NEGATIVE"
        else:
            label = "NEUTRAL"

        return {
            "label": label,
            "score": round(compound, 4),
            # Distance from neutral: how strongly VADER committed.
            "confidence": round(abs(compound), 4),
            "positive": scores["pos"],
            "neutral": scores["neu"],
            "negative": scores["neg"],
        }

    def score_only(self, text: str) -> float:
        """Compound score alone - convenient for aggregation."""
        return self.analyze_one(text)["score"]
