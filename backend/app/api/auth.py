"""Auth API routes - registration, login, token refresh and logout.

Sessions are a short-lived access token (JWT, returned in the body) plus a
rotating refresh token in an HttpOnly cookie scoped to /api/auth. The
frontend silently trades the cookie for a new access token on a 401.
"""

import re
import secrets

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from fastapi.responses import JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func
from fastapi.security import OAuth2PasswordRequestForm

from app.database import get_db
from app.models.user import User
from app.config import settings
from app.core.security import (
    burn_password_check,
    create_access_token,
    hash_password_async,
    needs_rehash,
    require_role,
    verify_password_async,
)
from app.schemas.user import UserCreate, TokenResponse, UserResponse
from app.services.auth_service import create_user
from app.services import refresh_service
from app.core import perf

router = APIRouter()


# --------------------------------------------------------------------- #
#  Refresh cookie
# --------------------------------------------------------------------- #

def _refresh_cookie_header(value: str, max_age: int) -> str:
    """Build the Set-Cookie header by hand.

    Starlette's set_cookie goes through http.cookies, which only supports
    the Partitioned attribute on Python 3.14+ (production runs 3.11).
    The value is URL-safe base64 from secrets.token_urlsafe, so it needs no
    quoting.
    """
    parts = [
        f"{settings.REFRESH_COOKIE_NAME}={value}",
        f"Max-Age={max_age}",
        f"Path={settings.REFRESH_COOKIE_PATH}",
        "HttpOnly",           # unreadable by page JavaScript, so XSS cannot steal it
        f"SameSite={settings.REFRESH_COOKIE_SAMESITE.capitalize()}",
    ]
    if max_age == 0:
        parts.append("Expires=Thu, 01 Jan 1970 00:00:00 GMT")
    if settings.REFRESH_COOKIE_SECURE:
        parts.append("Secure")
    if settings.REFRESH_COOKIE_PARTITIONED:
        parts.append("Partitioned")
    return "; ".join(parts)


def set_refresh_cookie(response: Response, raw_token: str) -> None:
    max_age = settings.REFRESH_TOKEN_EXPIRE_DAYS * 24 * 3600
    response.headers.append("set-cookie", _refresh_cookie_header(raw_token, max_age))


def clear_refresh_cookie(response: Response) -> None:
    # Same Path / SameSite / Partitioned as when set, or browsers keep it.
    response.headers.append("set-cookie", _refresh_cookie_header("", 0))


def origin_allowed(origin: str) -> bool:
    """Same allow-list as CORS (CORS_ORIGINS plus CORS_ORIGIN_REGEX)."""
    origins = settings.cors_origins
    if "*" in origins or origin in origins:
        return True
    regex = settings.CORS_ORIGIN_REGEX
    return bool(regex and re.fullmatch(regex, origin))


def require_allowed_origin(request: Request) -> None:
    """CSRF guard for the cookie-authenticated endpoints.

    The refresh cookie is SameSite=None (the frontend is a different site),
    so a page on any site could make the browser POST it here. CORS stops
    that page from *reading* the new access token, but the request would
    still rotate the token. Browsers always send Origin on cross-site
    POSTs, so refuse any Origin not on the allow-list. Requests without
    Origin (curl, server-to-server) carry no browser cookie jar to abuse.
    """
    origin = request.headers.get("origin")
    if origin and not origin_allowed(origin):
        raise HTTPException(status_code=403, detail="Origin not allowed")


async def _session_response(db: AsyncSession, response: Response, user: User) -> dict:
    """Body for a fresh login: access token, plus a refresh cookie."""
    raw, _ = await refresh_service.issue(db, user.id)
    set_refresh_cookie(response, raw)
    return {
        "access_token": create_access_token(data={"sub": str(user.id)}),
        "token_type": "bearer",
        "user": user,
    }

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
    response: Response,
    form_data: OAuth2PasswordRequestForm = Depends(),
    db: AsyncSession = Depends(get_db),
):
    # Try to authenticate user
    with perf.span("auth.db_lookup"):
        result = await db.execute(
            select(User).where(func.lower(User.email) == form_data.username.lower())
        )
        user = result.scalar_one_or_none()

    password_ok = False
    with perf.span("auth.bcrypt_verify"):
        if user:
            password_ok = await verify_password_async(form_data.password, user.hashed_password)
        else:
            # Same cost as a real check, so response time does not reveal
            # whether the email has an account.
            await burn_password_check(form_data.password)

    if not user or not password_ok:
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
        
    if needs_rehash(user.hashed_password):
        # Moves stored hashes to the configured BCRYPT_ROUNDS on next login;
        # committed by get_db with the rest of the request.
        with perf.span("auth.rehash"):
            user.hashed_password = await hash_password_async(form_data.password)

    with perf.span("auth.token_create"):
        return await _session_response(db, response, user)


@router.post("/demo", response_model=TokenResponse)
async def demo_login(response: Response, db: AsyncSession = Depends(get_db)):
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
            hashed_password=await hash_password_async(secrets.token_urlsafe(32)),
            full_name="Demo Visitor",
            role="viewer",
        )
        db.add(user)
        await db.commit()
        await db.refresh(user)

    return await _session_response(db, response, user)


@router.post(
    "/refresh",
    response_model=TokenResponse,
    dependencies=[Depends(require_allowed_origin)],
)
async def refresh(request: Request, response: Response, db: AsyncSession = Depends(get_db)):
    """Trade the refresh cookie for a new access token, rotating the cookie."""
    result = await refresh_service.rotate(db, request.cookies.get(settings.REFRESH_COOKIE_NAME))
    if result.user is None:
        if result.error == "reused":
            # Revoking the family must survive the error response.
            await db.commit()
        failed = JSONResponse(
            status_code=status.HTTP_401_UNAUTHORIZED,
            content={"detail": "Session expired. Please log in again."},
        )
        clear_refresh_cookie(failed)
        return failed

    if result.new_raw_token:
        set_refresh_cookie(response, result.new_raw_token)
    return {
        "access_token": create_access_token(data={"sub": str(result.user.id)}),
        "token_type": "bearer",
        "user": result.user,
    }


@router.post("/logout", dependencies=[Depends(require_allowed_origin)])
async def logout(request: Request, response: Response, db: AsyncSession = Depends(get_db)):
    """Revoke this login's refresh tokens and clear the cookie. Idempotent."""
    await refresh_service.revoke(db, request.cookies.get(settings.REFRESH_COOKIE_NAME))
    clear_refresh_cookie(response)
    return {"success": True}
