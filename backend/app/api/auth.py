"""Auth API routes - registration, login, and current-user lookup."""

import secrets

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func
from fastapi.security import OAuth2PasswordRequestForm

from app.database import get_db
from app.models.user import User
from app.config import settings
from app.core.security import hash_password, verify_password, create_access_token, require_role
from app.schemas.user import UserCreate, TokenResponse, UserResponse
from app.services.auth_service import create_user

router = APIRouter()

@router.post("/register", response_model=UserResponse)
async def register(user_in: UserCreate, db: AsyncSession = Depends(get_db)):
    # Case-insensitive: stored emails may predate email normalisation.
    result = await db.execute(
        select(User).where(func.lower(User.email) == user_in.email.lower())
    )
    if result.scalars().first():
        raise HTTPException(status_code=400, detail="Email already registered")
    # The demo address is shared by every visitor through /demo, so nobody
    # may claim it as a private account.
    if user_in.email.lower() == settings.DEMO_EMAIL.lower():
        raise HTTPException(status_code=400, detail="This email is reserved")

    return await create_user(db, user_in)

@router.get(
    "/users",
    response_model=list[UserResponse],
    dependencies=[Depends(require_role("admin"))],
)
async def get_all_users(db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(User))
    users = result.scalars().all()
    return list(users)


@router.post("/login", response_model=TokenResponse)
async def login(
    form_data: OAuth2PasswordRequestForm = Depends(),
    db: AsyncSession = Depends(get_db)
):
    # Try to authenticate user
    result = await db.execute(
        select(User).where(func.lower(User.email) == form_data.username.lower())
    )
    user = result.scalar_one_or_none()
    
    if not user or not verify_password(form_data.password, user.hashed_password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect email or password",
            headers={"WWW-Authenticate": "Bearer"},
        )
        
    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Inactive user"
        )
        
    access_token = create_access_token(data={"sub": str(user.id)})
    
    return {
        "access_token": access_token,
        "token_type": "bearer",
        "user": user
    }


@router.post("/demo", response_model=TokenResponse)
async def demo_login(db: AsyncSession = Depends(get_db)):
    """Sign in to the shared demo account, creating it on first use.

    Lets visitors try the product without registering. The account is a
    plain viewer with an unguessable password, so it can only be reached
    through this endpoint.
    """
    if not settings.DEMO_ENABLED:
        raise HTTPException(status_code=404, detail="Demo access is disabled")

    result = await db.execute(
        select(User).where(func.lower(User.email) == settings.DEMO_EMAIL.lower())
    )
    user = result.scalar_one_or_none()
    if user is not None and user.role == "admin":
        # Never hand an admin session to anonymous visitors, e.g. when
        # ADMIN_EMAIL is misconfigured to the demo address.
        raise HTTPException(status_code=403, detail="Demo access is unavailable")
    if user is None:
        user = User(
            email=settings.DEMO_EMAIL,
            hashed_password=hash_password(secrets.token_urlsafe(32)),
            full_name="Demo Visitor",
            role="viewer",
        )
        db.add(user)
        await db.commit()
        await db.refresh(user)

    return {
        "access_token": create_access_token(data={"sub": str(user.id)}),
        "token_type": "bearer",
        "user": user,
    }
