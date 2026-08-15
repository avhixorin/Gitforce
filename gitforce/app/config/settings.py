from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="GITFORCE_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # App
    env: str = "development"
    debug: bool = True
    host: str = "0.0.0.0"
    port: int = 8000

    # Database
    database_url: str = (
        "postgresql+asyncpg://gitforce:gitforce@localhost:5432/gitforce"
    )

    # Redis
    redis_url: str = "redis://localhost:6379/0"

    # GitHub
    github_app_id: str | None = None
    github_app_private_key_path: str | None = None
    github_app_installation_id: str | None = None
    github_token: str | None = None

    # LLM
    llm_provider: str = "openai"
    openai_api_key: str | None = None
    anthropic_api_key: str | None = None
    google_api_key: str | None = None
    groq_api_key: str | None = None
    local_llm_base_url: str | None = None
    local_llm_api_key: str | None = None

    # Model routing defaults
    model_fast: str = "gpt-4o-mini"
    model_coding: str = "gpt-4o"
    model_reasoning: str = "gpt-4o"
    model_judge: str = "gpt-4o"

    # Retrieval
    embedding_provider: str = "hash"  # hash | openai | local
    embedding_model: str = "text-embedding-3-small"
    embedding_dimensions: int = 1536
    rag_max_chunks: int = 2000
    rag_top_k: int = 8

    # Observability
    otel_enabled: bool = False
    otel_exporter_otlp_endpoint: str | None = None
    langsmith_api_key: str | None = None

    # Execution / Sandbox
    sandbox_backend: str = "docker"
    sandbox_network_restricted: bool = True
    sandbox_cpu_limit: float = 2.0
    sandbox_memory_limit: str = "2g"
    sandbox_timeout_seconds: int = 600
    sandbox_image: str = "python:3.12-slim"

    # Workflow
    max_fix_iterations: int = 5
    max_workflow_iterations: int = 10
    max_feedback_iterations: int = 3
    agent_timeout_seconds: int = 600
    agent_max_iterations: int = 20
    auto_discover: bool = True
    workspace_root: str = "workspaces"

    # Security / Rate limiting (Phase 12)
    rate_limit_enabled: bool = True
    rate_limit_requests_per_minute: int = 120
    rate_limit_burst: int = 200
    structured_logging: bool = True
    enable_secret_management: bool = True

    @property
    def is_development(self) -> bool:
        return self.env.lower() == "development"


@lru_cache
def get_settings() -> Settings:
    return Settings()