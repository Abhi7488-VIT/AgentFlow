"""End-to-end tests for the Ask AI flow over the HTTP API.

Ingestion (stored scraped rows -> chunks -> embeddings -> vector store),
retrieval, grounded answer generation, and the access rules around them.
The suite stays offline: Chroma, the Gemini embedder and the Gemini model
are replaced with small in-memory fakes that behave like the real ones.
"""

import math
import re

import pytest

from app.config import settings
from app.models.scraped_data import ScrapedData
from app.models.workflow import Workflow
from app.rag import retriever as retriever_module
from app.rag.embeddings import EmbeddingGenerator
from app.rag.vectorstore import VectorStore
from tests.conftest import TestSessionLocal

PASSWORD = "Correct-Horse-Battery9"

CORPUS = [
    ("reddit", "The battery drains really fast when gaming, barely lasts four hours."),
    ("amazon", "Battery life is poor, it drains overnight even in standby."),
    ("youtube", "The camera is excellent in low light, best photos I have taken."),
]


def _embed(text: str) -> list[float]:
    """Deterministic bag-of-words vector over a tiny fixed vocabulary."""
    vocab = ["battery", "drains", "camera", "photos", "light", "gaming", "screen"]
    words = re.findall(r"[a-z]+", text.lower())
    vec = [float(sum(w.startswith(v) for w in words)) for v in vocab]
    norm = math.sqrt(sum(v * v for v in vec)) or 1.0
    return [v / norm for v in vec]


class FakeStore:
    """In-memory stand-in for the Chroma-backed VectorStore."""

    def __init__(self):
        self.collections: dict[str, list[tuple[str, dict, list[float]]]] = {}

    async def add_documents(self, collection_name, texts, metadatas, ids, embeddings=None):
        rows = self.collections.setdefault(collection_name, [])
        for text, meta, emb in zip(texts, metadatas, embeddings or [_embed(t) for t in texts]):
            rows.append((text, meta, emb))
        return True

    async def count(self, collection_name):
        return len(self.collections.get(collection_name, []))

    async def search(self, collection_name, query_texts=None, query_embeddings=None, n_results=5):
        query = query_embeddings[0] if query_embeddings else _embed(query_texts[0])
        scored = sorted(
            (1.0 - sum(a * b for a, b in zip(query, emb)), text, meta)
            for text, meta, emb in self.collections.get(collection_name, [])
        )[:n_results]
        return {
            "documents": [[s[1] for s in scored]],
            "metadatas": [[s[2] for s in scored]],
            "distances": [[s[0] for s in scored]],
        }


class FakeModel:
    """Records the prompt and answers with a citation, like Gemini would."""

    def __init__(self, fail: bool = False):
        self.prompts: list[str] = []
        self.fail = fail

    async def generate_content_async(self, prompt, request_options=None):
        self.prompts.append(prompt)
        if self.fail:
            raise ValueError("model exploded")

        class Response:
            text = "Battery drain is the top complaint [1][2]."

        return Response()


@pytest.fixture
def rag(monkeypatch):
    store = FakeStore()
    model = FakeModel()

    for name in ("add_documents", "count", "search"):
        monkeypatch.setattr(VectorStore, name, lambda self, *a, _n=name, **k: getattr(store, _n)(*a, **k))

    async def fake_generate(self, texts, task_type="retrieval_document"):
        return [_embed(t) for t in texts]

    monkeypatch.setattr(EmbeddingGenerator, "generate", fake_generate)
    monkeypatch.setattr(EmbeddingGenerator, "is_available", property(lambda self: True))
    monkeypatch.setattr(EmbeddingGenerator, "model_name", property(lambda self: "fake-embedder"))

    monkeypatch.setattr(settings, "GEMINI_API_KEY", "test-key")
    monkeypatch.setattr(settings, "RAG_MIN_SIMILARITY", 0.3)
    monkeypatch.setattr(retriever_module.genai, "configure", lambda **kw: None)
    monkeypatch.setattr(retriever_module.genai, "GenerativeModel", lambda *a, **k: model)
    return store, model


async def _user(client, email: str) -> dict:
    await client.post(
        "/api/auth/register",
        json={"email": email, "password": PASSWORD, "full_name": "T"},
    )
    resp = await client.post("/api/auth/login", data={"username": email, "password": PASSWORD})
    body = resp.json()
    return {"id": body["user"]["id"], "headers": {"Authorization": f"Bearer {body['access_token']}"}}


async def _workflow_with_data(user_id, rows=CORPUS) -> str:
    import uuid

    async with TestSessionLocal() as db:
        wf = Workflow(user_id=uuid.UUID(user_id), query="phone", sources=["reddit"], status="completed")
        db.add(wf)
        await db.commit()
        await db.refresh(wf)
        for source, content in rows:
            db.add(ScrapedData(workflow_id=wf.id, source=source, content=content))
        await db.commit()
        return str(wf.id)


@pytest.mark.asyncio
class TestAskFlow:
    async def test_index_then_ask_returns_a_grounded_cited_answer(self, client, rag):
        _, model = rag
        owner = await _user(client, "owner@example.com")
        wf = await _workflow_with_data(owner["id"])

        status = await client.get(f"/api/rag/status/{wf}", headers=owner["headers"])
        assert status.json()["queryable"] is False

        built = await client.post("/api/rag/index", params={"workflow_id": wf}, headers=owner["headers"])
        assert built.status_code == 200
        assert built.json()["documents"] == 3

        status = await client.get(f"/api/rag/status/{wf}", headers=owner["headers"])
        assert status.json() == {**status.json(), "indexed_chunks": 3, "queryable": True}

        resp = await client.post(
            "/api/rag/query",
            json={"question": "Why does the battery drain?", "workflow_id": wf},
            headers=owner["headers"],
        )
        body = resp.json()

        assert resp.status_code == 200
        assert "[1]" in body["answer"]
        sources = {s["metadata"]["source"] for s in body["sources"]}
        assert sources == {"reddit", "amazon"}, "the off-topic camera review must be filtered out"
        assert body["confidence"] > 0

        prompt = model.prompts[-1]
        assert "drains" in prompt and "camera" not in prompt
        assert "untrusted" in prompt.lower()

    async def test_question_the_data_does_not_cover_is_declined(self, client, rag):
        _, model = rag
        owner = await _user(client, "owner@example.com")
        wf = await _workflow_with_data(owner["id"])
        await client.post("/api/rag/index", params={"workflow_id": wf}, headers=owner["headers"])

        resp = await client.post(
            "/api/rag/query",
            json={"question": "How is the screen?", "workflow_id": wf},
            headers=owner["headers"],
        )

        assert resp.json()["answer"] == retriever_module.NO_CONTEXT_ANSWER
        assert resp.json()["sources"] == []
        assert model.prompts == [], "no LLM call when nothing relevant was retrieved"

    async def test_unindexed_workflow_is_declined(self, client, rag):
        owner = await _user(client, "owner@example.com")
        wf = await _workflow_with_data(owner["id"])

        resp = await client.post(
            "/api/rag/query",
            json={"question": "battery?", "workflow_id": wf},
            headers=owner["headers"],
        )

        assert resp.json()["answer"] == retriever_module.NO_CONTEXT_ANSWER

    async def test_indexing_a_workflow_without_data_is_a_conflict(self, client, rag):
        owner = await _user(client, "owner@example.com")
        wf = await _workflow_with_data(owner["id"], rows=[])

        resp = await client.post("/api/rag/index", params={"workflow_id": wf}, headers=owner["headers"])

        assert resp.status_code == 409

    async def test_model_failure_still_returns_the_evidence(self, client, rag):
        _, model = rag
        model.fail = True
        owner = await _user(client, "owner@example.com")
        wf = await _workflow_with_data(owner["id"])
        await client.post("/api/rag/index", params={"workflow_id": wf}, headers=owner["headers"])

        resp = await client.post(
            "/api/rag/query",
            json={"question": "battery drains?", "workflow_id": wf},
            headers=owner["headers"],
        )

        assert resp.status_code == 200
        assert "drains" in resp.json()["answer"]
        assert resp.json()["sources"]


@pytest.mark.asyncio
class TestAskAccess:
    async def test_other_users_workflow_is_forbidden(self, client, rag):
        owner = await _user(client, "owner@example.com")
        stranger = await _user(client, "stranger@example.com")
        wf = await _workflow_with_data(owner["id"])

        for call in (
            client.post("/api/rag/query", json={"question": "battery?", "workflow_id": wf}, headers=stranger["headers"]),
            client.post("/api/rag/index", params={"workflow_id": wf}, headers=stranger["headers"]),
            client.get(f"/api/rag/status/{wf}", headers=stranger["headers"]),
        ):
            assert (await call).status_code == 403

    async def test_non_admin_must_name_a_workflow(self, client, rag):
        await _user(client, "owner@example.com")  # first account is admin
        viewer = await _user(client, "viewer@example.com")

        resp = await client.post("/api/rag/query", json={"question": "battery?"}, headers=viewer["headers"])

        assert resp.status_code == 400

    async def test_anonymous_is_rejected(self, client, rag):
        resp = await client.post("/api/rag/query", json={"question": "battery?"})

        assert resp.status_code == 401

    @pytest.mark.parametrize("question", ["", "x" * 501])
    async def test_question_length_is_bounded(self, client, rag, question):
        owner = await _user(client, "owner@example.com")
        wf = await _workflow_with_data(owner["id"])

        resp = await client.post(
            "/api/rag/query", json={"question": question, "workflow_id": wf}, headers=owner["headers"]
        )

        assert resp.status_code == 422
