from functools import lru_cache
from typing import Self

from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

#: Local development default. Anything containing this password is refused in production.
DEFAULT_DATABASE_URL = "postgresql+psycopg://playup:playup@localhost:5432/playup"
DEVELOPMENT_PASSWORD_MARKER = ":playup@"


class Settings(BaseSettings):
    app_name: str = "PlayMate Sports API"
    environment: str = "development"
    database_url: str = DEFAULT_DATABASE_URL

    #: How long a session token stays valid after it is issued.
    session_ttl_days: int = 30
    #: One-time sign-in codes must have a short, server-enforced lifetime.
    access_code_ttl_minutes: int = 5
    smtp_host: str | None = None
    smtp_port: int = 587
    smtp_username: str | None = None
    smtp_password: str | None = None
    smtp_from_email: str | None = None
    smtp_starttls: bool = True
    #: Hours before kickoff that the sweep cancels a game short of min_players.
    default_auto_cancellation_hours: int = 4

    cors_origins: list[str] = Field(default_factory=lambda: ["http://localhost:5173"])

    model_config = SettingsConfigDict(env_file=".env", env_prefix="PLAYUP_", extra="ignore")

    @property
    def is_production(self) -> bool:
        return self.environment == "production"

    @model_validator(mode="after")
    def refuse_development_credentials_in_production(self) -> Self:
        """Fail at startup rather than run a public instance on the default password."""
        if self.is_production and DEVELOPMENT_PASSWORD_MARKER in self.database_url:
            raise ValueError(
                "PLAYUP_DATABASE_URL still uses the development password; "
                "set POSTGRES_PASSWORD (see .env.example)"
            )
        return self

    @property
    def exposes_access_codes(self) -> bool:
        """Outside production the access code comes back in the response, so
        local development and tests do not need a working mailbox."""
        return not self.is_production

    @property
    def has_smtp(self) -> bool:
        return all(
            (
                self.smtp_host,
                self.smtp_username,
                self.smtp_password,
                self.smtp_from_email,
            )
        )


@lru_cache
def get_settings() -> Settings:
    return Settings()
