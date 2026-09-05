"""RAG API routes - question-answering over workflow data."""

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from typing import Optional

from app.core.security import get_current_user
from app.database import get_db
from app.models.user import User
from app.models.workflow import Workflow
from app.services import rag_service

router = APIRouter()


class RAGQuery(BaseModel):
    question: str
    workflow_id: Optional[str] = None


async def _owned_workflow(db: AsyncSession, workflow_id: str, user: User) -> Workflow:
    """Load a workflow, rejecting ids that are malformed or not the caller's."""
    try:
        wf_uuid = UUID(str(workflow_id))
    except (ValueError, AttributeError):
        raise HTTPException(status_code=400, detail="Invalid workflow_id")

    result = await db.execute(select(Workflow).where(Workflow.id == wf_uuid))
    workflow = result.scalar_one_or_none()
    if workflow is None:
        raise HTTPException(status_code=404, detail="Workflow not found")
    if workflow.user_id != user.id and getattr(user, "role", None) != "admin":
        raise HTTPException(status_code=403, detail="Not authorized for this workflow")
    return workflow


@router.post("/query")
async def query_rag(
    query: RAGQuery,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Ask a question answered only from that workflow's scraped corpus."""
    if query.workflow_id:
        await _owned_workflow(db, query.workflow_id, current_user)
    return await rag_service.query_rag(query.question, query.workflow_id)


@router.post("/index")
async def index_documents(
    workflow_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Rebuild the vector index for a workflow from its stored scraped data.

    Workflows are indexed automatically when they complete; this endpoint
    re-runs it, for example after changing the embedding model.
    """
    workflow = await _owned_workflow(db, workflow_id, current_user)
    stats = await rag_service.index_workflow(db, workflow.id)

    if not stats.get("indexed"):
        raise HTTPException(
            status_code=409,
            detail="Nothing was indexed - the workflow has no scraped data, "
                   "or embedding generation failed.",
        )

    return {
        "status": "success",
        "message": f"Indexed {stats['documents']} documents into {stats['chunks']} chunks",
        **stats,
    }


@router.get("/status/{workflow_id}")
async def index_status(
    workflow_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Report whether a workflow's corpus is queryable, and how large it is."""
    workflow = await _owned_workflow(db, workflow_id, current_user)
    return await rag_service.collection_status(workflow.id)
