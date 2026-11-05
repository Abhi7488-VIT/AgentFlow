"""
AgentFlow AI - Refresh Token Model

Server-side record of each refresh token, so tokens can be rotated, revoked
and checked for reuse. The token itself only ever lives in the browser's
HttpOnly cookie; the database stores its SHA-256 hash, so a leaked table
cannot be replayed.

Tokens from one login form a *family*. Every refresh revokes the presented
token and issues a successor in the same family. If an already-rotated token
shows up again, someone else holds a copy, and the whole family is revoked.
"""

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class RefreshToken(Base):
    __tablename__ = "refresh_tokens"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    # hex SHA-256 of the cookie value
    token_hash: Mapped[str] = mapped_column(String(64), nullable=False, unique=True, index=True)
    family_id: Mapped[uuid.UUID] = mapped_column(nullable=False, index=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # Set when revoked by rotation (not by logout or reuse detection).
    replaced_by: Mapped[uuid.UUID | None] = mapped_column(nullable=True)

    def __repr__(self) -> str:
        return f"<RefreshToken(id={self.id}, user_id={self.user_id}, revoked={self.revoked_at is not None})>"
