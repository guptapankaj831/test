from __future__ import annotations

import logging
import os
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

# Look for `.env` in two conventional places (project root first, backend/ second).
_BACKEND_DIR = Path(__file__).resolve().parent.parent
_PROJECT_ROOT = _BACKEND_DIR.parent
_ENV_FILES: tuple[str, ...] = tuple(
    str(p) for p in (_PROJECT_ROOT / ".env", _BACKEND_DIR / ".env") if p.is_file()
)


class Settings(BaseSettings):
    """Application settings loaded from environment / .env."""

    model_config = SettingsConfigDict(
        env_file=_ENV_FILES or None,
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    openai_api_key: str = Field(..., description="OpenAI API key.")
    openai_model: str = Field("gpt-4o", description="Chat model used by every agent.")
    openai_temperature: float = Field(0.2, ge=0.0, le=2.0)

    duckduckgo_num_results: int = Field(5, ge=1, le=20)
    web_search_max_retries: int = Field(3, ge=1, le=10)

    max_iterations_default: int = Field(3, ge=1, le=10)

    log_level: str = Field("INFO")


settings = Settings()


def configure_logging() -> None:
    """Idempotent root-logger setup. Safe to call from any entrypoint."""
    root = logging.getLogger()
    if getattr(root, "_mara_configured", False):
        return
    logging.basicConfig(
        level=settings.log_level.upper(),
        format="%(asctime)s %(levelname)-5s %(name)s | %(message)s",
        datefmt="%H:%M:%S",
    )
    # Quieten chatty deps unless the user explicitly asked for debug.
    if settings.log_level.upper() != "DEBUG":
        for noisy in ("httpx", "httpcore", "openai", "urllib3", "ddgs", "primp"):
            logging.getLogger(noisy).setLevel(logging.WARNING)
    root._mara_configured = True  # type: ignore[attr-defined]


# Make the key available to libraries that read os.environ directly
# (langchain-openai falls back to OPENAI_API_KEY when none is passed).
os.environ.setdefault("OPENAI_API_KEY", settings.openai_api_key)
configure_logging()
