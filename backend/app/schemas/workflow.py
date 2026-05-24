from typing import List, Optional
from pydantic import BaseModel, ConfigDict
from uuid import UUID
from datetime import datetime

class WorkflowBase(BaseModel):
    query: str
    sources: List[str] = ["amazon", "youtube", "reddit"]

class WorkflowCreate(WorkflowBase):
    pass

class WorkflowResponse(WorkflowBase):
    id: UUID
    status: str
    result_summary: Optional[str] = None
    agent_states: Optional[dict] = None
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)

class WorkflowListResponse(BaseModel):
    workflows: List[WorkflowResponse]
    total: int
