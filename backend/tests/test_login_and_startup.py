"""Phase 1: login speed, cold start and per-request user loading.

All offline. See docs/PERF_BASELINE.md for the numbers these changes target.
"""

import asyncio
import subprocess
import sys
import threading
from datetime import datetime, timedelta, timezone
from pathlib import Path

import bcrypt
import pytest
from sqlalchemy import select
from sqlalchemy.exc import InvalidRequestError

import app.main as main_module
from app.config import settings
from app.core import security, startup
from app.database import is_pooled_host, normalize_db_url
from app.models.scraped_data import ScrapedData
from app.models.user import User
from app.models.workflow import Workflow
from app.services import workflow_service
from tests.conftest import TestSessionLocal

PASSWORD = "Correct-Horse-Battery9"
BACKEND_DIR = Path(__file__).resolve().parents[1]


async def _register(client, email="user@example.com"):
    resp = await client.post(
        "/api/auth/register", json={"email": email, "password": PASSWORD, "full_name": "U"}
    )
    assert resp.status_code == 200, resp.text
    return resp.json()


async def _login(client, email="user@example.com", password=PASSWORD):
    return await client.post("/api/auth/login", data={"username": email, "password": password})


async def _stored_hash(email):
    async with TestSessionLocal() as db:
        return (await db.execute(select(User.hashed_password).where(User.email == email))).scalar_one()


# --------------------------------------------------------------------- #
#  bcrypt
# --------------------------------------------------------------------- #

class TestPasswordHashing:
    async def test_verify_runs_off_the_event_loop(self, monkeypatch):
        loop_thread = threading.get_ident()
        seen = []
        real = bcrypt.checkpw

        def spy(*args):
            seen.append(threading.get_ident())
            return real(*args)

        monkeypatch.setattr(security.bcrypt, "checkpw", spy)
        hashed = security.hash_password("pw")

        assert await security.verify_password_async("pw", hashed)
        assert seen and seen[0] != loop_thread

    async def test_event_loop_keeps_serving_during_a_login(self, client):
        """A login must not freeze other requests for the bcrypt duration."""
        await _register(client)
        ticks = 0

        async def ticker():
            nonlocal ticks
            while True:
                ticks += 1
                await asyncio.sleep(0.005)

        task = asyncio.create_task(ticker())
        try:
            assert (await _login(client)).status_code == 200
        finally:
            task.cancel()
        # bcrypt at cost 11 is ~100+ ms; a blocked loop would tick ~once.
        assert ticks > 5

    def test_new_hashes_use_the_configured_cost(self):
        assert security.hash_rounds(security.hash_password("pw")) == settings.BCRYPT_ROUNDS

    def test_malformed_hash_is_a_failed_check_not_an_error(self):
        assert security.verify_password("pw", "not-a-bcrypt-hash") is False


class TestLogin:
    async def test_unknown_email_still_spends_a_bcrypt_check(self, client, monkeypatch):
        """Equal work for 'no such user' and 'wrong password' (no email probing)."""
        calls = []
        real = security.verify_password

        def counting(plain, hashed):
            calls.append(hashed)
            return real(plain, hashed)

        monkeypatch.setattr(security, "verify_password", counting)

        resp = await _login(client, email="nobody@example.com")

        assert resp.status_code == 401
        assert len(calls) == 1

    async def test_unknown_email_and_wrong_password_get_the_same_answer(self, client):
        await _register(client)
        unknown = await _login(client, email="nobody@example.com")
        wrong = await _login(client, password="wrong-password")
        assert unknown.status_code == wrong.status_code == 401
        assert unknown.json() == wrong.json()

    async def test_old_cost_hash_is_upgraded_on_login(self, client):
        await _register(client)
        old = bcrypt.hashpw(PASSWORD.encode(), bcrypt.gensalt(rounds=12)).decode()
        async with TestSessionLocal() as db:
            user = (await db.execute(select(User))).scalar_one()
            user.hashed_password = old
            await db.commit()

        assert (await _login(client)).status_code == 200

        new = await _stored_hash("user@example.com")
        assert new != old
        assert security.hash_rounds(new) == settings.BCRYPT_ROUNDS
        assert (await _login(client)).status_code == 200

    async def test_current_cost_hash_is_left_alone(self, client):
        await _register(client)
        before = await _stored_hash("user@example.com")
        assert (await _login(client)).status_code == 200
        assert await _stored_hash("user@example.com") == before

    async def test_bcrypt_rounds_below_owasp_minimum_are_rejected(self):
        from pydantic import ValidationError
        from app.config import Settings

        with pytest.raises(ValidationError):
            Settings(BCRYPT_ROUNDS=8)


class TestAdminRoutesRefuseViewers:
    @pytest.mark.parametrize(
        "path", ["/api/admin/users", "/api/admin/stats", "/api/monitoring/system", "/api/auth/users"]
    )
    async def test_viewer_gets_403(self, client, path):
        await _register(client, "owner@example.com")      # first account: admin
        await _register(client, "viewer@example.com")
        token = (await _login(client, email="viewer@example.com")).json()["access_token"]

        resp = await client.get(path, headers={"Authorization": f"Bearer {token}"})

        assert resp.status_code == 403


# --------------------------------------------------------------------- #
#  Per-request user load (the selectin cascade)
# --------------------------------------------------------------------- #

class TestUserLoadIsConstant:
    async def _seed_history(self, n_workflows, rows_each):
        async with TestSessionLocal() as db:
            user = (await db.execute(select(User))).scalar_one()
            for i in range(n_workflows):
                wf = Workflow(user_id=user.id, query=f"q{i}", status="completed", sources=["reddit"])
                db.add(wf)
                await db.flush()
                for _ in range(rows_each):
                    db.add(ScrapedData(workflow_id=wf.id, source="reddit", content="c",
                                       sentiment_label="POSITIVE", sentiment_score=0.5))
            await db.commit()

    async def _queries(self, client, token, path):
        resp = await client.get(path, headers={"Authorization": f"Bearer {token}"})
        assert resp.status_code == 200, resp.text
        return int(resp.headers["x-sql-queries"])

    async def test_query_count_does_not_grow_with_history(self, client, monkeypatch):
        monkeypatch.setattr(settings, "PERF_DEBUG", True)
        await _register(client)
        token = (await _login(client)).json()["access_token"]

        empty = await self._queries(client, token, "/api/dashboard/sentiment")
        await self._seed_history(n_workflows=5, rows_each=10)
        full = await self._queries(client, token, "/api/dashboard/sentiment")

        # One query to load the user, one for the aggregate. Before the
        # fix it was 7 + 1, and every scraped row was loaded.
        assert empty == full == 2

    async def test_login_is_lookup_plus_token_insert(self, client, monkeypatch):
        await _register(client)
        await self._seed_history(n_workflows=3, rows_each=5)
        monkeypatch.setattr(settings, "PERF_DEBUG", True)

        resp = await _login(client)

        assert resp.status_code == 200
        # User lookup + refresh-token insert. Was 7 with the selectin cascade.
        assert int(resp.headers["x-sql-queries"]) == 2

    async def test_relationships_never_load_implicitly(self, client):
        await _register(client)
        async with TestSessionLocal() as db:
            user = (await db.execute(select(User))).scalar_one()
            with pytest.raises(InvalidRequestError):
                _ = user.workflows


# --------------------------------------------------------------------- #
#  Cold start: health, background startup, lazy imports
# --------------------------------------------------------------------- #

class TestHealth:
    @pytest.mark.parametrize("path", ["/health", "/api/health"])
    async def test_liveness_never_touches_the_database(self, client, monkeypatch, path):
        def explode():
            raise AssertionError("liveness must not open a DB session")

        monkeypatch.setattr(main_module, "async_session_factory", explode)
        monkeypatch.setattr(settings, "PERF_DEBUG", True)

        resp = await client.get(path)

        assert resp.status_code == 200
        assert resp.json() == {"status": "ok"}
        assert resp.headers["x-sql-queries"] == "0"

    async def test_ready_is_503_until_startup_finishes(self, client, monkeypatch):
        monkeypatch.setattr(startup.state, "ready", False)
        resp = await client.get("/health/ready")
        assert resp.status_code == 503
        assert resp.json()["status"] == "starting"

    async def test_ready_checks_the_database_once_started(self, client, monkeypatch):
        monkeypatch.setattr(startup.state, "ready", True)
        monkeypatch.setattr(main_module, "async_session_factory", TestSessionLocal)
        resp = await client.get("/api/health/ready")
        assert resp.status_code == 200
        assert resp.json() == {"status": "ready", "database": "ok"}

    async def test_ready_reports_a_database_outage(self, client, monkeypatch):
        def broken():
            raise ConnectionError("neon is asleep")

        monkeypatch.setattr(startup.state, "ready", True)
        monkeypatch.setattr(main_module, "async_session_factory", broken)
        resp = await client.get("/health/ready")
        assert resp.status_code == 503


class TestBackgroundStartup:
    async def test_retries_until_the_database_answers(self, monkeypatch):
        attempts = []

        async def flaky():
            attempts.append(1)
            if len(attempts) < 3:
                raise ConnectionError("db waking up")
            return 0

        monkeypatch.setattr(startup, "_initialise_once", flaky)
        monkeypatch.setattr(startup, "state", startup.StartupState())
        monkeypatch.setattr(startup.asyncio, "sleep", _no_sleep)

        await startup.run_startup()

        assert len(attempts) == 3
        assert startup.state.ready and startup.state.error is None

    async def test_reaper_spares_workflows_created_after_process_start(self):
        async with TestSessionLocal() as db:
            user = User(email="o@example.com", hashed_password="x", full_name="O")
            db.add(user)
            await db.flush()
            old = Workflow(user_id=user.id, query="old", status="running", sources=[],
                           created_at=datetime.now(timezone.utc) - timedelta(hours=1))
            new = Workflow(user_id=user.id, query="new", status="pending", sources=[],
                           created_at=datetime.now(timezone.utc) + timedelta(seconds=5))
            db.add_all([old, new])
            await db.commit()
            cutoff = datetime.now(timezone.utc)

            reaped = await workflow_service.fail_interrupted_workflows(db, created_before=cutoff)

            statuses = dict((await db.execute(select(Workflow.query, Workflow.status))).all())
        assert reaped == 1
        assert statuses == {"old": "failed", "new": "pending"}

    async def test_preload_disabled_with_negative_delay(self, monkeypatch):
        imported = []
        monkeypatch.setattr(startup.importlib, "import_module", imported.append)
        await startup.preload_heavy_modules(delay=-1)
        assert imported == []

    async def test_preload_imports_heavy_modules(self, monkeypatch):
        imported = []
        monkeypatch.setattr(startup.importlib, "import_module", imported.append)
        await startup.preload_heavy_modules(delay=0)
        assert imported == list(startup.HEAVY_MODULES)


def test_boot_does_not_import_the_agent_and_rag_stack():
    """Regression guard for cold start: these cost ~4 s of the 5.6 s boot."""
    code = (
        "import sys, app.main; "
        "heavy = [m for m in ('chromadb', 'langgraph', 'google.generativeai', 'sklearn', "
        "'mlflow', 'reportlab') if m in sys.modules]; print(','.join(heavy))"
    )
    env = {"GEMINI_API_KEY": "", "PATH": ""}
    import os

    out = subprocess.run(
        [sys.executable, "-c", code], cwd=BACKEND_DIR, capture_output=True, text=True,
        env={**os.environ, **env}, timeout=120,
    )
    assert out.returncode == 0, out.stderr[-2000:]
    assert out.stdout.strip() == ""


async def _no_sleep(_seconds):
    return None


# --------------------------------------------------------------------- #
#  Neon pooled endpoint
# --------------------------------------------------------------------- #

class TestPooledEndpoint:
    def test_pooler_host_disables_prepared_statement_caches(self):
        url, args = normalize_db_url(
            "postgresql://u:p@ep-cool-123-pooler.ap-southeast-1.aws.neon.tech/db?sslmode=require"
        )
        assert "prepared_statement_cache_size=0" in url
        assert args["statement_cache_size"] == 0
        assert args["ssl"] == "require"
        a, b = args["prepared_statement_name_func"](), args["prepared_statement_name_func"]()
        assert a != b

    def test_direct_host_keeps_caches(self):
        url, args = normalize_db_url("postgresql://u:p@ep-cool-123.ap-southeast-1.aws.neon.tech/db")
        assert "prepared_statement_cache_size" not in url
        assert "statement_cache_size" not in args

    def test_pooler_detection(self):
        assert is_pooled_host("ep-x-pooler.us-east-2.aws.neon.tech")
        assert not is_pooled_host("ep-x.us-east-2.aws.neon.tech")
