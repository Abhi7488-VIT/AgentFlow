"""Refresh-token lifecycle: issue, rotate (with reuse detection), revoke.

The browser holds the raw token in an HttpOnly cookie; the database holds
only its SHA-256. See app/models/refresh_token.py for the family model.
"""

from __future__ import annotations

import hashlib
import secrets
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.core.logging import get_logger
from app.models.refresh_token import RefreshToken
from app.models.user import User

logger = get_logger(__name__)


def hash_token(raw: str) -> str:
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _aware(dt: datetime) -> datetime:
    # SQLite returns naive datetimes; everything stored is UTC.
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


async def issue(db: AsyncSession, user_id, family_id: uuid.UUID | None = None) -> tuple[str, RefreshToken]:
    """Create a refresh token (a new family unless one is given)."""
    raw = secrets.token_urlsafe(48)
    row = RefreshToken(
        user_id=user_id,
        token_hash=hash_token(raw),
        family_id=family_id or uuid.uuid4(),
        expires_at=_now() + timedelta(days=settings.REFRESH_TOKEN_EXPIRE_DAYS),
    )
    db.add(row)
    await db.flush()
    return raw, row


@dataclass
class RefreshResult:
    user: User | None = None
    new_raw_token: str | None = None   # None: keep the cookie as it is
    error: str | None = None


async def revoke_family(db: AsyncSession, family_id) -> None:
    await db.execute(
        update(RefreshToken)
        .where(RefreshToken.family_id == family_id, RefreshToken.revoked_at.is_(None))
        .values(revoked_at=_now())
        .execution_options(synchronize_session=False)
    )


async def rotate(db: AsyncSession, raw: str | None) -> RefreshResult:
    """Exchange a refresh token for a user plus its successor token."""
    if not raw:
        return RefreshResult(error="missing")

    row = (
        await db.execute(select(RefreshToken).where(RefreshToken.token_hash == hash_token(raw)))
    ).scalar_one_or_none()
    if row is None:
        return RefreshResult(error="unknown")

    now = _now()
    if row.revoked_at is not None:
        rotated_recently = (
            row.replaced_by is not None
            and now - _aware(row.revoked_at) <= timedelta(seconds=settings.REFRESH_REUSE_GRACE_SECONDS)
        )
        if not rotated_recently:
            # A rotated (or logged-out) token came back: assume it was copied.
            # Kill every token from that login so the copy is useless too.
            logger.warning("refresh_token_reuse", user_id=str(row.user_id), family_id=str(row.family_id))
            await revoke_family(db, row.family_id)
            return RefreshResult(error="reused")
        # Concurrent refresh from another tab: it already got the successor
        # cookie. Hand out an access token, leave the cookie alone.
        user = await db.get(User, row.user_id)
        if user is None or not user.is_active:
            return RefreshResult(error="inactive")
        return RefreshResult(user=user)

    if _aware(row.expires_at) <= now:
        return RefreshResult(error="expired")

    user = await db.get(User, row.user_id)
    if user is None or not user.is_active:
        await revoke_family(db, row.family_id)
        return RefreshResult(error="inactive")

    new_raw, new_row = await issue(db, row.user_id, family_id=row.family_id)
    row.revoked_at = now
    row.replaced_by = new_row.id
    return RefreshResult(user=user, new_raw_token=new_raw)


async def revoke(db: AsyncSession, raw: str | None) -> None:
    """Logout: revoke the whole family of the presented token."""
    if not raw:
        return
    row = (
        await db.execute(select(RefreshToken).where(RefreshToken.token_hash == hash_token(raw)))
    ).scalar_one_or_none()
    if row is not None:
        await revoke_family(db, row.family_id)
