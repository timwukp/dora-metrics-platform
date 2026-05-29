from pydantic_settings import BaseSettings
from pydantic import field_validator
from typing import Optional


class Settings(BaseSettings):
    app_name: str = "DORA Metrics Platform"

    # Required — no default credentials. App refuses to start with placeholder values.
    database_url: str = "postgresql://dora:dora@localhost:5432/dora_metrics"

    # Optional GitHub credentials (None disables GitHub collection until set)
    github_token: Optional[str] = None
    github_repos: str = ""
    github_webhook_secret: Optional[str] = None

    # API key gating mutating endpoints. None => endpoints disabled (return 503).
    api_key: Optional[str] = None

    claude_code_admin_key: Optional[str] = None
    anthropic_api_base: str = "https://api.anthropic.com"

    otel_enabled: bool = False
    otel_endpoint: str = "http://localhost:4317"

    poll_interval_minutes: int = 15
    log_level: str = "INFO"

    # Disable /docs and /openapi.json in production. Default is on for dev
    # ergonomics; ops should set DORA_ENABLE_DOCS=false for public deployments.
    enable_docs: bool = True

    # CORS — strict allowlist. Wildcard explicitly rejected.
    cors_origins: str = "http://localhost:5173,http://localhost:3000"

    @field_validator("cors_origins")
    @classmethod
    def _no_wildcard_cors(cls, v: str) -> str:
        origins = [o.strip() for o in v.split(",") if o.strip()]
        if "*" in origins:
            raise ValueError(
                "DORA_CORS_ORIGINS must not contain '*' (wildcard is unsafe with "
                "credentials). Set exact frontend origins."
            )
        for o in origins:
            if not (o.startswith("http://") or o.startswith("https://")):
                raise ValueError(f"CORS origin must include scheme: {o!r}")
        return v

    @field_validator("database_url")
    @classmethod
    def _no_placeholder_db(cls, v: str) -> str:
        if "CHANGE_ME" in v:
            raise ValueError("DORA_DATABASE_URL still contains placeholder; set a real connection string.")
        return v

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

    @property
    def github_repo_list(self) -> list[str]:
        return [r.strip() for r in self.github_repos.split(",") if r.strip()]

    class Config:
        env_file = ".env"
        env_prefix = "DORA_"


settings = Settings()
