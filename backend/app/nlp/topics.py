"""Topic modelling with NMF over a TF-IDF matrix.

Non-negative Matrix Factorization decomposes the document-term matrix into
topic-term and document-topic matrices. Because every factor is
constrained to be non-negative, each topic reads as an additive set of
terms rather than a mix of positive and negative contributions - which is
what makes the output interpretable.

NMF is preferred over LDA here because the corpus is short, noisy user
text (comments and reviews), where LDA's document-length assumptions tend
to produce mush.

Each topic reports how many documents it dominates, so a topic covering
three comments is not presented as equal to one covering three hundred.
"""

from sklearn.decomposition import NMF
from sklearn.feature_extraction.text import TfidfVectorizer

from app.core.logging import get_logger
from app.nlp.sentiment import SentimentAnalyzer

logger = get_logger(__name__)

# NMF needs enough documents for a decomposition to mean anything.
MIN_DOCUMENTS = 5
TERMS_PER_TOPIC = 8


class TopicExtractor:
    """Discovers latent themes across a corpus of scraped text."""

    def __init__(self):
        self.sentiment = SentimentAnalyzer()

    def extract_topics(self, texts: list[str], n_topics: int = 5) -> list[dict]:
        """Return up to ``n_topics`` themes, ranked by document coverage."""
        documents = [t for t in (texts or []) if t and t.strip()]

        if len(documents) < MIN_DOCUMENTS:
            logger.info(
                f"Only {len(documents)} documents; too few for topic modelling"
            )
            return [{
                "topic_id": 0,
                "label": "insufficient data",
                "keywords": [],
                "weight": 1.0,
                "document_count": len(documents),
                "sentiment": 0.0,
            }]

        try:
            return self._nmf_topics(documents, n_topics)
        except Exception as e:
            logger.error(f"Topic modelling failed: {e}")
            return [{
                "topic_id": 0,
                "label": "topic extraction unavailable",
                "keywords": [],
                "weight": 1.0,
                "document_count": len(documents),
                "sentiment": 0.0,
            }]

    def _nmf_topics(self, documents: list[str], n_topics: int) -> list[dict]:
        n_docs = len(documents)

        vectorizer = TfidfVectorizer(
            ngram_range=(1, 2),
            stop_words="english",
            min_df=2 if n_docs >= 10 else 1,
            max_df=0.85 if n_docs >= 10 else 1.0,
            max_features=1000,
            token_pattern=r"(?u)\b[a-zA-Z][a-zA-Z-]{1,}[a-zA-Z]\b",
        )
        matrix = vectorizer.fit_transform(documents)
        terms = vectorizer.get_feature_names_out()

        if matrix.shape[1] == 0:
            raise ValueError("no usable vocabulary after filtering")

        # n_components cannot exceed either dimension of the matrix.
        n_components = max(2, min(n_topics, n_docs // 3, matrix.shape[1]))

        model = NMF(
            n_components=n_components,
            init="nndsvd",        # deterministic seeding
            random_state=42,      # reproducible runs
            max_iter=400,
        )
        doc_topics = model.fit_transform(matrix)

        # Assign each document to the topic it scores highest on.
        assignments = doc_topics.argmax(axis=1)

        topics: list[dict] = []
        for topic_id, term_weights in enumerate(model.components_):
            top_indices = term_weights.argsort()[::-1][:TERMS_PER_TOPIC]
            keywords = [str(terms[i]) for i in top_indices if term_weights[i] > 0]
            if not keywords:
                continue

            member_docs = [
                documents[i] for i, t in enumerate(assignments) if t == topic_id
            ]
            doc_count = len(member_docs)

            topics.append({
                "topic_id": int(topic_id),
                # A readable handle for charts and report sections.
                "label": " / ".join(keywords[:2]),
                "keywords": keywords,
                "weight": round(doc_count / n_docs, 4),
                "document_count": doc_count,
                "sentiment": self._topic_sentiment(member_docs),
            })

        # Most-covered themes first.
        topics.sort(key=lambda t: t["document_count"], reverse=True)
        logger.info(f"Extracted {len(topics)} topics from {n_docs} documents")
        return topics

    def _topic_sentiment(self, documents: list[str], sample_cap: int = 40) -> float:
        """Average sentiment of the documents belonging to a topic."""
        sample = documents[:sample_cap]
        if not sample:
            return 0.0
        total = sum(self.sentiment.score_only(doc) for doc in sample)
        return round(total / len(sample), 4)
