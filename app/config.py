"""App settings, read from environment variables or a local .env file."""
from functools import lru_cache
from pathlib import Path

import yaml
from pydantic_settings import BaseSettings, SettingsConfigDict

ROOT = Path(__file__).resolve().parent.parent


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=ROOT / ".env", extra="ignore")

    database_url: str = "sqlite:///./jobs.db"

    # LinkedIn guest search
    search_keywords: str = "AI Engineer"
    search_geo_id: str = "102713980"  # India
    search_hours: int = 6
    search_work_types: str = "1,2,3"  # 1 on-site, 2 remote, 3 hybrid
    search_pages: int = 2  # 10 jobs per page

    # LLM providers
    ai_providers: str = "gemini,gemini2,mistral,cerebras,groq"
    gemini_api_key: str = ""
    gemini_api_key_2: str = ""
    gemini_model: str = "gemini-2.5-flash"
    mistral_api_key: str = ""
    mistral_model: str = "mistral-small-latest"
    cerebras_api_key: str = ""
    cerebras_model: str = "gpt-oss-120b"
    groq_api_key: str = ""
    groq_model: str = "openai/gpt-oss-120b"

    # Telegram
    telegram_bot_token: str = ""
    telegram_chat_id: str = ""

    # Dashboard
    dashboard_password: str = ""
    webhook_secret: str = ""

    @property
    def keywords(self) -> list[str]:
        return [k.strip() for k in self.search_keywords.split(",") if k.strip()]

    @property
    def providers(self) -> list[str]:
        return [p.strip() for p in self.ai_providers.split(",") if p.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()


@lru_cache
def get_profile() -> dict:
    """My profile: experience, skills, locations, companies to skip."""
    with open(ROOT / "profile.yaml", encoding="utf-8") as f:
        return yaml.safe_load(f)
