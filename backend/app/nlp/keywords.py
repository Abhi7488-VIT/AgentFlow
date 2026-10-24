"""Keyword extraction using TF-IDF.

Raw frequency counting surfaces words that are common everywhere ("phone",
"product"). TF-IDF instead weights a term by how often it appears in a
document against how rare it is across the corpus, so what comes back is
what makes *this* corpus distinctive.

Bigrams are included because the useful phrases in review text are almost
always two words - "battery life", "build quality", "noise cancelling".
Summed TF-IDF systematically favours unigrams, though, because a single
word appears in more documents than any specific pairing of it. A share of
the results is therefore reserved for phrases, so they are ranked against
each other rather than against words they can never outscore.

Each keyword also carries the average sentiment of the documents that
mention it, which is what turns a word cloud into something actionable:
"battery life, 120 mentions, -0.4" says where the problem is.
"""

import re

from app.core.logging import get_logger
from app.nlp.sentiment import SentimentAnalyzer
from app.nlp.vectorize import TfidfVectorizer

logger = get_logger(__name__)

# Domain noise that is technically distinctive but analytically useless.
_EXTRA_STOP_WORDS = {
    "product", "item", "thing", "stuff", "amazon", "reddit", "youtube",
    "just", "really", "definitely", "actually", "literally", "basically",
    "got", "get", "getting", "buy", "bought", "buying", "purchase",
    "review", "reviews", "star", "stars", "www", "http", "https", "com",
    # Frequent but contentless in review prose.
    "like", "use", "used", "using", "way", "lot", "bit", "thing", "things",
    "make", "makes", "made", "one", "two", "know", "think", "want", "need",
    "say", "said", "see", "look", "come", "take", "going", "video",
}


class KeywordExtractor:
    """Extracts weighted keywords and phrases from a document corpus."""

    def __init__(self):
        self.sentiment = SentimentAnalyzer()

    def extract_keywords(self, texts: list[str], top_n: int = 20) -> list[dict]:
        """Return the ``top_n`` most distinctive terms across ``texts``."""
        documents = [t for t in (texts or []) if t and t.strip()]
        if not documents:
            return []

        try:
            return self._tfidf_extract(documents, top_n)
        except Exception as e:
            logger.error(f"TF-IDF extraction failed, falling back to counts: {e}")
            return self._frequency_extract(documents, top_n)

    def _tfidf_extract(self, documents: list[str], top_n: int) -> list[dict]:
        stop_words = list(_EXTRA_STOP_WORDS)

        # min_df/max_df must adapt: on a tiny corpus, "appears in >= 2 docs"
        # or "appears in < 80% of docs" can filter out every single term.
        n_docs = len(documents)
        min_df = 2 if n_docs >= 10 else 1
        max_df = 0.8 if n_docs >= 10 else 1.0

        vectorizer = TfidfVectorizer(
            ngram_range=(1, 2),          # unigrams + bigrams
            stop_words="english",
            min_df=min_df,
            max_df=max_df,
            max_features=2000,
            sublinear_tf=True,           # dampen runaway term counts
            # Must start and end with a letter, so "wh-1000xm5" does not
            # leak a dangling "wh-" token into the results.
            token_pattern=r"(?u)\b[a-zA-Z][a-zA-Z-]{1,}[a-zA-Z]\b",
        )

        matrix = vectorizer.fit_transform(documents)
        terms = vectorizer.get_feature_names_out()

        # Corpus-level weight for each term: summed TF-IDF across documents.
        weights = matrix.sum(axis=0)
        ranked = sorted(zip(terms, weights), key=lambda x: x[1], reverse=True)

        # Rank words and phrases separately so phrases are not crowded out.
        unigrams = [(t, w) for t, w in ranked
                    if " " not in t and not self._is_noise(t, stop_words)]
        phrases = [(t, w) for t, w in ranked
                   if " " in t and not self._is_noise(t, stop_words)]

        lowered = [d.lower() for d in documents]
        results: list[dict] = []

        # Phrases first, up to their reserved share of the output.
        phrase_quota = max(1, top_n // 3)
        covered: dict[str, int] = {}

        for term, weight in phrases[:phrase_quota]:
            entry = self._build_entry(term, weight, lowered)
            if entry is None:
                continue
            results.append(entry)
            # Remember how often each component word was seen inside a phrase.
            for word in term.split():
                covered[word] = max(covered.get(word, 0), entry["frequency"])

        # Then words, skipping any that never occur outside a chosen phrase.
        for term, weight in unigrams:
            if len(results) >= top_n:
                break

            entry = self._build_entry(term, weight, lowered)
            if entry is None:
                continue
            if entry["frequency"] <= covered.get(term, 0):
                continue  # redundant: "build" adds nothing over "build quality"

            results.append(entry)

        results.sort(key=lambda k: k["score"], reverse=True)
        return results[:top_n]

    def _build_entry(self, term: str, weight: float, lowered: list[str]) -> dict | None:
        """Assemble one keyword result, or None if the term matches nothing."""
        mentions = [doc for doc in lowered if term in doc]
        if not mentions:
            return None

        return {
            "keyword": term,
            "score": round(float(weight), 4),
            "frequency": len(mentions),
            "sentiment": self._mention_sentiment(mentions),
        }

    def _mention_sentiment(self, mentions: list[str], sample_cap: int = 40) -> float:
        """Average sentiment of the documents mentioning a term."""
        sample = mentions[:sample_cap]
        if not sample:
            return 0.0
        total = sum(self.sentiment.score_only(doc) for doc in sample)
        return round(total / len(sample), 4)

    @staticmethod
    def _is_noise(term: str, stop_words: list[str]) -> bool:
        """Drop terms that are noise even after vectorizer filtering."""
        parts = term.split()
        if any(part in stop_words for part in parts):
            return True
        if all(len(part) <= 2 for part in parts):
            return True
        if re.fullmatch(r"[\d\W_]+", term):
            return True
        return False

    def _frequency_extract(self, documents: list[str], top_n: int) -> list[dict]:
        """Plain word counts - only used if TF-IDF itself errors."""
        combined = " ".join(documents).lower()
        words = re.findall(r"\b[a-z][a-z-]{2,}\b", combined)

        counts: dict[str, int] = {}
        for word in words:
            if word not in _EXTRA_STOP_WORDS:
                counts[word] = counts.get(word, 0) + 1

        ranked = sorted(counts.items(), key=lambda x: x[1], reverse=True)
        lowered = [d.lower() for d in documents]

        return [
            {
                "keyword": word,
                "score": float(count),
                "frequency": count,
                "sentiment": self._mention_sentiment(
                    [d for d in lowered if word in d]
                ),
            }
            for word, count in ranked[:top_n]
        ]
