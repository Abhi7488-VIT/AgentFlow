"""RAG service - question answering over indexed workflow data."""

from app.rag.indexer import reindex_workflow
from app.rag.retriever import RAGRetriever
from app.rag.vectorstore import VectorStore, collection_name_for


async def query_rag(question: str, workflow_id: str = None) -> dict:
    """Answer a question from a workflow's indexed corpus."""
    retriever = RAGRetriever()
    collection_name = collection_name_for(workflow_id)
    result = await retriever.query(question, collection_name)
    result["collection"] = collection_name
    return result


async def index_workflow(db, workflow_id) -> dict:
    """Rebuild the vector index for one workflow from its stored data."""
    return await reindex_workflow(db, workflow_id)


async def collection_status(workflow_id) -> dict:
    """How many chunks are currently indexed for a workflow."""
    collection_name = collection_name_for(workflow_id)
    count = await VectorStore().count(collection_name)
    return {
        "collection": collection_name,
        "indexed_chunks": count,
        "queryable": count > 0,
    }
