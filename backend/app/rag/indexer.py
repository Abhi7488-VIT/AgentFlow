"""Indexes scraped workflow data into ChromaDB for retrieval.

This is the write half of the RAG pipeline: after a workflow finishes and
its scraped rows are persisted to PostgreSQL, every item is chunked,
embedded, and upserted into that workflow's own Chroma collection. An
``EmbeddingMetadata`` row is written per chunk so it is always possible to
trace a retrieved chunk back to the ``scraped_data`` row it came from.
"""

import uuid

from sqlalchemy import delete, select

from app.config import settings
from app.core.logging import get_logger
from app.models.embedding_metadata import EmbeddingMetadata
from app.models.scraped_data import ScrapedData
from app.rag.embeddings import EmbeddingGenerator
from app.rag.vectorstore import VectorStore, collection_name_for

logger = get_logger(__name__)

# Chroma metadata values must be primitives; everything else is dropped.
_PRIMITIVES = (str, int, float, bool)
_KEEP_KEYS = (
    "subreddit", "author", "date", "score", "post_title", "num_comments",
    "type", "rating", "verified_purchase", "video_title", "channel",
    "likes", "is_mock",
)


def chunk_text(text: str, size: int = None, overlap: int = None) -> list[str]:
    """Split ``text`` into overlapping windows.

    Overlap keeps a sentence that straddles a boundary retrievable from
    either side. Most scraped items are short enough to yield one chunk.
    """
    size = size or settings.RAG_CHUNK_SIZE
    overlap = overlap or settings.RAG_CHUNK_OVERLAP

    text = (text or "").strip()
    if not text:
        return []
    if len(text) <= size:
        return [text]

    step = max(size - overlap, 1)
    chunks = []
    for start in range(0, len(text), step):
        chunk = text[start:start + size].strip()
        if chunk:
            chunks.append(chunk)
        if start + size >= len(text):
            break
    return chunks


def _flatten_metadata(item: dict, workflow_id, chunk_index: int, total_chunks: int) -> dict:
    """Build a Chroma-safe metadata dict (primitives only, no None)."""
    flat = {
        "workflow_id": str(workflow_id),
        "source": str(item.get("source") or "unknown"),
        "scraped_id": str(item.get("id") or ""),
        "chunk_index": chunk_index,
        "total_chunks": total_chunks,
    }

    if item.get("sentiment_label"):
        flat["sentiment_label"] = str(item["sentiment_label"])
    if isinstance(item.get("sentiment_score"), (int, float)):
        flat["sentiment_score"] = float(item["sentiment_score"])

    raw = item.get("metadata") or {}
    if isinstance(raw, dict):
        for key in _KEEP_KEYS:
            value = raw.get(key)
            if value is None:
                continue
            flat[key] = value if isinstance(value, _PRIMITIVES) else str(value)

    return flat


async def index_workflow_items(db, workflow_id, items: list[dict]) -> dict:
    """Chunk, embed, and upsert ``items`` into the workflow's collection.

    Each item needs ``id`` (the ``scraped_data`` row id) and ``content``;
    ``source``, ``metadata``, and sentiment fields are indexed when present.

    Returns a stats dict. Never raises - indexing failure degrades the
    RAG feature but must not fail an otherwise successful workflow.
    """
    collection = collection_name_for(workflow_id)
    stats = {
        "collection": collection,
        "documents": 0,
        "chunks": 0,
        "embedding_model": None,
        "indexed": False,
    }

    try:
        texts: list[str] = []
        metadatas: list[dict] = []
        ids: list[str] = []
        metadata_rows: list[EmbeddingMetadata] = []

        for item in items:
            content = (item.get("content") or "").strip()
            if not content:
                continue

            source_id = item.get("id")
            chunks = chunk_text(content)
            if not chunks:
                continue

            stats["documents"] += 1

            for idx, chunk in enumerate(chunks):
                # Deterministic id makes re-indexing idempotent.
                chunk_id = f"{source_id}:{idx}" if source_id else str(uuid.uuid4())
                texts.append(chunk)
                metadatas.append(_flatten_metadata(item, workflow_id, idx, len(chunks)))
                ids.append(chunk_id)

                if source_id:
                    metadata_rows.append(
                        EmbeddingMetadata(
                            workflow_id=workflow_id,
                            source_id=source_id,
                            collection_name=collection,
                            embedding_model="",  # filled in below
                            chunk_text=chunk,
                        )
                    )

        if not texts:
            logger.warning(f"Nothing to index for workflow {workflow_id}")
            return stats

        generator = EmbeddingGenerator()
        embeddings = await generator.generate(texts, task_type="retrieval_document")

        if generator.is_available and not embeddings:
            # Gemini is configured but failed. Indexing text-only would make
            # Chroma build a different-dimension index that later queries
            # cannot match, so stop rather than corrupt the collection.
            logger.error(
                f"Embedding generation failed for workflow {workflow_id}; "
                "skipping indexing to keep the collection consistent"
            )
            return stats

        model_name = generator.model_name
        stats["embedding_model"] = model_name

        store = VectorStore()
        ok = await store.add_documents(
            collection_name=collection,
            texts=texts,
            metadatas=metadatas,
            ids=ids,
            embeddings=embeddings or None,
        )
        if not ok:
            return stats

        # Replace bookkeeping rows so re-indexing does not accumulate duplicates.
        await db.execute(
            delete(EmbeddingMetadata).where(EmbeddingMetadata.workflow_id == workflow_id)
        )
        for row in metadata_rows:
            row.embedding_model = model_name
            db.add(row)

        stats["chunks"] = len(texts)
        stats["indexed"] = True
        logger.info(
            f"Indexed workflow {workflow_id}: {stats['documents']} documents -> "
            f"{stats['chunks']} chunks in '{collection}' via {model_name}"
        )
        return stats

    except Exception as e:
        logger.error(f"Indexing failed for workflow {workflow_id}: {e}")
        return stats


async def reindex_workflow(db, workflow_id) -> dict:
    """Rebuild a workflow's collection from its persisted ``scraped_data``."""
    result = await db.execute(
        select(ScrapedData).where(ScrapedData.workflow_id == workflow_id)
    )
    rows = list(result.scalars().all())

    items = [
        {
            "id": row.id,
            "content": row.content,
            "source": row.source,
            "metadata": row.metadata_ or {},
            "sentiment_label": row.sentiment_label,
            "sentiment_score": row.sentiment_score,
        }
        for row in rows
    ]

    stats = await index_workflow_items(db, workflow_id, items)
    await db.commit()
    return stats
