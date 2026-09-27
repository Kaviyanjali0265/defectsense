"""
Central, validated application config — replaces scattered os.getenv() calls across
core/ and pipeline/ with one typed, fail-fast Settings object. Loads from environment
variables and .env directly (pydantic-settings reads the file itself, no python-dotenv
needed) with the exact same variable names and defaults as before, so this is a pure
refactor — no production default changes.

Deliberately scoped to core APPLICATION config (LLM provider, Redis, Qdrant, report
retention, prompt shuffling) — NOT eval-script-only flags like WITH_HISTORY,
EVAL_LIMIT, N_EVENTS, or the EVAL_HISTORY_COLLECTION* variants, which stay as plain
os.getenv() calls in their own scripts. Those are one-off tool flags for a specific
eval run, not settings the live pipeline/API/worker depend on — bundling them in here
would blur the line between "app config" and "this script's CLI-style flags."
"""
from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", case_sensitive=False, extra="ignore")

    # LLM provider — "ollama" (default, local) or "groq" (cloud, via LiteLLM)
    llm_provider: str = "ollama"
    groq_api_key: str | None = None
    groq_model: str = "llama-3.3-70b-versatile"
    # None = not explicitly set; resolved to a provider-appropriate default below,
    # exactly matching the conditional logic that used to live in pipeline/flows.py.
    llm_model: str | None = None

    # Redis (event stream + report store)
    redis_url: str = "redis://localhost:6379"

    # Qdrant (vector store) — DEFECT_HISTORY_COLLECTION overridable so eval scripts
    # can point the same search()/fetch_seen_before() machinery at an eval-only
    # collection without ever touching live data.
    qdrant_url: str = "http://localhost:6333"
    defect_history_collection: str = "defect_history"

    # Report store retention
    max_reports: int = 200

    # Candidate-shuffle salt (pipeline/prompts.py) — empty string default, unchanged
    shuffle_seed: str = ""

    # Langfuse (LLM observability, via LiteLLM's callback). None = tracing disabled
    # (default). LiteLLM's langfuse integration reads its own credentials straight
    # from os.environ, not from this object — pipeline/flows.py bridges these three
    # values into os.environ explicitly, only when both keys are present.
    langfuse_public_key: str | None = None
    langfuse_secret_key: str | None = None
    langfuse_host: str = "https://cloud.langfuse.com"

    @model_validator(mode="after")
    def _resolve_llm_model(self) -> "Settings":
        if self.llm_model is None:
            self.llm_model = self.groq_model if self.llm_provider == "groq" else "llama3.2:3b"
        return self


settings = Settings()
