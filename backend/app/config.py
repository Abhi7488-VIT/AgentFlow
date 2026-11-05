"""
AgentFlow AI - Application Configuration

Loads all settings from environment variables and .env file using pydantic-settings.
"""

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
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 30

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

    # Application
    APP_NAME: str = "AgentFlow AI"
    DEBUG: bool = False
    LOG_LEVEL: str = "INFO"


    @property
    def cors_origins(self) -> list[str]:
        """Parsed allow-list of front-end origins."""
        return [o.strip() for o in self.CORS_ORIGINS.split(",") if o.strip()]


settings = Settings()
