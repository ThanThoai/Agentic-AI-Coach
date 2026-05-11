from enum import StrEnum
from pydantic import SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class LLMProvider(StrEnum):
    ANTHROPIC = "anthropic"
    OPENAI = "openai"
    GEMINI = "gemini"
    GROK = "grok"
    OPENROUTER = "openrouter"


class AppEnv(StrEnum):
    DEVELOPMENT = "development"
    TEST = "test"
    PRODUCTION = "production"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # App
    app_env: AppEnv = AppEnv.DEVELOPMENT
    log_level: str = "INFO"
    allowed_origins: list[str] = ["http://localhost:3000"]

    # Database
    database_url: str
    redis_url: str = "redis://localhost:6379/0"

    # Auth
    jwt_secret: SecretStr
    jwt_algorithm: str = "HS256"
    access_token_expire_minutes: int = 30

    # Knowledge base
    knowledge_base_path: str = "../knowledge-base"

    # Qdrant
    qdrant_url: str = "http://localhost:6333"
    qdrant_api_key: SecretStr | None = None
    qdrant_collection_knowledge: str = "knowledge_base"
    qdrant_collection_workouts: str = "workout_embeddings"

    # LLM routing
    default_llm_provider: LLMProvider = LLMProvider.ANTHROPIC
    default_embedding_provider: LLMProvider = LLMProvider.OPENAI

    # Anthropic
    anthropic_api_key: SecretStr | None = None
    anthropic_default_model: str = "claude-sonnet-4-6"

    # OpenAI
    openai_api_key: SecretStr | None = None
    openai_default_model: str = "gpt-4o"
    openai_embedding_model: str = "text-embedding-3-small"

    # Gemini
    gemini_api_key: SecretStr | None = None
    gemini_default_model: str = "gemini-1.5-pro"

    # Grok (xAI) — OpenAI-compatible
    grok_api_key: SecretStr | None = None
    grok_default_model: str = "grok-beta"
    grok_base_url: str = "https://api.x.ai/v1"

    # OpenRouter
    openrouter_api_key: SecretStr | None = None
    openrouter_default_model: str = "anthropic/claude-3.5-sonnet"
    openrouter_base_url: str = "https://openrouter.ai/api/v1"
    openrouter_site_url: str = "http://localhost:3000"
    openrouter_site_name: str = "CoachAgent"

    @field_validator("jwt_secret", mode="before")
    @classmethod
    def jwt_secret_min_length(cls, v: str) -> str:
        if len(v) < 32:
            raise ValueError("JWT_SECRET must be at least 32 characters")
        return v

    def get_api_key(self, provider: LLMProvider) -> str:
        """Return the API key for a provider, raising clearly if unset."""
        key_map: dict[LLMProvider, SecretStr | None] = {
            LLMProvider.ANTHROPIC: self.anthropic_api_key,
            LLMProvider.OPENAI: self.openai_api_key,
            LLMProvider.GEMINI: self.gemini_api_key,
            LLMProvider.GROK: self.grok_api_key,
            LLMProvider.OPENROUTER: self.openrouter_api_key,
        }
        secret = key_map[provider]
        if secret is None:
            raise RuntimeError(
                f"API key for provider '{provider}' is not configured. "
                f"Set {provider.upper()}_API_KEY in .env."
            )
        return secret.get_secret_value()


settings = Settings()
