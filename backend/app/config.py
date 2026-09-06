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
        case_sensitive=False,
    )

    # Database
    DATABASE_URL: str = "sqlite+aiosqlite:///./agentflow.db"

    # AI / LLM
    GEMINI_API_KEY: str = ""

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
    CORS_ORIGINS: str = (
        "http://localhost:5173,"
        "http://localhost:3000,"
        "https://agentflowww.netlify.app"
    )

    # Netlify deploy previews get a generated subdomain per PR, so they are
    # matched by pattern rather than listed.
    CORS_ORIGIN_REGEX: str = r"https://.*--agentflowww\.netlify\.app"

    # Application
    APP_NAME: str = "AgentFlow AI"
    DEBUG: bool = False
    LOG_LEVEL: str = "INFO"


    @property
    def cors_origins(self) -> list[str]:
        """Parsed allow-list of front-end origins."""
        return [o.strip() for o in self.CORS_ORIGINS.split(",") if o.strip()]


settings = Settings()
