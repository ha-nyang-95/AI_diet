from __future__ import annotations

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # --- Infra (docker-compose에서 주입) ---
    database_url: str = "postgresql+asyncpg://app:app@postgres:5432/app"
    redis_url: str = "redis://redis:6379/0"

    # --- LLM ---
    openai_api_key: str = ""
    anthropic_api_key: str = ""

    # --- LangSmith ---
    langsmith_api_key: str = ""
    langsmith_project: str = "balancenote-dev"
    langchain_tracing_v2: bool = False

    # --- JWT (사용자 / 관리자 분리) ---
    jwt_user_secret: str = "dev-user-secret-please-rotate"
    jwt_admin_secret: str = "dev-admin-secret-please-rotate"
    jwt_user_issuer: str = "balancenote-user"
    jwt_admin_issuer: str = "balancenote-admin"

    # --- Sentry ---
    sentry_dsn: str = ""

    # --- Google OAuth ---
    google_oauth_client_id: str = ""
    google_oauth_client_secret: str = ""

    # --- Cloudflare R2 ---
    r2_account_id: str = ""
    r2_access_key_id: str = ""
    r2_secret_access_key: str = ""
    r2_bucket: str = "balancenote-meals"
    r2_public_base_url: str = ""

    # --- Expo ---
    expo_access_token: str = ""

    # --- 식약처 OpenAPI ---
    mfds_openapi_key: str = ""

    # --- 결제 ---
    toss_secret_key: str = ""

    # --- 환경 ---
    environment: str = Field(default="dev", description="dev | staging | prod")


settings = Settings()
