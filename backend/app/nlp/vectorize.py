"""TF-IDF and NMF in plain numpy.

scikit-learn was only used for a TfidfVectorizer and an NMF, but importing
it costs over 100 MB of RAM - a fifth of the 512 MB hosting instance. This
module reimplements exactly the behaviour the NLP agents relied on:

- sklearn's tokenisation (lowercase, regex token pattern), English stop
  words removed before n-grams are formed, document-frequency pruning,
  ``max_features`` by corpus frequency, optional sublinear tf, smooth idf
  and l2 row normalisation;
- NMF with NNDSVD initialisation and the coordinate-descent solver
  (Frobenius loss, no regularisation), the same defaults sklearn uses.

Corpora here are at most a few thousand short documents and the vocabulary
is capped, so dense matrices are small enough and keep the code simple.
"""

import re
from collections import Counter

import numpy as np

# scikit-learn's ENGLISH_STOP_WORDS, copied verbatim.
ENGLISH_STOP_WORDS = frozenset({
    "a", "about", "above", "across", "after", "afterwards", "again", "against",
    "all", "almost", "alone", "along", "already", "also", "although", "always",
    "am", "among", "amongst", "amoungst", "amount", "an", "and", "another",
    "any", "anyhow", "anyone", "anything", "anyway", "anywhere", "are",
    "around", "as", "at", "back", "be", "became", "because", "become",
    "becomes", "becoming", "been", "before", "beforehand", "behind", "being",
    "below", "beside", "besides", "between", "beyond", "bill", "both",
    "bottom", "but", "by", "call", "can", "cannot", "cant", "co", "con",
    "could", "couldnt", "cry", "de", "describe", "detail", "do", "done",
    "down", "due", "during", "each", "eg", "eight", "either", "eleven", "else",
    "elsewhere", "empty", "enough", "etc", "even", "ever", "every", "everyone",
    "everything", "everywhere", "except", "few", "fifteen", "fifty", "fill",
    "find", "fire", "first", "five", "for", "former", "formerly", "forty",
    "found", "four", "from", "front", "full", "further", "get", "give", "go",
    "had", "has", "hasnt", "have", "he", "hence", "her", "here", "hereafter",
    "hereby", "herein", "hereupon", "hers", "herself", "him", "himself", "his",
    "how", "however", "hundred", "i", "ie", "if", "in", "inc", "indeed",
    "interest", "into", "is", "it", "its", "itself", "keep", "last", "latter",
    "latterly", "least", "less", "ltd", "made", "many", "may", "me",
    "meanwhile", "might", "mill", "mine", "more", "moreover", "most", "mostly",
    "move", "much", "must", "my", "myself", "name", "namely", "neither",
    "never", "nevertheless", "next", "nine", "no", "nobody", "none", "noone",
    "nor", "not", "nothing", "now", "nowhere", "of", "off", "often", "on",
    "once", "one", "only", "onto", "or", "other", "others", "otherwise", "our",
    "ours", "ourselves", "out", "over", "own", "part", "per", "perhaps",
    "please", "put", "rather", "re", "same", "see", "seem", "seemed",
    "seeming", "seems", "serious", "several", "she", "should", "show", "side",
    "since", "sincere", "six", "sixty", "so", "some", "somehow", "someone",
    "something", "sometime", "sometimes", "somewhere", "still", "such",
    "system", "take", "ten", "than", "that", "the", "their", "them",
    "themselves", "then", "thence", "there", "thereafter", "thereby",
    "therefore", "therein", "thereupon", "these", "they", "thick", "thin",
    "third", "this", "those", "though", "three", "through", "throughout",
    "thru", "thus", "to", "together", "too", "top", "toward", "towards",
    "twelve", "twenty", "two", "un", "under", "until", "up", "upon", "us",
    "very", "via", "was", "we", "well", "were", "what", "whatever", "when",
    "whence", "whenever", "where", "whereafter", "whereas", "whereby",
    "wherein", "whereupon", "wherever", "whether", "which", "while", "whither",
    "who", "whoever", "whole", "whom", "whose", "why", "will", "with",
    "within", "without", "would", "yet", "you", "your", "yours", "yourself",
    "yourselves",
})


class TfidfVectorizer:
    """Subset of ``sklearn.feature_extraction.text.TfidfVectorizer``."""

    def __init__(
        self,
        ngram_range: tuple[int, int] = (1, 1),
        stop_words: str | None = None,
        min_df: int | float = 1,
        max_df: int | float = 1.0,
        max_features: int | None = None,
        sublinear_tf: bool = False,
        token_pattern: str = r"(?u)\b\w\w+\b",
    ):
        self.ngram_range = ngram_range
        self.stop_words = ENGLISH_STOP_WORDS if stop_words == "english" else frozenset()
        self.min_df = min_df
        self.max_df = max_df
        self.max_features = max_features
        self.sublinear_tf = sublinear_tf
        self._token_re = re.compile(token_pattern)
        self.vocabulary_: dict[str, int] = {}

    def _analyze(self, doc: str) -> list[str]:
        tokens = [t for t in self._token_re.findall(doc.lower())
                  if t not in self.stop_words]
        lo, hi = self.ngram_range
        grams: list[str] = []
        for n in range(lo, hi + 1):
            grams.extend(" ".join(tokens[i:i + n]) for i in range(len(tokens) - n + 1))
        return grams

    def fit_transform(self, documents: list[str]) -> np.ndarray:
        counts = [Counter(self._analyze(doc)) for doc in documents]
        n_docs = len(documents)

        # Vocabulary is alphabetical, as in sklearn.
        terms = sorted(set().union(*counts))
        if not terms:
            raise ValueError("empty vocabulary; perhaps the documents only contain stop words")
        index = {t: i for i, t in enumerate(terms)}

        tf = np.zeros((n_docs, len(terms)), dtype=np.float64)
        for row, counter in enumerate(counts):
            for term, c in counter.items():
                tf[row, index[term]] = c

        # Document-frequency pruning (float = proportion, int = absolute).
        df = np.count_nonzero(tf, axis=0)
        max_doc = self.max_df if isinstance(self.max_df, int) else self.max_df * n_docs
        min_doc = self.min_df if isinstance(self.min_df, int) else self.min_df * n_docs
        if max_doc < min_doc:
            raise ValueError("max_df corresponds to < documents than min_df")
        keep = np.flatnonzero((df >= min_doc) & (df <= max_doc))
        if self.max_features is not None and len(keep) > self.max_features:
            # Integer counts and the default sort reproduce sklearn's
            # tie-breaking between equally frequent terms.
            corpus_tf = tf[:, keep].sum(axis=0).astype(np.int64)
            top = (-corpus_tf).argsort()[: self.max_features]
            keep = np.sort(keep[top])
        if len(keep) == 0:
            raise ValueError("After pruning, no terms remain. Try a lower min_df or a higher max_df.")

        tf, df = tf[:, keep], df[keep]
        self.vocabulary_ = {terms[i]: j for j, i in enumerate(keep)}
        self._feature_names = np.array([terms[i] for i in keep], dtype=object)

        if self.sublinear_tf:
            nz = tf > 0
            tf[nz] = np.log(tf[nz]) + 1.0
        idf = np.log((1.0 + n_docs) / (1.0 + df)) + 1.0
        X = tf * idf
        norms = np.linalg.norm(X, axis=1, keepdims=True)
        norms[norms == 0] = 1.0
        return X / norms

    def get_feature_names_out(self) -> np.ndarray:
        return self._feature_names


class NMF:
    """Subset of ``sklearn.decomposition.NMF``: nndsvd init + coordinate descent."""

    def __init__(self, n_components: int, max_iter: int = 200, tol: float = 1e-4):
        self.n_components = n_components
        self.max_iter = max_iter
        self.tol = tol
        self.components_: np.ndarray | None = None

    def _nndsvd(self, X: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
        k = self.n_components
        U, S, V = np.linalg.svd(X, full_matrices=False)
        U, S, V = U[:, :k], S[:k], V[:k]

        W = np.zeros((X.shape[0], k))
        H = np.zeros((k, X.shape[1]))
        W[:, 0] = np.sqrt(S[0]) * np.abs(U[:, 0])
        H[0, :] = np.sqrt(S[0]) * np.abs(V[0, :])
        for j in range(1, k):
            x, y = U[:, j], V[j, :]
            x_p, y_p = np.maximum(x, 0), np.maximum(y, 0)
            x_n, y_n = np.abs(np.minimum(x, 0)), np.abs(np.minimum(y, 0))
            x_p_nrm, y_p_nrm = np.linalg.norm(x_p), np.linalg.norm(y_p)
            x_n_nrm, y_n_nrm = np.linalg.norm(x_n), np.linalg.norm(y_n)
            m_p, m_n = x_p_nrm * y_p_nrm, x_n_nrm * y_n_nrm
            # Keep whichever sign half of the singular pair carries more mass.
            if m_p > m_n:
                u, v, sigma = x_p / x_p_nrm, y_p / y_p_nrm, m_p
            else:
                u, v, sigma = x_n / x_n_nrm, y_n / y_n_nrm, m_n
            lbd = np.sqrt(S[j] * sigma)
            W[:, j] = lbd * u
            H[j, :] = lbd * v

        eps = 1e-6
        W[W < eps] = 0
        H[H < eps] = 0
        return W, H

    @staticmethod
    def _update(X: np.ndarray, W: np.ndarray, Ht: np.ndarray) -> float:
        """One coordinate-descent sweep over W's columns; returns the violation.

        Rows of W are independent given Ht, so sklearn's per-element loop
        vectorises exactly across rows.
        """
        HHt = Ht.T @ Ht
        XHt = X @ Ht
        violation = 0.0
        for t in range(W.shape[1]):
            grad = W @ HHt[t] - XHt[:, t]
            pg = np.where(W[:, t] == 0, np.minimum(grad, 0.0), grad)
            violation += float(np.abs(pg).sum())
            hess = HHt[t, t]
            if hess != 0:
                W[:, t] = np.maximum(W[:, t] - grad / hess, 0.0)
        return violation

    def fit_transform(self, X: np.ndarray) -> np.ndarray:
        X = np.asarray(X, dtype=np.float64)
        W, H = self._nndsvd(X)
        Ht = np.ascontiguousarray(H.T)

        violation_init = None
        for _ in range(self.max_iter):
            violation = self._update(X, W, Ht)
            violation += self._update(X.T, Ht, W)
            if violation_init is None:
                violation_init = violation
            if violation_init == 0 or violation / violation_init <= self.tol:
                break

        self.components_ = Ht.T
        return W
