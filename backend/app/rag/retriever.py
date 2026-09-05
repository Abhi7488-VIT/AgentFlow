"""RAG retriever - embed the question, search ChromaDB, answer with Gemini.

This is the read half of the RAG pipeline. Answers are constrained to the
chunks retrieved from the workflow's own collection, and every claim is
expected to carry a ``[n]`` citation pointing at one of them.
"""

import asyncio

import google.generativeai as genai

from app.config import settings
from app.core.logging import get_logger
from app.core.sanitizer import sanitize_query
from app.rag.embeddings import EmbeddingGenerator
from app.rag.vectorstore import VectorStore

logger = get_logger(__name__)

# One retry is enough for a transient per-minute limit; a daily cap will
# not clear in time and the retrieved context is returned instead.
_GENERATION_ATTEMPTS = 2
_RATE_LIMIT_BACKOFF = 30

NO_CONTEXT_ANSWER = (
    "I don't have enough context in the collected data to answer that question. "
    "Run a workflow for this topic first, or ask about something covered by the "
    "data that was gathered."
)


class RAGRetriever:
    def __init__(self):
        self.embedding_gen = EmbeddingGenerator()
        self.vector_store = VectorStore()
        if settings.GEMINI_API_KEY:
            genai.configure(api_key=settings.GEMINI_API_KEY)
            self.model = genai.GenerativeModel("gemini-2.5-flash")
        else:
            self.model = None

    async def query(self, question: str, collection_name: str) -> dict:
        try:
            # The question reaches an LLM prompt, so it gets the same
            # injection sanitising as any other user input.
            try:
                question, warnings = sanitize_query(question)
            except ValueError as e:
                return {"answer": str(e), "sources": [], "confidence": 0.0}
            if warnings:
                logger.warning(f"Sanitizer warnings on RAG question: {warnings}")

            indexed = await self.vector_store.count(collection_name)
            if indexed == 0:
                logger.info(f"Collection '{collection_name}' is empty")
                return {"answer": NO_CONTEXT_ANSWER, "sources": [], "confidence": 0.0}

            # 1. Embed the question with the query-side task type.
            query_embedding = await self.embedding_gen.generate(
                [question], task_type="retrieval_query"
            )

            # 2. Search. Fall back to text search only when embeddings are
            #    unavailable at both index and query time.
            results = await self.vector_store.search(
                collection_name=collection_name,
                query_texts=None if query_embedding else [question],
                query_embeddings=query_embedding or None,
                n_results=settings.RAG_TOP_K,
            )

            documents = (results.get("documents") or [[]])[0]
            metadatas = (results.get("metadatas") or [[]])[0]
            distances = (results.get("distances") or [[]])[0]

            # 3. Drop weak matches so genuinely unrelated chunks are never
            #    presented to the model as evidence.
            kept = [
                (doc, metadatas[i] if i < len(metadatas) else {}, distances[i] if i < len(distances) else 1.0)
                for i, doc in enumerate(documents)
                if _similarity(distances[i] if i < len(distances) else 1.0)
                >= settings.RAG_MIN_SIMILARITY
            ]

            if not kept:
                logger.info(
                    f"All {len(documents)} hits fell below the "
                    f"{settings.RAG_MIN_SIMILARITY} similarity floor"
                )
                return {"answer": NO_CONTEXT_ANSWER, "sources": [], "confidence": 0.0}

            documents = [k[0] for k in kept]
            metadatas = [k[1] for k in kept]
            distances = [k[2] for k in kept]

            # 4. Build a numbered context block the model must cite from.
            context = "\n\n".join(
                f"Source [{i + 1}] ({(metadatas[i] or {}).get('source', 'unknown')}): {doc}"
                for i, doc in enumerate(documents)
            )

            prompt = f"""You are an AI assistant analyzing market research data.
Use ONLY the following context to answer the user's question.
If the answer is not contained in the context, say so plainly instead of guessing.
Always cite your sources using the [number] format.

Context:
{context}

Question: {question}
"""

            # 5. Generate the grounded answer. Retrieval has already
            #    succeeded at this point, so a generation failure degrades
            #    to returning the evidence rather than losing it.
            if self.model:
                answer = await self._generate(prompt, context)
            else:
                answer = (
                    "No Gemini API key is configured, so I can only return the "
                    "retrieved context:\n\n" + context
                )

            sources = [
                {
                    "id": i + 1,
                    "text": doc[:200] + ("..." if len(doc) > 200 else ""),
                    "metadata": metadatas[i] if i < len(metadatas) else {},
                    "similarity": _similarity(distances[i]) if i < len(distances) else None,
                }
                for i, doc in enumerate(documents)
            ]

            return {
                "answer": answer,
                "sources": sources,
                "confidence": _confidence(distances),
                "chunks_searched": indexed,
            }

        except Exception as e:
            logger.error(f"Error in RAG query: {e}")
            return {
                "answer": (
                    "The question could not be answered right now. Please try again."
                ),
                "sources": [],
                "confidence": 0.0,
                "error": str(e)[:300],
            }

    async def _generate(self, prompt: str, context: str) -> str:
        """Ask Gemini, retrying once through a transient rate limit.

        If generation stays unavailable the retrieved context is returned
        instead: the useful work - finding the relevant evidence - is
        already done, and throwing it away because the summariser is
        rate-limited would waste it.
        """
        for attempt in range(1, _GENERATION_ATTEMPTS + 1):
            try:
                response = await self.model.generate_content_async(prompt)
                return response.text
            except Exception as e:
                if attempt >= _GENERATION_ATTEMPTS or not _is_rate_limit(e):
                    logger.error(f"RAG generation failed: {str(e)[:200]}")
                    break

                logger.warning(
                    f"RAG generation rate-limited, retrying in {_RATE_LIMIT_BACKOFF}s"
                )
                await asyncio.sleep(_RATE_LIMIT_BACKOFF)

        return (
            "The summarising model is unavailable right now (rate limited), "
            "so here is the source material retrieved for your question:\n\n"
            + context
        )


def _is_rate_limit(error: Exception) -> bool:
    """Gemini signals quota exhaustion several different ways."""
    text = str(error).lower()
    return "429" in text or "resourceexhausted" in text or "quota" in text


def _similarity(distance) -> float:
    """Cosine distance -> similarity in [0, 1]."""
    try:
        return round(max(0.0, min(1.0, 1.0 - float(distance))), 4)
    except (TypeError, ValueError):
        return 0.0


def _confidence(distances) -> float:
    """Mean similarity of the top 3 hits - how well the corpus covers the question."""
    if not distances:
        return 0.0
    top = [_similarity(d) for d in distances[:3]]
    return round(sum(top) / len(top), 4) if top else 0.0
