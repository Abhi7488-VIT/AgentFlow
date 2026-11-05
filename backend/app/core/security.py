"""Password hashing, JWT creation, and the current-user dependency."""

import asyncio
import secrets
from datetime import datetime, timedelta, timezone
from typing import Optional
from uuid import UUID
from jose import jwt, JWTError
import bcrypt
from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.config import settings
from app.database import get_db
from app.models.user import User
from app.core import perf

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/auth/login")

# Fixed demo user UUID
DEMO_USER_ID = UUID("00000000-0000-0000-0000-000000000001")

def hash_password(password: str) -> str:
    salt = bcrypt.gensalt(rounds=settings.BCRYPT_ROUNDS)
    return bcrypt.hashpw(password.encode("utf-8"), salt).decode("utf-8")

def verify_password(plain_password: str, hashed_password: str) -> bool:
    try:
        return bcrypt.checkpw(plain_password.encode("utf-8"), hashed_password.encode("utf-8"))
    except ValueError:
        # Malformed stored hash: treat as a failed login, never a 500.
        return False


def hash_rounds(hashed_password: str) -> int | None:
    """Cost factor of a bcrypt hash (``$2b$12$...`` -> 12)."""
    try:
        return int(hashed_password.split("$")[2])
    except (IndexError, ValueError):
        return None


def needs_rehash(hashed_password: str) -> bool:
    """True when the hash was made with a different cost than configured."""
    return hash_rounds(hashed_password) != settings.BCRYPT_ROUNDS


# bcrypt is deliberately slow CPU work (about 240 ms at cost 12 on a laptop and
# 1.7 s on Render's shared CPU, see docs/PERF_BASELINE.md). Called inline from
# an async route it freezes the event loop, so every other request waits
# behind a login. These run it in the default thread pool; bcrypt releases
# the GIL while hashing.

async def hash_password_async(password: str) -> str:
    return await asyncio.to_thread(hash_password, password)


async def verify_password_async(plain_password: str, hashed_password: str) -> bool:
    return await asyncio.to_thread(verify_password, plain_password, hashed_password)


_dummy_hash: str | None = None


async def burn_password_check(plain_password: str) -> None:
    """Spend the same bcrypt time as a real check, for unknown emails.

    Without it, "no such user" answers in one DB round trip while "wrong
    password" takes a full bcrypt verify. In production the gap was 0.4 s vs
    2.1 s, which tells an attacker which emails have accounts.
    """
    global _dummy_hash
    if _dummy_hash is None or hash_rounds(_dummy_hash) != settings.BCRYPT_ROUNDS:
        _dummy_hash = await hash_password_async(secrets.token_urlsafe(16))
    await verify_password_async(plain_password, _dummy_hash)

def create_access_token(data: dict, expires_delta: Optional[timedelta] = None) -> str:
    to_encode = data.copy()
    if expires_delta:
        expire = datetime.now(timezone.utc) + expires_delta
    else:
        expire = datetime.now(timezone.utc) + timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
    to_encode.update({"exp": expire})
    encoded_jwt = jwt.encode(to_encode, settings.JWT_SECRET_KEY, algorithm=settings.JWT_ALGORITHM)
    return encoded_jwt

def verify_token(token: str) -> dict:
    try:
        payload = jwt.decode(token, settings.JWT_SECRET_KEY, algorithms=[settings.JWT_ALGORITHM])
        return payload
    except JWTError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Could not validate credentials",
            headers={"WWW-Authenticate": "Bearer"},
        )

async def get_current_user(
    token: str = Depends(oauth2_scheme),
    db: AsyncSession = Depends(get_db)
) -> User:
    try:
        payload = verify_token(token)
        user_id_str = payload.get("sub")
        if user_id_str is None:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Could not validate credentials",
                headers={"WWW-Authenticate": "Bearer"},
            )
        user_id = UUID(user_id_str)
    except Exception:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Could not validate credentials",
            headers={"WWW-Authenticate": "Bearer"},
        )
        
    with perf.span("auth.user_load"):
        result = await db.execute(select(User).where(User.id == user_id))
        user = result.scalar_one_or_none()
    
    if user is None or not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User not found or inactive",
            headers={"WWW-Authenticate": "Bearer"},
        )
        
    return user

def require_role(*allowed_roles: str):
    async def role_checker(current_user: User = Depends(get_current_user)):
        if current_user.role not in allowed_roles:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Operation not permitted"
            )
        return current_user
    return role_checker
