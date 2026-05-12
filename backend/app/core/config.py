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

    # Auth
    jwt_secret: SecretStr
    jwt_algorithm: str = "HS256"
    access_token_expire_minutes: int = 30

    # Database — required; set DATABASE_URL in .env
    database_url: str

    # Knowledge base
    knowledge_base_path: str = "../knowledge-base"

    # Qdrant
    qdrant_url: str = "http://localhost:6333"
    qdrant_api_key: SecretStr | None = None
    qdrant_collection_knowledge: str = "knowledge_base"
    qdrant_collection_workouts: str = "workout_embeddings"

    # LLM routing — global defaults
    default_llm_provider: LLMProvider = LLMProvider.ANTHROPIC
    default_embedding_provider: LLMProvider = LLMProvider.OPENAI

    # RAG pipeline — per-step model routing
    # provider: None → falls back to default_llm_provider
    # model:    None → falls back to the provider's own default_model

    # Step 1: L2 intent classifier (lightweight, runs only on risk signals)
    rag_guardrail_provider: LLMProvider | None = None
    rag_guardrail_model: str | None = None

    # Step 2: query type classifier (SIMPLE / COMPLEX / COMPARISON)
    rag_classifier_provider: LLMProvider | None = None
    rag_classifier_model: str | None = None

    # Step 3: query rewriter + decomposer
    rag_rewrite_provider: LLMProvider | None = None
    rag_rewrite_model: str | None = None

    # Step 4: conflict detection LLM re-check (optional, runs on candidate pairs)
    rag_conflict_provider: LLMProvider | None = None
    rag_conflict_model: str | None = None

    # Step 5: final answer generation (most quality-sensitive step)
    rag_generation_provider: LLMProvider | None = None
    rag_generation_model: str | None = None

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
    openrouter_default_model: str = "anthropic/claude-sonnet-4-5"
    openrouter_base_url: str = "https://openrouter.ai/api/v1"
    openrouter_site_url: str = "http://localhost:3000"
    openrouter_site_name: str = "CoachAgent"
    # Per-step model defaults when using OpenRouter (overrides rag_*_model when set)
    openrouter_guardrail_model: str = "anthropic/claude-haiku-4-5"
    openrouter_classifier_model: str = "anthropic/claude-haiku-4-5"
    openrouter_rewrite_model: str = "anthropic/claude-haiku-4-5"
    openrouter_conflict_model: str = "anthropic/claude-haiku-4-5"
    openrouter_generation_model: str = "anthropic/claude-sonnet-4-5"

    # Agent (Feature 3) — coach assist agent
    agent_provider: LLMProvider | None = None  # None → default_llm_provider
    agent_model: str | None = None  # None → provider's default_model
    agent_max_iterations: int = 4
    agent_llm_timeout: float = 60.0  # seconds per complete_with_tools() call
    agent_tool_timeout: float = 45.0  # seconds per individual tool execution

    # Workout analysis — per-step model routing
    # provider: None → falls back to default_llm_provider
    # model:    None → falls back to the provider's own default_model
    workout_classifier_provider: LLMProvider | None = None
    workout_classifier_model: str | None = None
    workout_generation_provider: LLMProvider | None = None
    workout_generation_model: str | None = None
    # Per-step model defaults when using OpenRouter (overrides workout_*_model when set)
    openrouter_workout_classifier_model: str = "anthropic/claude-haiku-4-5"
    openrouter_workout_generation_model: str = "anthropic/claude-sonnet-4-5"

    # Evaluation pipeline (Feature 4) — native provider model names
    eval_faithfulness_model_anthropic: str = "claude-sonnet-4-6"
    eval_faithfulness_model_openai: str = "gpt-4o"
    eval_faithfulness_model_gemini: str = "gemini-2.5-pro"
    eval_helpfulness_model_anthropic: str = "claude-haiku-4-5-20251001"
    eval_helpfulness_model_openai: str = "gpt-4o-mini"
    eval_helpfulness_model_gemini: str = "gemini-2.0-flash"
    # OpenRouter model IDs for eval judges (used when DEFAULT_LLM_PROVIDER=openrouter)
    openrouter_eval_faithfulness_anthropic: str = "anthropic/claude-sonnet-4-5"
    openrouter_eval_faithfulness_openai: str = "openai/gpt-4o"
    openrouter_eval_faithfulness_gemini: str = "google/gemini-3.1-pro-preview"
    openrouter_eval_helpfulness_anthropic: str = "anthropic/claude-haiku-4-5"
    openrouter_eval_helpfulness_openai: str = "openai/gpt-4o-mini"
    openrouter_eval_helpfulness_gemini: str = "google/gemini-3.1-pro-preview"
    eval_dispute_threshold: float = 1.5
    eval_pass_threshold: float = 0.7

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
