"""
AgentFlow AI - Application Configuration

Loads all settings from environment variables and .env file using pydantic-settings.
"""

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings loaded from environment variables and .env file."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        # .env is shared with docker-compose (GRAFANA_*, PROMETHEUS_PORT...);
        # ignore keys this class does not model instead of refusing to start.
        extra="ignore",
        case_sensitive=False,
    )

    # Database
    DATABASE_URL: str = "sqlite+aiosqlite:///./agentflow.db"

    # AI / LLM
    GEMINI_API_KEY: str = ""
    # Model used by the insight, report, reviewer and RAG agents. Override via env
    # when Google retires a model, instead of editing five call sites.
    GEMINI_MODEL: str = "gemini-3.8-flash"
    # Per-request timeout so a hung Gemini call fails over to the fallback path
    # instead of leaving a workflow stuck in "running" forever.
    GEMINI_TIMEOUT_SECONDS: int = 90

    # JWT Authentication
    JWT_SECRET_KEY: str = "super-secret-key-change-in-production"
    JWT_ALGORITHM: str = "HS256"
    # Short-lived: the frontend refreshes it silently from the refresh cookie.
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 15

    # Refresh tokens: opaque, rotated on every use, stored hashed server side
    # (app/models/refresh_token.py) and sent only as an HttpOnly cookie.
    # The frontend (Netlify) and API (Render) are different sites, so the
    # cookie must be SameSite=None + Secure to be sent at all. Partitioned
    # (CHIPS) keys it to the frontend's site; Safari blocks third-party
    # cookies by default, so Safari users fall back to logging in again.
    REFRESH_TOKEN_EXPIRE_DAYS: int = 14
    REFRESH_COOKIE_NAME: str = "agentflow_refresh"
    REFRESH_COOKIE_PATH: str = "/api/auth"     # never sent to other endpoints
    REFRESH_COOKIE_SECURE: bool = True         # browsers treat localhost as secure
    REFRESH_COOKIE_SAMESITE: str = "none"      # "lax" when frontend and API share a site
    REFRESH_COOKIE_PARTITIONED: bool = True
    # Two tabs refreshing at the same moment both present the same token; the
    # loser would look like token theft. Within this window a just-rotated
    # token still gets an access token (but no new refresh token).
    REFRESH_REUSE_GRACE_SECONDS: int = 30
    # bcrypt cost factor for new hashes. Each step doubles the work: on
    # Render's free CPU 12 took ~1.7 s per login, 11 is ~0.85 s. 11 stays
    # above OWASP's minimum of 10. Existing hashes are upgraded or downgraded
    # transparently on the user's next successful login.
    BCRYPT_ROUNDS: int = Field(default=11, ge=10, le=15)

    # YouTube Data API
    YOUTUBE_API_KEY: str = ""

    # Reddit API
    REDDIT_CLIENT_ID: str = ""
    REDDIT_CLIENT_SECRET: str = ""
    REDDIT_USER_AGENT: str = "AgentFlow/1.0"

    # ChromaDB / RAG
    CHROMA_PERSIST_DIR: str = "./chroma_data"
    RAG_CHUNK_SIZE: int = 800          # characters per indexed chunk
    RAG_CHUNK_OVERLAP: int = 100       # character overlap between chunks
    RAG_TOP_K: int = 10                # chunks retrieved per question
    RAG_MIN_SIMILARITY: float = 0.35   # drop hits below this cosine similarity

    # Agent workflow
    MAX_REPORT_REVISIONS: int = 2      # reviewer -> report loops before auto-approve

    # Recurring schedules - polls the DB for due ScheduledTask rows.
    SCHEDULER_ENABLED: bool = True

    # Scrapers
    ALLOW_MOCK_DATA: bool = True       # fall back to synthetic data when live sources fail

    # MLflow - defaults to a local ./mlruns file store so tracking works
    # with no server; the Docker stack points this at the mlflow container.
    MLFLOW_TRACKING_URI: str = "./mlruns"
    MLFLOW_ENABLED: bool = True

    # CORS - comma-separated origins allowed to call the API.
    # The deployed frontend is included by default: defaulting to localhost
    # only means a deploy with no CORS_ORIGINS set silently blocks every
    # request from production, which is a failure that looks like the site
    # is broken rather than misconfigured.
    # "*" is development-only; credentials are disabled when it is used.
    # New deploys set this to their frontend URL (see render.yaml); the
    # existing Netlify frontend stays allowed so current production keeps
    # working when CORS_ORIGINS is unset.
    CORS_ORIGINS: str = (
        "http://localhost:5173,"
        "http://localhost:3000,"
        "https://agentflowww.netlify.app"
    )

    # Per-branch preview deploys get a generated subdomain, so they are
    # matched by pattern rather than listed. Defaults to Netlify deploy
    # previews; a Vercel deploy can use e.g. r"https://agentflow-.*\.vercel\.app"
    CORS_ORIGIN_REGEX: str = r"https://.*--agentflowww\.netlify\.app"

    # Accounts
    # The user registering with this email becomes admin. When unset, the
    # first account ever registered is made admin instead.
    ADMIN_EMAIL: str = ""

    # Public demo login ("Try the live demo"): signs visitors into one shared,
    # non-admin account. The hourly cap stops a stranger from burning through
    # the Gemini quota.
    DEMO_ENABLED: bool = True
    DEMO_EMAIL: str = "demo@agentflow.app"
    DEMO_MAX_WORKFLOWS_PER_HOUR: int = 10

    # Performance instrumentation. Workflow stage timings are always logged
    # (one "workflow_perf" line per run). PERF_DEBUG additionally returns
    # Server-Timing / X-SQL-Queries headers on every response - dev only,
    # because the timings are a side channel (e.g. bcrypt duration).
    PERF_DEBUG: bool = False
    PERF_LOG_SQL: bool = False         # with PERF_DEBUG: keep each SQL statement in the trace

    # Startup. The app answers /health as soon as uvicorn is listening; table
    # creation, the interrupted-workflow reaper and the scheduler run in the
    # background, and /health/ready reports 503 until they finish.
    DB_CREATE_ALL_ON_STARTUP: bool = True
    # Seconds after startup before the heavy agent / RAG modules (langgraph,
    # chromadb, google-generativeai: ~4 s of imports locally, far more on a
    # 0.1 vCPU host) are imported in a background thread, so the first
    # workflow does not pay for them. Delayed so a cold-start login is not
    # competing for the CPU. Negative disables the preload.
    PRELOAD_DELAY_SECONDS: float = 20.0

    # Connection pool. Recycle below Neon's 5-minute scale-to-zero so idle
    # connections are replaced before the server side has dropped them.
    DB_POOL_SIZE: int = 5
    DB_MAX_OVERFLOW: int = 5
    DB_POOL_RECYCLE_SECONDS: int = 240

    # Application
    APP_NAME: str = "AgentFlow AI"
    DEBUG: bool = False
    LOG_LEVEL: str = "INFO"


    @property
    def cors_origins(self) -> list[str]:
        """Parsed allow-list of front-end origins."""
        return [o.strip() for o in self.CORS_ORIGINS.split(",") if o.strip()]


settings = Settings()
