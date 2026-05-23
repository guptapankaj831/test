import logging
import os
from pathlib import Path
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

# Look for `.env` in two conventional places (project root first, backend/ second).
_BACKEND_DIR = Path(__file__).resolve().parent.parent
_PROJECT_ROOT = _BACKEND_DIR.parent
_ENV_FILES: tuple[str, ...] = tuple(
    str(p) for p in (_PROJECT_ROOT / '.env', _BACKEND_DIR / '.env') if p.is_file()
)


class Settings(BaseSettings):
    """Application settings loaded from environment / .env."""

    model_config = SettingsConfigDict(
        env_file=_ENV_FILES or None,
        env_file_encoding='utf-8',
        case_sensitive=False,
        extra='ignore'
    )

    openai_api_key: str = Field(..., description="OpenAI API key used for chat and embeddings.")
    openai_model: str = Field('gpt-4o', description="Chat model used for SQL generation and schema description.")
    openai_temperature: float = Field(.1, ge=0.0, le=2.0, description="Sampling temperature. 0.1 keeps SQL generation deterministic.")
    openai_embedding_model: str = Field('text-embedding-3-small', description="Embedding model for schema descriptions and user questions.")

    mysql_host: str = Field(..., description="MySQL hostname (e.g. 'localhost' locally, 'mysql' inside Compose).")
    mysql_port: int = Field(3306, description="MySQL TCP port.")
    mysql_db: str = Field(..., description="Database the app queries (e.g. 'sakila').")
    mysql_user: str = Field(..., description="Application MySQL user — must have SELECT-only privileges, never root.")
    mysql_password: str = Field(..., description="Password for the read-only MySQL user.")

    chroma_persist_dir: str = Field("./chroma_data", description="Directory where ChromaDB persists the schema index (mount as a volume in Docker).")
    chroma_collection_name: str = Field('schema_index', description="Name of the ChromaDB collection holding schema embeddings.")
    retrieval_top_k: int = Field(10, ge=1, le=50, description="Number of schema chunks (tables + columns) retrieved per question.")
    sql_validation_max_retries: int = Field(1, description="Retries allowed after a SQL validation (AST) failure.")
    sql_execution_max_retries: int = Field(2, description="Retries allowed after a SQL execution (DB) failure.")
    statement_timeout_ms: int = Field(15000, description="MySQL statement timeout in ms. Caps runaway queries.")
    result_row_cap: int = Field(1000, description="Hard cap on rows returned from any executed query.")

    log_level: str = Field('INFO', description="Root logger level (DEBUG / INFO / WARNING / ERROR).")


settings = Settings()


def configure_logging() -> None:
    """Idempotent root-logger setup. Safe to call from any entrypoint."""

    root = logging.getLogger()
    if getattr(root, '_mara_configured', False):
        return

    logging.basicConfig(
        level=settings.log_level.upper(),
        format='%(asctime)s %(levelname)-5s %(name)s | %(message)s',
        datefmt='%H:%M:%S'
    )

    if settings.log_level.upper() != 'DEBUG':
        for noisy in ("httpx", "httpcore", "openai", "urllib3", "chromadb", "sqlalchemy.engine"):
            logging.getLogger(noisy).setLevel(logging.WARNING)

    root._mara_configured = True

os.environ.setdefault("OPENAI_API_KEY", settings.openai_api_key)
configure_logging()
