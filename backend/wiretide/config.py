"""Configuration management for the Wiretide backend."""

from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

from . import __version__


class Settings(BaseSettings):
    """Application settings loaded from environment or .env."""

    app_name: str = "Wiretide Controller"
    version: str = __version__
    database_url: str = Field(
        default="sqlite:///./wiretide.db",
        description="SQLAlchemy-compatible database URL (defaults to local SQLite).",
    )
    admin_token: str = Field(
        default="wiretide-admin-dev",
        description="Static admin token for UI/admin endpoints; override in production.",
    )
    admin_cookie_name: str = Field(
        default="wiretide_admin",
        description="Cookie name for admin session token.",
    )
    admin_cookie_secure: bool = Field(
        default=False,
        description="Set admin cookie Secure flag (enable when served over HTTPS).",
    )
    static_dir: str = Field(
        default="static", description="Directory for static assets (relative or absolute)."
    )
    templates_dir: str = Field(
        default="templates",
        description="Directory for Jinja2 templates (relative or absolute).",
    )

    model_config = SettingsConfigDict(
        env_prefix="WIRETIDE_",
        env_file=".env",
        extra="ignore",
        case_sensitive=False,
    )

    @property
    def using_sqlite(self) -> bool:
        return self.database_url.startswith("sqlite")


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
