"""Embedding generation for RAG indexing and retrieval.

Uses Google's ``gemini-embedding-001`` model when a Gemini API key is
configured. When no key is present the generator returns an empty list,
which signals callers to let ChromaDB use its own built-in embedding
function instead of storing meaningless placeholder vectors.

Task types matter for retrieval quality: documents are embedded with
``retrieval_document`` and questions with ``retrieval_query``, so the two
land in the same vector space with the asymmetry the model expects.
"""

import asyncio
import math

import google.generativeai as genai

from app.config import settings
from app.core.logging import get_logger

logger = get_logger(__name__)

EMBEDDING_MODEL = "models/gemini-embedding-001"
EMBEDDING_DIM = 768  # model default is 3072; 768 keeps the index compact
CHROMA_DEFAULT_MODEL = "chromadb-default"

# Gemini caps how much can be embedded in one request.
_MAX_BATCH = 32
_MAX_CHARS = 8000
_MAX_ATTEMPTS = 3


def _normalize(vector) -> list[float]:
    """Scale a vector to unit length so cosine distance behaves."""
    values = [float(v) for v in vector]
    magnitude = math.sqrt(sum(v * v for v in values))
    if magnitude == 0:
        return values
    return [v / magnitude for v in values]


class EmbeddingGenerator:
    """Singleton wrapper around the Gemini embedding endpoint."""

    _instance = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super(EmbeddingGenerator, cls).__new__(cls)
            cls._instance._configured = False

            if settings.GEMINI_API_KEY:
                try:
                    genai.configure(api_key=settings.GEMINI_API_KEY)
                    cls._instance._configured = True
                    logger.info(f"EmbeddingGenerator ready ({EMBEDDING_MODEL}, {EMBEDDING_DIM}d)")
                except Exception as e:
                    logger.error(f"Failed to configure Gemini embeddings: {e}")
            else:
                logger.warning(
                    "No GEMINI_API_KEY set - ChromaDB's built-in embedding "
                    "function will be used instead"
                )
        return cls._instance

    @property
    def is_available(self) -> bool:
        """True when real Gemini embeddings can be produced."""
        return self._configured

    @property
    def model_name(self) -> str:
        """Identifier recorded alongside every indexed chunk."""
        return EMBEDDING_MODEL if self._configured else CHROMA_DEFAULT_MODEL

    async def generate(
        self,
        texts: list[str],
        task_type: str = "retrieval_document",
    ) -> list[list[float]]:
        """Embed ``texts``.

        Returns a vector per input text, or ``[]`` if embeddings are
        unavailable - callers must then pass raw text to ChromaDB and let
        it embed with its default function.
        """
        if not texts or not self._configured:
            return []

        prepared = [(t or "")[:_MAX_CHARS] for t in texts]
        vectors: list[list[float]] = []

        for start in range(0, len(prepared), _MAX_BATCH):
            batch = prepared[start:start + _MAX_BATCH]
            batch_vectors = await self._embed_batch(batch, task_type)
            if not batch_vectors:
                logger.error(
                    f"Embedding failed for batch at offset {start}; "
                    "aborting so ChromaDB is not given a partial vector set"
                )
                return []
            vectors.extend(batch_vectors)

        return vectors

    async def _embed_batch(self, batch: list[str], task_type: str) -> list[list[float]]:
        """Embed one batch with exponential-backoff retry on transient errors."""
        for attempt in range(1, _MAX_ATTEMPTS + 1):
            try:
                response = await asyncio.to_thread(
                    genai.embed_content,
                    model=EMBEDDING_MODEL,
                    content=batch,
                    task_type=task_type,
                    output_dimensionality=EMBEDDING_DIM,
                )
                embedding = response["embedding"]
                # A single string input returns a flat vector; normalise to a list.
                if embedding and isinstance(embedding[0], (int, float)):
                    embedding = [embedding]
                # Gemini only returns unit-length vectors at the full 3072
                # dimensions; truncated outputs must be re-normalised before
                # cosine distance is meaningful.
                return [_normalize(vec) for vec in embedding]

            except Exception as e:
                is_rate_limit = (
                    "429" in str(e)
                    or "ResourceExhausted" in str(e)
                    or "quota" in str(e).lower()
                )
                if attempt == _MAX_ATTEMPTS:
                    logger.error(f"Embedding batch failed after {attempt} attempts: {e}")
                    return []

                delay = 60 if is_rate_limit else 2 ** attempt
                logger.warning(
                    f"Embedding attempt {attempt} failed ({e}); retrying in {delay}s"
                )
                await asyncio.sleep(delay)

        return []
