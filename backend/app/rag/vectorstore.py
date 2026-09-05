"""ChromaDB vector store wrapper with async support."""

import asyncio

import chromadb

from app.config import settings
from app.core.logging import get_logger

logger = get_logger(__name__)

GLOBAL_COLLECTION = "global_knowledge"


def collection_name_for(workflow_id) -> str:
    """Collection holding one workflow's scraped corpus.

    Indexing and querying both route through this helper so the two can
    never disagree on where a workflow's vectors live.
    """
    if not workflow_id:
        return GLOBAL_COLLECTION
    return f"workflow_{workflow_id}"


def _empty_results() -> dict:
    """Chroma's query response shape, with one empty result row."""
    return {"documents": [[]], "metadatas": [[]], "distances": [[]], "ids": [[]]}


class VectorStore:
    """Singleton ChromaDB client. Persists to ``settings.CHROMA_PERSIST_DIR``."""

    _instance = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super(VectorStore, cls).__new__(cls)
            try:
                cls._instance.client = chromadb.PersistentClient(path=settings.CHROMA_PERSIST_DIR)
                logger.info("ChromaDB client initialized successfully")
            except Exception as e:
                logger.error(f"Failed to initialize ChromaDB client: {e}")
                cls._instance.client = None
        return cls._instance

    @property
    def is_available(self) -> bool:
        return self.client is not None

    def _get_or_create_collection(self, collection_name: str):
        if self.client is None:
            return None
        try:
            return self.client.get_or_create_collection(
                name=collection_name,
                # Cosine space makes similarity a readable 1 - distance.
                metadata={"hnsw:space": "cosine"},
            )
        except Exception as e:
            logger.error(f"Could not open collection {collection_name}: {e}")
            return None

    async def add_documents(
        self,
        collection_name: str,
        texts: list[str],
        metadatas: list[dict],
        ids: list[str],
        embeddings: list[list[float]] = None,
    ) -> bool:
        """Upsert chunks into ``collection_name``.

        ``upsert`` (rather than ``add``) makes re-indexing a workflow
        idempotent - the same chunk id overwrites instead of duplicating.
        """
        collection = self._get_or_create_collection(collection_name)
        if collection is None:
            logger.warning("ChromaDB not available, skipping add_documents")
            return False

        if not texts:
            return True

        try:
            kwargs = {"documents": texts, "metadatas": metadatas, "ids": ids}
            if embeddings:
                kwargs["embeddings"] = embeddings

            await asyncio.to_thread(lambda: collection.upsert(**kwargs))
            logger.info(f"Upserted {len(texts)} chunks into '{collection_name}'")
            return True
        except Exception as e:
            logger.error(f"Error adding documents to ChromaDB: {e}")
            return False

    async def search(
        self,
        collection_name: str,
        query_texts: list[str] = None,
        query_embeddings: list[list[float]] = None,
        n_results: int = 5,
    ) -> dict:
        """Query a collection by vector (preferred) or raw text."""
        collection = self._get_or_create_collection(collection_name)
        if collection is None:
            logger.warning("ChromaDB not available, returning empty search results")
            return _empty_results()

        if not query_embeddings and not query_texts:
            logger.warning("search() called with neither embeddings nor text")
            return _empty_results()

        try:
            # Never send both: Chroma rejects that combination.
            kwargs = {"n_results": n_results}
            if query_embeddings:
                kwargs["query_embeddings"] = query_embeddings
            else:
                kwargs["query_texts"] = query_texts

            return await asyncio.to_thread(lambda: collection.query(**kwargs))
        except Exception as e:
            logger.error(f"Error searching ChromaDB: {e}")
            return _empty_results()

    async def count(self, collection_name: str) -> int:
        """Number of chunks indexed in a collection (0 if it does not exist)."""
        collection = self._get_or_create_collection(collection_name)
        if collection is None:
            return 0
        try:
            return await asyncio.to_thread(collection.count)
        except Exception as e:
            logger.error(f"Error counting collection {collection_name}: {e}")
            return 0

    async def delete_collection(self, collection_name: str) -> bool:
        if self.client is None:
            return False
        try:
            await asyncio.to_thread(self.client.delete_collection, collection_name)
            return True
        except Exception as e:
            logger.error(f"Error deleting collection {collection_name}: {e}")
            return False
