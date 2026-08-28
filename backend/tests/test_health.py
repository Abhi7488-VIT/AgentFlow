"""Smoke test - verify the root endpoint and health check respond."""

import pytest


@pytest.mark.asyncio
async def test_root_endpoint(client):
    response = await client.get("/")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "ok"
    assert "AgentFlow" in data["name"]
