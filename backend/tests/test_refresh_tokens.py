"""Refresh-token flow: HttpOnly cookie, rotation, reuse detection, logout.

Uses an https:// test client because httpx (like browsers) only sends
Secure cookies over HTTPS.
"""

from datetime import datetime, timedelta, timezone

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

from app.config import settings
from app.core.security import create_access_token
from app.database import get_db
from app.main import app
from app.models.refresh_token import RefreshToken
from app.models.user import User
from app.services.refresh_service import hash_token
from tests.conftest import TestSessionLocal, override_get_db

PASSWORD = "Correct-Horse-Battery9"
ALLOWED_ORIGIN = "http://localhost:5173"   # in CORS_ORIGINS (conftest)
COOKIE = settings.REFRESH_COOKIE_NAME


@pytest_asyncio.fixture
async def sclient():
    app.dependency_overrides[get_db] = override_get_db
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="https://test",
        headers={"Origin": ALLOWED_ORIGIN},
    ) as ac:
        yield ac
    app.dependency_overrides.clear()


async def _login(client, email="user@example.com"):
    await client.post(
        "/api/auth/register", json={"email": email, "password": PASSWORD, "full_name": "U"}
    )
    resp = await client.post("/api/auth/login", data={"username": email, "password": PASSWORD})
    assert resp.status_code == 200, resp.text
    return resp


def _cookie_header(resp) -> str:
    headers = [h for h in resp.headers.get_list("set-cookie") if h.startswith(f"{COOKIE}=")]
    assert len(headers) == 1, headers
    return headers[0]


def _cookie_value(resp) -> str:
    return _cookie_header(resp).split(";", 1)[0].split("=", 1)[1]


async def _rows():
    async with TestSessionLocal() as db:
        return list((await db.execute(select(RefreshToken).order_by(RefreshToken.created_at))).scalars())


async def _refresh(client, raw: str | None = None):
    """POST /refresh. With ``raw``, present exactly that token and nothing else."""
    if raw is None:
        return await client.post("/api/auth/refresh")
    client.cookies.clear()
    return await client.post("/api/auth/refresh", headers={"Cookie": f"{COOKIE}={raw}"})


class TestCookie:
    async def test_login_sets_a_locked_down_refresh_cookie(self, sclient):
        header = _cookie_header(await _login(sclient))
        attrs = [a.strip().lower() for a in header.split(";")]

        assert "httponly" in attrs
        assert "secure" in attrs
        assert "samesite=none" in attrs
        assert "partitioned" in attrs
        assert f"path={settings.REFRESH_COOKIE_PATH}" in attrs
        assert f"max-age={settings.REFRESH_TOKEN_EXPIRE_DAYS * 86400}" in attrs

    async def test_token_is_not_in_the_response_body(self, sclient):
        resp = await _login(sclient)
        assert _cookie_value(resp) not in resp.text

    async def test_only_the_hash_is_stored(self, sclient):
        raw = _cookie_value(await _login(sclient))
        [row] = await _rows()
        assert row.token_hash == hash_token(raw)
        assert raw not in row.token_hash

    async def test_demo_login_also_gets_a_refresh_cookie(self, sclient):
        resp = await sclient.post("/api/auth/demo")
        assert resp.status_code == 200
        assert _cookie_value(resp)


class TestRefresh:
    async def test_expired_access_token_is_refreshed(self, sclient):
        await _login(sclient)
        async with TestSessionLocal() as db:
            user = (await db.execute(select(User))).scalar_one()
        expired = create_access_token({"sub": str(user.id)}, expires_delta=timedelta(minutes=-1))

        denied = await sclient.get(
            "/api/dashboard/overview", headers={"Authorization": f"Bearer {expired}"}
        )
        assert denied.status_code == 401

        refreshed = await _refresh(sclient)
        assert refreshed.status_code == 200
        token = refreshed.json()["access_token"]
        assert refreshed.json()["user"]["email"] == "user@example.com"

        ok = await sclient.get("/api/dashboard/overview", headers={"Authorization": f"Bearer {token}"})
        assert ok.status_code == 200

    async def test_refresh_rotates_the_cookie(self, sclient):
        first = _cookie_value(await _login(sclient))
        resp = await _refresh(sclient)
        second = _cookie_value(resp)

        assert second != first
        old, new = await _rows()
        assert old.revoked_at is not None and old.replaced_by == new.id
        assert new.revoked_at is None and new.family_id == old.family_id

    async def test_rotation_chain_keeps_working(self, sclient):
        await _login(sclient)
        for _ in range(3):
            assert (await _refresh(sclient)).status_code == 200
        rows = await _rows()
        assert len(rows) == 4 and sum(r.revoked_at is None for r in rows) == 1

    async def test_missing_cookie_is_401(self, sclient):
        resp = await _refresh(sclient)
        assert resp.status_code == 401

    async def test_unknown_token_is_401_and_clears_the_cookie(self, sclient):
        resp = await _refresh(sclient, "forged")
        assert resp.status_code == 401
        assert "max-age=0" in _cookie_header(resp).lower()

    async def test_expired_refresh_token_is_rejected(self, sclient):
        await _login(sclient)
        async with TestSessionLocal() as db:
            row = (await db.execute(select(RefreshToken))).scalar_one()
            row.expires_at = datetime.now(timezone.utc) - timedelta(seconds=1)
            await db.commit()
        assert (await _refresh(sclient)).status_code == 401

    async def test_deactivated_user_cannot_refresh(self, sclient):
        await _login(sclient)
        async with TestSessionLocal() as db:
            user = (await db.execute(select(User))).scalar_one()
            user.is_active = False
            await db.commit()
        assert (await _refresh(sclient)).status_code == 401


class TestRevocation:
    async def test_revoked_refresh_token_is_rejected_after_logout(self, sclient):
        raw = _cookie_value(await _login(sclient))

        out = await sclient.post("/api/auth/logout")
        assert out.status_code == 200
        assert "max-age=0" in _cookie_header(out).lower()

        # Replay the token the browser had before logging out.
        assert (await _refresh(sclient, raw)).status_code == 401

    async def test_logout_without_a_cookie_is_harmless(self, sclient):
        assert (await sclient.post("/api/auth/logout")).status_code == 200

    async def test_reuse_of_a_rotated_token_revokes_the_whole_family(self, sclient, monkeypatch):
        monkeypatch.setattr(settings, "REFRESH_REUSE_GRACE_SECONDS", 0)
        stolen = _cookie_value(await _login(sclient))
        legit = _cookie_value(await _refresh(sclient))     # rotates; `stolen` is now spent
        assert (await _refresh(sclient, stolen)).status_code == 401

        # The legitimate successor is dead too: the family was revoked.
        assert (await _refresh(sclient, legit)).status_code == 401
        assert all(r.revoked_at is not None for r in await _rows())

    async def test_concurrent_refresh_within_grace_is_not_treated_as_theft(self, sclient):
        first = _cookie_value(await _login(sclient))
        await _refresh(sclient)                              # tab A rotates
        resp = await _refresh(sclient, first)                       # tab B, same old cookie

        assert resp.status_code == 200
        assert resp.json()["access_token"]
        assert not [h for h in resp.headers.get_list("set-cookie") if h.startswith(f"{COOKIE}=")]
        assert sum(r.revoked_at is None for r in await _rows()) == 1


class TestCsrf:
    @pytest.mark.parametrize("path", ["/api/auth/refresh", "/api/auth/logout"])
    async def test_foreign_origin_is_refused(self, sclient, path):
        await _login(sclient)
        resp = await sclient.post(path, headers={"Origin": "https://evil.example"})
        assert resp.status_code == 403
        assert all(r.revoked_at is None for r in await _rows())

    async def test_preview_origin_matching_the_regex_is_allowed(self, sclient):
        await _login(sclient)
        resp = await sclient.post(
            "/api/auth/refresh", headers={"Origin": "https://agentflow-pr-7.vercel.app"}
        )
        assert resp.status_code == 200

    async def test_cors_lets_the_frontend_send_credentials(self, sclient):
        resp = await sclient.options(
            "/api/auth/refresh",
            headers={"Origin": ALLOWED_ORIGIN, "Access-Control-Request-Method": "POST"},
        )
        assert resp.headers["access-control-allow-origin"] == ALLOWED_ORIGIN
        assert resp.headers["access-control-allow-credentials"] == "true"
