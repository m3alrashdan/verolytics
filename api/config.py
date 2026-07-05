"""Application settings, loaded from environment variables / .env."""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """All runtime configuration. Every value can be overridden via env vars."""

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # LLM
    # Provider for the agent's model calls:
    #   "openrouter" (default) — OpenRouter via its OpenAI-compatible API;
    #   "openai"               — any other OpenAI-compatible endpoint (Ollama, vLLM, LiteLLM);
    #   "anthropic"            — the native Anthropic Messages API.
    # Both OpenAI-compatible paths translate the agent's Anthropic-format
    # messages/tools to and from the OpenAI chat schema, so the rest of the
    # pipeline is unchanged regardless of provider.
    llm_provider: str = "openrouter"

    # OpenRouter (used when llm_provider == "openrouter"): OpenAI-compatible.
    # api_key comes from OPENROUTER_API_KEY; the optional HTTP-Referer / X-Title
    # headers identify the app on OpenRouter's leaderboards. The default model is
    # a strong, tool-calling model that handles Arabic well.
    openrouter_api_key: str = ""
    openrouter_base_url: str = "https://openrouter.ai/api/v1"
    openrouter_model: str = "anthropic/claude-sonnet-4.6"
    openrouter_http_referer: str = ""
    openrouter_title: str = ""

    anthropic_api_key: str = ""
    # Alternative auth for Anthropic-format gateways (e.g. OpenRouter's /api
    # endpoint): auth_token is sent as "Authorization: Bearer ..." instead of
    # x-api-key, base_url points the SDK at the gateway.
    anthropic_auth_token: str = ""
    anthropic_base_url: str = ""

    # OpenAI-compatible provider (used when llm_provider == "openai").
    # For Ollama: base_url=http://localhost:11434/v1, api_key=ollama (ignored),
    # model=a tool-capable model such as qwen2.5:7b or llama3.1:8b.
    openai_api_key: str = ""
    openai_base_url: str = ""
    openai_model: str = ""
    # NOTE: the original spec named claude-sonnet-4-20250514, which is
    # deprecated (retires 2026-06-15). claude-sonnet-4-6 is the drop-in
    # replacement — see DECISIONS.md.
    anthropic_model: str = "claude-sonnet-4-6"
    llm_max_tokens: int = 8192

    # Storage
    database_url: str = "sqlite:///./data_analyst.db"
    workspace_root: Path = Path("./workspaces")
    # When the API itself runs inside Docker, volume binds must use *host*
    # paths. Set this to the host path that workspace_root is mounted from.
    sandbox_host_workspace_root: Path | None = None

    # Sandbox
    sandbox_image: str = "data-analyst-sandbox:latest"
    sandbox_timeout_s: int = 60
    sandbox_mem_limit: str = "1g"
    sandbox_nano_cpus: int = 1_000_000_000  # 1 core
    # Cap on simultaneously-running sandbox containers across the process, so
    # concurrent analyses can't exhaust host memory/CPU/PIDs.
    max_concurrent_sandboxes: int = 4

    # Pipeline limits
    max_file_mb: int = 25
    max_rows: int = 500_000
    max_analysis_steps: int = 12
    max_step_retries: int = 3
    max_verification_attempts: int = 3
    forecast_min_points: int = 24
    enable_anomaly_investigation: bool = True
    max_anomaly_investigations: int = 2
    scenario_iterations: int = 1000

    # Reasoning engine (v3): a self-critique/reflexion pass reviews the draft
    # report against the computed results and revises it before verification.
    enable_self_critique: bool = True
    max_critique_passes: int = 1

    # Auth (built-in email + password). Tokens are opaque, stored server-side.
    token_ttl_days: int = 30

    cors_origins: list[str] = ["*"]  # lock down to your web origin(s) in production
    # Per-IP request cap per minute (0 disables). Protects cost/abuse; in-memory,
    # so a multi-process deploy needs a shared store (e.g. Redis) for a hard limit.
    rate_limit_per_minute: int = 120

    @property
    def active_model(self) -> str:
        """The model id used for the configured provider."""
        provider = (self.llm_provider or "openrouter").lower()
        if provider == "openrouter":
            return self.openrouter_model
        if provider == "openai":
            return self.openai_model or self.anthropic_model
        return self.anthropic_model

    @property
    def credentials_present(self) -> bool:
        """True when the active provider has an API key/token configured.

        Lets the app fail fast with a clear message instead of surfacing an
        opaque 401 in the middle of an analysis run.
        """
        provider = (self.llm_provider or "openrouter").lower()
        if provider == "openrouter":
            return bool(self.openrouter_api_key)
        if provider == "openai":
            # OpenAI-compatible local servers (Ollama) ignore the key, so any
            # non-empty value — including the documented placeholder — counts.
            return bool(self.openai_api_key)
        return bool(self.anthropic_api_key or self.anthropic_auth_token)

    def host_workspace(self, session_id: str) -> Path:
        root = self.sandbox_host_workspace_root or self.workspace_root.resolve()
        return Path(root) / session_id


@lru_cache
def get_settings() -> Settings:
    return Settings()
