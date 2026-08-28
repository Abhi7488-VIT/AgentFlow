# AgentFlow AI — Backend

FastAPI backend powering the AgentFlow multi-agent market intelligence platform.

## Quick Start

```bash
python -m venv venv
source venv/bin/activate  # Windows: venv\Scripts\activate
pip install -r requirements.txt
cp ../.env.example ../.env  # Edit with your API keys
uvicorn app.main:app --reload --port 8000
```

## Project Structure

```
app/
├── agents/        # LangGraph agent node definitions
├── api/           # FastAPI route handlers
├── core/          # Config, security, logging, middleware
├── models/        # SQLAlchemy ORM models
├── nlp/           # NLP pipeline (sentiment, topics, keywords, trends)
├── rag/           # RAG pipeline (embeddings, vector store, retriever)
├── schemas/       # Pydantic request/response schemas
├── scrapers/      # Data source scrapers (Amazon, YouTube, Reddit)
├── services/      # Business logic layer
├── workers/       # Background task workers
├── config.py      # App configuration (env vars)
├── database.py    # Async SQLAlchemy engine and session
└── main.py        # FastAPI application entry point
```

## Tests

```bash
python -m pytest tests/ -v
```

## API Docs

When running locally: [http://localhost:8000/docs](http://localhost:8000/docs)
