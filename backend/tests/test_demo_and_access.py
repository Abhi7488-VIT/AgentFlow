"""Tests for public-deployment hardening: demo login, user-list access,
ADMIN_EMAIL, and hosted-Postgres URL handling."""

import pytest

from app.config import settings
from app.database import normalize_db_url
from app.schemas.user import UserCreate
from app.services.auth_service import create_user
from tests.conftest import TestSessionLocal

PASSWORD = "Correct-Horse-Battery9"


async def _register(client, email: str) -> dict:
    resp = await client.post(
        "/api/auth/register",
        json={"email": email, "password": PASSWORD, "full_name": "Test User"},
    )
    assert resp.status_code == 200, resp.text
    return resp.json()


async def _token(client, email: str) -> str:
    resp = await client.post(
        "/api/auth/login", data={"username": email, "password": PASSWORD}
    )
    assert resp.status_code == 200, resp.text
    return resp.json()["access_token"]


@pytest.mark.asyncio
class TestDemoLogin:
    async def test_demo_login_returns_token_for_viewer(self, client):
        resp = await client.post("/api/auth/demo")

        assert resp.status_code == 200
        body = resp.json()
        assert body["access_token"]
        assert body["user"]["email"] == settings.DEMO_EMAIL
        assert body["user"]["role"] == "viewer"

    async def test_demo_login_reuses_one_account(self, client):
        first = (await client.post("/api/auth/demo")).json()["user"]["id"]
        second = (await client.post("/api/auth/demo")).json()["user"]["id"]

        assert first == second

    async def test_demo_token_authenticates(self, client):
        token = (await client.post("/api/auth/demo")).json()["access_token"]
        resp = await client.get(
            "/api/workflows/", headers={"Authorization": f"Bearer {token}"}
        )

        assert resp.status_code == 200

    async def test_demo_can_be_disabled(self, client, monkeypatch):
        monkeypatch.setattr(settings, "DEMO_ENABLED", False)

        assert (await client.post("/api/auth/demo")).status_code == 404

    async def test_demo_workflows_are_capped_per_hour(self, client, monkeypatch):
        monkeypatch.setattr(settings, "DEMO_MAX_WORKFLOWS_PER_HOUR", 2)
        # Don't run the real agent pipeline in the background.
        monkeypatch.setattr(
            "app.api.workflows.execute_workflow_task", lambda **kwargs: None
        )
        token = (await client.post("/api/auth/demo")).json()["access_token"]
        headers = {"Authorization": f"Bearer {token}"}
        body = {"query": "electric scooters", "sources": ["youtube"]}

        codes = [
            (await client.post("/api/workflows/", json=body, headers=headers)).status_code
            for _ in range(3)
        ]

        assert codes == [200, 200, 429]


@pytest.mark.asyncio
class TestUserListAccess:
    async def test_anonymous_cannot_list_users(self, client):
        assert (await client.get("/api/auth/users")).status_code == 401

    async def test_viewer_cannot_list_users(self, client):
        await _register(client, "owner@example.com")
        await _register(client, "viewer@example.com")
        token = await _token(client, "viewer@example.com")

        resp = await client.get(
            "/api/auth/users", headers={"Authorization": f"Bearer {token}"}
        )

        assert resp.status_code == 403

    async def test_admin_can_list_users(self, client):
        await _register(client, "owner@example.com")
        token = await _token(client, "owner@example.com")

        resp = await client.get(
            "/api/auth/users", headers={"Authorization": f"Bearer {token}"}
        )

        assert resp.status_code == 200
        assert [u["email"] for u in resp.json()] == ["owner@example.com"]


@pytest.mark.asyncio
class TestAdminEmail:
    async def test_admin_email_wins_over_first_signup(self, monkeypatch):
        monkeypatch.setattr(settings, "ADMIN_EMAIL", "Owner@Example.com")
        async with TestSessionLocal() as db:
            first = await create_user(
                db, UserCreate(email="early@example.com", password=PASSWORD, full_name="A")
            )
            owner = await create_user(
                db, UserCreate(email="owner@example.com", password=PASSWORD, full_name="B")
            )

        assert first.role == "viewer"
        assert owner.role == "admin"


class TestNormalizeDbUrl:
    def test_neon_url_is_converted_for_asyncpg(self):
        url, args = normalize_db_url(
            "postgresql://u:p@ep-x.neon.tech/db?sslmode=require&channel_binding=require"
        )

        assert url == "postgresql+asyncpg://u:p@ep-x.neon.tech/db"
        assert args == {"ssl": "require"}

    def test_postgres_scheme_alias_is_accepted(self):
        url, args = normalize_db_url("postgres://u:p@host:5432/db")

        assert url == "postgresql+asyncpg://u:p@host:5432/db"
        assert args == {}

    def test_asyncpg_and_sqlite_urls_pass_through(self):
        for raw in (
            "postgresql+asyncpg://u:p@postgres:5432/agentflow",
            "sqlite+aiosqlite:///./agentflow.db",
        ):
            assert normalize_db_url(raw) == (raw, {})


@pytest.mark.asyncio
class TestDemoAccountIsolation:
    async def test_demo_email_cannot_be_registered(self, client):
        resp = await client.post(
            "/api/auth/register",
            json={"email": settings.DEMO_EMAIL.upper(), "password": PASSWORD, "full_name": "X"},
        )

        assert resp.status_code == 400

    async def test_demo_never_signs_into_an_admin(self, client, monkeypatch):
        monkeypatch.setattr(settings, "ADMIN_EMAIL", settings.DEMO_EMAIL)
        async with TestSessionLocal() as db:
            admin = await create_user(
                db, UserCreate(email=settings.DEMO_EMAIL, password=PASSWORD, full_name="A")
            )
        assert admin.role == "admin"

        assert (await client.post("/api/auth/demo")).status_code == 403
