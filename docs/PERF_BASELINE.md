# AgentFlow performance baseline (Phase 0)

Measured 2026-11-05 on branch `perf-fixes`, before any optimisation. All later
phases report before/after numbers against this file.

## How it was measured

| What | How |
|---|---|
| Stage timings | `app/core/perf.py`: a `PerfTrace` per request / workflow run in a `ContextVar`. Spans around every agent node, each scraper attempt and sleep, every Gemini call (latency, ok/error, token usage incl. thinking), embedding batches, RAG upsert and the persistence transaction. Each run logs one `workflow_perf` line; MLflow gets the same numbers as `perf_*` metrics. |
| SQL per request | Engine-level `before_cursor_execute` listener counting statements per trace. With `PERF_DEBUG=true` every response carries `Server-Timing` and `X-SQL-Queries` headers (off by default: timings are a side channel). |
| Endpoints | App run in-process (httpx ASGI) against SQLite, seeded with a realistic history: N workflows x 150 scraped rows, 6 agent logs, 1 report (40 KB `full_report`) and 4 analytics rows each. Median of 5. SQLite is local, so absolute ms are a **lower bound**; Neon adds a network round trip per query. Query counts are database-independent. |
| Workflow | `execute_workflow_task` run directly, scratch SQLite + Chroma, MLflow off. *Offline* = all API keys blank (mock Reddit, fallback agents); *live* = real `.env` keys. Query: "Sony WH-1000XM5 headphones", sources reddit + youtube + amazon. |
| Boot | `python -X importtime -c "import app.main"`, warm disk cache. |
| Frontend | `npm run build`; dependency share from the sourcemap (`sourcesContent` bytes per package). |

Machine: developer laptop (Windows 11, Python 3.13). Render free is ~0.1 vCPU,
so CPU-bound numbers (bcrypt, imports, NLP, local embeddings) will be several
times slower in production.

## Results

### Login and boot

| Operation | Measured | Cause |
|---|---|---|
| `POST /api/auth/login`, 2 workflows of history | 261 ms (bcrypt 236, DB lookup 13, token 0.1), **7 SQL queries** | bcrypt cost 12, run synchronously in the `async` route: it blocks the event loop for every other request meanwhile. |
| same, 20 workflows | 328 ms (lookup **63**) | Loading `User` triggers the `lazy="selectin"` cascade (below). |
| same, 60 workflows | 582 ms (lookup **208**) | Grows linearly with the user's history. |
| bcrypt verify alone | 242 ms at cost 12 | Expect ~1 s+ on Render's shared CPU. |
| Backend import (`import app.main`) | **5.6 s** warm, 6.8-16.8 s cold disk | `app.workers.tasks` is 4.2 s of it: chromadb 1.7 s, google.generativeai 1.5 s, langgraph 0.8 s, all imported at boot through `app.api.workflows`. |
| Render cold start | not measured | The production URL is not in the repo. `agentflow-api.onrender.com` (the README example) belongs to a different service. Needs the real Render URL. |

### Page and dashboard load

Every authenticated request runs `get_current_user`, which loads `User`. `User`
has `selectin` relationships to all of the user's `workflows`, `reports` and
`agent_logs`, and each `Workflow` in turn eagerly loads all of its
`scraped_data`, `agent_logs` and `reports`. **So every authenticated request
pulls the user's entire history, including every scraped row, before the
endpoint runs.** That is 7 of the 8-13 queries below.

| Endpoint | SQL queries | p50 @ 2 wf | p50 @ 20 wf | p50 @ 60 wf | of which `auth.user_load` @ 60 |
|---|---|---|---|---|---|
| `/api/dashboard/overview` | 13 | 22 ms | 83 ms | 333 ms | 303 ms |
| `/api/dashboard/sentiment` | 8 | 16 | 81 | 328 | 194 |
| `/api/dashboard/trends` | 8 | 20 | 125 | 461 | 329 |
| `/api/dashboard/keywords` | 8 | 17 | 76 | 332 | 324 |
| `/api/dashboard/competitors` | 8 | 17 | 80 | 344 | 342 |
| `/api/dashboard/recent-activity` | 11 | 24 | 95 | 355 | 322 |
| `/api/workflows/` | 12 | 25 | 117 | 376 | 310 |
| `/api/reports/` | 9 | 18 | 79 | 319 | 190 |

- The dashboard fires 6 of these in parallel, so with 60 workflows that is 6 full history loads (about 9,000 scraped rows each) per page view.
- `overview` adds 6 separate aggregate queries on top.
- `/api/workflows/` returns 28 KB for 20 workflows (`agent_states` and `result_summary` included). `/api/reports/` returns 19 KB.
- `Workflows.tsx` polls `/api/workflows/` every 10 s, unconditionally (hidden tab, nothing running), and each poll pays the full user load.
- DB pool is already `pool_size=5, max_overflow=5, pool_pre_ping=True`, so that hypothesis is **rejected**. `pool_recycle` is not set.
- No indexes on the foreign keys yet (per the guide). Not measurable on SQLite; will verify with `EXPLAIN` on Postgres in Phase 2.

### Report generation

| Run | Total | Breakdown |
|---|---|---|
| Offline #1 (first ever) | 66 s | research 30.5 s, cleaning 0.5 s, NLP 0.4 s, LLM agents ~0 (fallbacks), **RAG upsert 34.1 s** |
| Offline #2 | 64 s | research **54.2 s** (Amazon), NLP 0.4 s, RAG upsert **8.2 s** |
| **Live** (real keys) | **369 s** | below |

Live run, stage by stage (wall clock, sequential):

| Stage | Time | What happened |
|---|---|---|
| Research (scrapers in `gather`) | 50.5 s | **Amazon 50.5 s**: tried 2 marketplaces, got HTTP 202 (bot wall) on both home pages, **24.1 s of fixed `request_delay` sleeps** (12 sleeps). YouTube 11.5 s (5.0 s of sleeps), 50 live items. Reddit returned **32 mock items** instantly (live Reddit did not work with the configured keys). |
| Cleaning + NLP | 1.0 s | Not a bottleneck (sentiment 21 ms, topics 56 ms, keywords 229 ms). |
| Insights (Gemini) | 90.3 s | Call ran **88.3 s and hit the 90 s client deadline** (504), then a 2 s sleep, then fallback insights. |
| Report (Gemini) | 99.8 s | Main call **88.8 s, 504**. 3 s sleep. Simple-prompt retry failed in 8 s with **429 daily quota**. |
| Reviewer (Gemini) | 60.5 s | 429 in 0.5 s, then a **flat 60 s sleep** although the response said `retry in 15h35m`. |
| RAG indexing (before `completed`) | 66.4 s | 5 embedding batches (6.2 s total) plus a **60 s sleep** on a 429 (embeddings cap 100/min; the response said retry in 30 s). |
| DB persistence | < 0.1 s | Not a bottleneck. |

Gemini calls in the live run: 4 generate calls (all failed) and 5 embedding batches. The worst case per workflow is 7 generate calls (insights 1, report up to 3, reviewer up to 3).

**Time actually spent waiting on fixed sleeps and timeouts: about 300 of 369 s.**

### Gemini quota (the hard constraint)

The 429 bodies give the exact limits for this key:

| Quota | Limit | Source |
|---|---|---|
| `GenerateRequestsPerDayPerProjectPerModel-FreeTier`, model `gemini-3.8-flash` | **20 requests / day** | 429 on report fallback and reviewer, `retry_delay` 56,135 s |
| `EmbedContentRequestsPerMinutePerProjectPerModel-FreeTier`, `gemini-embedding-1.0` | **100 / minute** (each text in a batch counts) | 429 on the 4th embedding batch, `retry_delay` 30 s |

At up to 7 generate calls per workflow, **20/day means roughly 3 full workflows a
day across all users** (6 if the reviewer is removed, up to 20 with one call per
workflow). The quota is per model, so routing some agents to a lighter model
draws from a separate bucket. That is a reason to do per-agent models in
Phase 3, not only for speed. The 45 s target is only reachable while quota
remains; once it is spent, the best possible outcome is a fast, clearly-flagged
fallback.

This measurement run exhausted the remaining daily quota on this key.

Not yet measured: tokens and thinking overhead per call. All four calls failed,
so there was no `usage_metadata`. The two 88 s calls ran into the deadline
before the 429s started, which is consistent with heavy thinking on long
prompts but not proven. Re-measure with the `perf` trace after the quota
resets.

### Frontend bundle

| Asset | Size | gzip |
|---|---|---|
| `index.js` (single chunk, no code splitting) | 698.5 KB | 210.7 KB |
| `index.css` | 43.5 KB | 8.0 KB |

Share of bundled source by package: **recharts 30%** (plus its deps
@reduxjs/toolkit 5.5%, decimal.js-light 2.2%, es-toolkit 1.9%, immer 1.6%,
react-redux 1.6%, d3-* ...; **about 45% in total**), react-dom 23%,
@remix-run/router 8%, axios 5.6%, app code 4%. Recharts is imported only by
`pages/Dashboard.tsx`, yet it ships to the landing and login pages. `zustand`
is a dependency with **zero imports**. No `React.lazy` anywhere.

## Hypotheses: confirmed or rejected

| Hypothesis (from the prompt) | Verdict |
|---|---|
| bcrypt blocks the event loop | **Confirmed**: about 240 ms synchronous at cost 12. |
| Heavy imports slow boot | **Confirmed**: 5.6 s, 75% from chromadb / generativeai / langgraph. |
| Render / Neon cold start | Unverified: needs the production URL. |
| Missing indexes slow lists | Unverified on SQLite. **The dominant cost is the `selectin` cascade**, which the prompt did not list. |
| Dashboard's 6 aggregates | Confirmed (13 queries), but secondary to the cascade. |
| N+1 from `lazy="selectin"` | **Confirmed, and it is the #1 page-load cause.** Not N+1 but "load everything": 7 queries and the whole history per request. |
| Pool too large for Neon | **Rejected**: already 5 / 5. |
| 10 s polling is wasteful | Confirmed: unconditional, and each poll does the full history load. |
| Up to 7 sequential Gemini calls | Confirmed. |
| Flat 60 s sleep on every 429 | **Confirmed and worse than assumed**: it also fires on *daily* caps (retry 15 h). |
| RAG indexing delays completion | **Confirmed**: 66 s live (60 s of it a sleep). 8 s offline, plus a 79 MB ONNX download on every fresh container. |
| Sequential scraper retries / backoff | Partly. Retries did not fire, but Amazon's fixed `request_delay` sleeps (24 s) and walking marketplaces after a bot wall dominate research. |
| Gemini thinking overhead | Unproven (no token data, see above). |
| NLP blocks the loop | Rejected as a bottleneck (about 0.4 s). Still worth `to_thread` on 0.1 vCPU. |
| Bundle: Recharts on every page, unused zustand | **Confirmed**. |

## Priority, by measured impact

1. Report: stop sleeping on daily caps and honour `retry_delay`; lower the 90 s Gemini timeout; move RAG indexing after `completed`; put a deadline on Amazon. Together these remove about 300 of the 369 s.
2. Every request: drop the `selectin` cascade on `User` / `Workflow`, which removes 7 queries and the whole-history load per request.
3. Login: bcrypt in `asyncio.to_thread`.
4. Boot: lazy-import chromadb, generativeai and langgraph.
5. Bundle: lazy Dashboard route so Recharts (about 45%) leaves the entry chunk; drop zustand.
