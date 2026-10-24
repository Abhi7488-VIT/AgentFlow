"""Tests for CORS configuration.

These exist because a regression here is invisible in every local test and
only shows up as "the deployed site is broken". Changing the default from
`*` to a localhost-only list silently blocked every request from the
production frontend, so the deployed origin is now asserted explicitly.
"""

import pytest

from app.config import settings

# Supplied via CORS_ORIGINS in conftest, as render.yaml does in production.
PRODUCTION_ORIGIN = "https://agentflow.example.app"


class TestConfiguredOrigins:
    def test_production_frontend_from_env_is_allowed(self):
        assert PRODUCTION_ORIGIN in settings.cors_origins

    def test_local_dev_origins_are_allowed(self):
        assert "http://localhost:5173" in settings.cors_origins

    def test_origins_are_parsed_and_trimmed(self, monkeypatch):
        monkeypatch.setattr(settings, "CORS_ORIGINS", " https://a.com , https://b.com ")
        assert settings.cors_origins == ["https://a.com", "https://b.com"]

    def test_empty_entries_are_dropped(self, monkeypatch):
        monkeypatch.setattr(settings, "CORS_ORIGINS", "https://a.com,,")
        assert settings.cors_origins == ["https://a.com"]

    def test_deploy_previews_match_the_regex(self):
        import re

        pattern = re.compile(settings.CORS_ORIGIN_REGEX)
        assert pattern.fullmatch("https://agentflow-git-feature-x.vercel.app")
        assert not pattern.fullmatch("https://evil.com")


class TestDefaults:
    """With no CORS env vars, the existing Netlify frontend must keep working."""

    def test_existing_netlify_frontend_is_allowed_by_default(self, monkeypatch):
        import re

        from app.config import Settings

        monkeypatch.delenv("CORS_ORIGINS", raising=False)
        monkeypatch.delenv("CORS_ORIGIN_REGEX", raising=False)
        defaults = Settings(_env_file=None)

        assert "https://agentflowww.netlify.app" in defaults.cors_origins
        assert re.fullmatch(
            defaults.CORS_ORIGIN_REGEX, "https://deploy-preview-1--agentflowww.netlify.app"
        )


@pytest.mark.asyncio
class TestPreflightResponses:
    """The behaviour a browser actually depends on."""

    async def test_preflight_from_production_origin_is_allowed(self, client):
        response = await client.options(
            "/api/dashboard/overview",
            headers={
                "Origin": PRODUCTION_ORIGIN,
                "Access-Control-Request-Method": "GET",
                "Access-Control-Request-Headers": "authorization",
            },
        )

        assert response.status_code == 200
        assert response.headers["access-control-allow-origin"] == PRODUCTION_ORIGIN

    async def test_preflight_from_localhost_is_allowed(self, client):
        response = await client.options(
            "/api/workflows/",
            headers={
                "Origin": "http://localhost:5173",
                "Access-Control-Request-Method": "POST",
                "Access-Control-Request-Headers": "content-type,authorization",
            },
        )

        assert response.status_code == 200
        assert response.headers["access-control-allow-origin"] == "http://localhost:5173"

    async def test_unlisted_origin_gets_no_allow_header(self, client):
        """The browser blocks the response when this header is absent."""
        response = await client.get("/", headers={"Origin": "https://evil.example.com"})

        assert "access-control-allow-origin" not in response.headers

    async def test_credentials_are_permitted_for_allowed_origins(self, client):
        response = await client.get("/", headers={"Origin": PRODUCTION_ORIGIN})

        assert response.headers.get("access-control-allow-credentials") == "true"
        assert response.headers["access-control-allow-origin"] == PRODUCTION_ORIGIN
