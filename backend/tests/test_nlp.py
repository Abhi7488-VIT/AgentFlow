"""Tests for the NLP layer: sentiment, keywords, topics, and trends.

All offline - VADER, TF-IDF, and NMF need no network and no model download.
"""

import pytest

from app.nlp.keywords import KeywordExtractor
from app.nlp.sentiment import SentimentAnalyzer
from app.nlp.topics import TopicExtractor
from app.nlp.trends import TrendAnalyzer

CORPUS = [
    ("2024-01-05", "The battery life is excellent, lasts me two full days."),
    ("2024-01-12", "Battery life is amazing. Best I have owned."),
    ("2024-01-20", "Noise cancelling is superb on flights, blocks engine noise."),
    ("2024-02-02", "The noise cancelling works great in the office too."),
    ("2024-02-14", "Build quality feels cheap, lots of creaky plastic."),
    ("2024-02-20", "Build quality is disappointing for this price point."),
    ("2024-03-01", "Battery died after two months, terrible quality control."),
    ("2024-03-10", "Customer support was awful when my unit broke."),
    ("2024-03-15", "The touch controls are unreliable and frustrating."),
    ("2024-03-22", "Mine broke within weeks. Build quality is a serious problem."),
    ("2024-04-02", "Terrible experience overall, would not buy again."),
    ("2024-04-11", "Battery drains fast now, very disappointing."),
]

TEXTS = [text for _, text in CORPUS]


class TestSentiment:
    """VADER must handle the linguistics a keyword counter cannot."""

    @pytest.mark.parametrize("text,expected", [
        ("This is not good at all.", "NEGATIVE"),          # negation
        ("Not bad, actually quite impressive.", "POSITIVE"),  # negated negative
        ("I don't love it.", "NEGATIVE"),                  # negated positive
        ("ABSOLUTELY AMAZING!!!", "POSITIVE"),             # caps + emphasis
        ("The product exists.", "NEUTRAL"),                # no valence
    ])
    def test_classification(self, text, expected):
        assert SentimentAnalyzer().analyze_one(text)["label"] == expected

    def test_score_is_compound_in_range(self):
        for text in TEXTS:
            result = SentimentAnalyzer().analyze_one(text)
            assert -1.0 <= result["score"] <= 1.0
            assert 0.0 <= result["confidence"] <= 1.0

    def test_emphasis_increases_intensity(self):
        analyzer = SentimentAnalyzer()
        plain = analyzer.analyze_one("This is good.")["score"]
        loud = analyzer.analyze_one("This is GOOD!!!")["score"]
        assert loud > plain

    def test_proportions_are_reported(self):
        result = SentimentAnalyzer().analyze_one("Great sound but terrible battery.")
        assert result["positive"] > 0
        assert result["negative"] > 0

    def test_empty_and_blank_text(self):
        for text in ("", "   ", None):
            result = SentimentAnalyzer().analyze_one(text)
            assert result["label"] == "NEUTRAL"
            assert result["score"] == 0.0

    @pytest.mark.asyncio
    async def test_batch_returns_one_result_per_input(self):
        results = await SentimentAnalyzer().analyze(TEXTS)
        assert len(results) == len(TEXTS)

    @pytest.mark.asyncio
    async def test_empty_batch(self):
        assert await SentimentAnalyzer().analyze([]) == []


class TestKeywords:
    def test_extracts_multiword_phrases(self):
        terms = [k["keyword"] for k in KeywordExtractor().extract_keywords(TEXTS, top_n=10)]
        assert any(" " in term for term in terms), "bigrams must be extracted"

    def test_finds_dominant_theme(self):
        terms = [k["keyword"] for k in KeywordExtractor().extract_keywords(TEXTS, top_n=10)]
        assert any("battery" in term for term in terms)

    def test_keyword_carries_its_own_sentiment(self):
        keywords = KeywordExtractor().extract_keywords(TEXTS, top_n=15)
        build = next((k for k in keywords if "build" in k["keyword"]), None)

        assert build is not None
        # The corpus only complains about build quality.
        assert build["sentiment"] < 0

    def test_result_shape(self):
        for entry in KeywordExtractor().extract_keywords(TEXTS, top_n=5):
            assert set(entry) == {"keyword", "score", "frequency", "sentiment"}
            assert entry["frequency"] >= 1

    def test_respects_top_n(self):
        assert len(KeywordExtractor().extract_keywords(TEXTS, top_n=3)) <= 3

    def test_single_document_corpus(self):
        """min_df must adapt or a one-document corpus yields nothing."""
        assert KeywordExtractor().extract_keywords(["battery life is great"], top_n=5)

    def test_empty_corpus(self):
        assert KeywordExtractor().extract_keywords([]) == []
        assert KeywordExtractor().extract_keywords(["", "   "]) == []


class TestTopics:
    def test_topics_contain_real_terms(self):
        topics = TopicExtractor().extract_topics(TEXTS, n_topics=4)

        assert topics
        for topic in topics:
            assert topic["keywords"], "every topic needs terms"
            assert not any("keyword_" in k for k in topic["keywords"])

    def test_every_document_is_assigned(self):
        topics = TopicExtractor().extract_topics(TEXTS, n_topics=4)
        assert sum(t["document_count"] for t in topics) == len(TEXTS)

    def test_topics_ranked_by_coverage(self):
        topics = TopicExtractor().extract_topics(TEXTS, n_topics=4)
        counts = [t["document_count"] for t in topics]
        assert counts == sorted(counts, reverse=True)

    def test_weights_are_document_shares(self):
        topics = TopicExtractor().extract_topics(TEXTS, n_topics=4)
        assert abs(sum(t["weight"] for t in topics) - 1.0) < 0.01

    def test_deterministic_across_runs(self):
        """Seeded NMF must give the same answer twice."""
        first = TopicExtractor().extract_topics(TEXTS, n_topics=3)
        second = TopicExtractor().extract_topics(TEXTS, n_topics=3)
        assert [t["keywords"] for t in first] == [t["keywords"] for t in second]

    def test_too_few_documents_says_so(self):
        result = TopicExtractor().extract_topics(["only one"], n_topics=5)
        assert result[0]["label"] == "insufficient data"

    def test_empty_corpus(self):
        assert TopicExtractor().extract_topics([])[0]["label"] == "insufficient data"


class TestTrends:
    @staticmethod
    def _items():
        analyzer = SentimentAnalyzer()
        items = []
        for date, text in CORPUS:
            scored = analyzer.analyze_one(text)
            items.append({
                "content": text,
                "metadata": {"date": date},
                "sentiment_label": scored["label"],
                "sentiment_score": scored["score"],
            })
        return items

    def test_bins_by_calendar_month(self):
        result = TrendAnalyzer().analyze_trends(self._items())
        # The corpus spans January to April 2024.
        assert [p["date"] for p in result["timeline"]] == [
            "2024-01", "2024-02", "2024-03", "2024-04"
        ]

    def test_detects_decline(self):
        """Corpus is positive early and negative late."""
        result = TrendAnalyzer().analyze_trends(self._items())
        assert result["trend_direction"] == "DECLINING"
        assert result["trend_slope"] < 0

    def test_volume_matches_input(self):
        result = TrendAnalyzer().analyze_trends(self._items())
        assert sum(p["volume"] for p in result["timeline"]) == len(CORPUS)
        assert result["total_analyzed"] == len(CORPUS)

    def test_short_range_uses_weekly_bins(self):
        items = [
            {"metadata": {"date": f"2024-01-{day:02d}"},
             "sentiment_label": "POSITIVE", "sentiment_score": 0.5}
            for day in (1, 3, 9, 11, 17, 19)
        ]
        assert TrendAnalyzer().analyze_trends(items)["period"] == "weekly"

    def test_youtube_iso_timestamps_parse(self):
        items = [
            {"metadata": {"date": "2024-01-15T10:30:00Z"},
             "sentiment_label": "POSITIVE", "sentiment_score": 0.5}
        ]
        assert TrendAnalyzer().analyze_trends(items)["dated_items"] == 1

    def test_undated_items_are_counted_not_dropped(self):
        items = [
            {"metadata": {}, "sentiment_label": "POSITIVE", "sentiment_score": 0.5},
            {"metadata": {"date": "nonsense"}, "sentiment_label": "NEGATIVE",
             "sentiment_score": -0.5},
        ]
        result = TrendAnalyzer().analyze_trends(items)

        assert result["undated_items"] == 2
        assert result["total_analyzed"] == 2
        assert result["timeline"] == []

    def test_too_few_periods_for_a_trend(self):
        items = [
            {"metadata": {"date": "2024-01-05"},
             "sentiment_label": "POSITIVE", "sentiment_score": 0.5}
        ]
        assert TrendAnalyzer().analyze_trends(items)["trend_direction"] == "INSUFFICIENT_HISTORY"

    def test_empty_input(self):
        assert TrendAnalyzer().analyze_trends([])["status"] == "insufficient_data"


class TestLanguageFiltering:
    def test_english_is_kept(self):
        from app.agents.cleaning_agent import is_english
        assert is_english("This product has excellent battery life and clear sound.")

    def test_non_english_is_rejected(self):
        from app.agents.cleaning_agent import is_english
        assert not is_english(
            "Este producto tiene una excelente duracion de bateria y buen sonido."
        )

    def test_short_text_is_kept_rather_than_guessed(self):
        from app.agents.cleaning_agent import is_english
        assert is_english("Battery died.")

    def test_undetectable_text_is_kept(self):
        from app.agents.cleaning_agent import is_english
        assert is_english("12345 !!! ????? 67890 :::: 11111")

    def test_empty_text_is_rejected(self):
        from app.agents.cleaning_agent import is_english
        assert not is_english("")
