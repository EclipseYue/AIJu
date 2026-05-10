from functools import lru_cache
from os import getenv
from pathlib import Path

try:
    from pydantic_settings import BaseSettings, SettingsConfigDict
except ImportError:  # Allows parser smoke tests before requirements are installed.
    from pydantic import BaseModel as BaseSettings

    SettingsConfigDict = dict

# Project root: the directory containing backend/ (i.e. the repo root).
_PROJECT_ROOT = Path(__file__).resolve().parents[3]


class Settings(BaseSettings):
    app_env: str = "development"
    openai_api_key: str = ""
    openai_base_url: str = "https://api.openai.com/v1"
    llm_model: str = "gpt-4o-mini"
    anthropic_base_url: str = ""
    anthropic_auth_token: str = ""
    anthropic_model: str = ""
    anthropic_small_fast_model: str = ""
    embedding_model: str = "BAAI/bge-small-zh-v1.5"
    textbook_data_dir: str = "../textbooks"
    upload_dir: str = "data/uploads"
    chroma_dir: str = "data/chroma"
    database_path: str = "data/aiju.sqlite"
    cors_origins: list[str] = ["http://localhost:5173", "http://127.0.0.1:5173"]

    if hasattr(BaseSettings, "model_config"):
        model_config = SettingsConfigDict(
            env_file=str(_PROJECT_ROOT / ".env"),
            env_file_encoding="utf-8",
            extra="ignore",
        )

    @property
    def project_root(self) -> Path:
        return _PROJECT_ROOT

    def resolve_path(self, relative: str) -> Path:
        """Resolve a path relative to the project root."""
        return (_PROJECT_ROOT / relative).resolve()

    def __init__(self, **data: object) -> None:
        env_overrides = {
            "app_env": getenv("APP_ENV"),
            "openai_api_key": getenv("OPENAI_API_KEY"),
            "openai_base_url": getenv("OPENAI_BASE_URL"),
            "llm_model": getenv("LLM_MODEL"),
            "anthropic_base_url": getenv("ANTHROPIC_BASE_URL"),
            "anthropic_auth_token": getenv("ANTHROPIC_AUTH_TOKEN"),
            "anthropic_model": getenv("ANTHROPIC_MODEL"),
            "anthropic_small_fast_model": getenv("ANTHROPIC_SMALL_FAST_MODEL"),
            "embedding_model": getenv("EMBEDDING_MODEL"),
            "textbook_data_dir": getenv("TEXTBOOK_DATA_DIR"),
            "upload_dir": getenv("UPLOAD_DIR"),
            "chroma_dir": getenv("CHROMA_DIR"),
            "database_path": getenv("DATABASE_PATH"),
        }
        data.update({key: value for key, value in env_overrides.items() if value is not None and value != ""})
        super().__init__(**data)


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
