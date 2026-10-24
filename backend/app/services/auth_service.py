"""Auth service - user creation and credential verification."""

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func
from app.models.user import User
from app.schemas.user import UserCreate
from app.config import settings
from app.core.security import hash_password, verify_password


async def role_for_new_user(db: AsyncSession, email: str) -> str:
    """Pick the role for a new signup.

    With ADMIN_EMAIL set, only that address becomes admin. Otherwise the very
    first account bootstraps as admin. Everyone else is a viewer: granting
    admin to every registration would make require_role() meaningless.
    """
    if settings.ADMIN_EMAIL:
        return "admin" if email.lower() == settings.ADMIN_EMAIL.lower() else "viewer"
    existing = await db.execute(select(func.count(User.id)))
    return "admin" if (existing.scalar() or 0) == 0 else "viewer"


async def create_user(db: AsyncSession, user_data: UserCreate) -> User:
    hashed = hash_password(user_data.password)
    role = await role_for_new_user(db, user_data.email)

    user = User(
        email=user_data.email,
        hashed_password=hashed,
        full_name=user_data.full_name,
        role=role
    )
    db.add(user)
    await db.commit()
    await db.refresh(user)
    return user

async def authenticate_user(db: AsyncSession, email: str, password: str) -> User | None:
    result = await db.execute(select(User).where(User.email == email))
    user = result.scalar_one_or_none()
    if not user:
        return None
    if not verify_password(password, user.hashed_password):
        return None
    return user

async def get_user_by_email(db: AsyncSession, email: str) -> User | None:
    result = await db.execute(select(User).where(User.email == email))
    return result.scalar_one_or_none()

async def get_user_by_id(db: AsyncSession, user_id) -> User | None:
    result = await db.execute(select(User).where(User.id == user_id))
    return result.scalar_one_or_none()
