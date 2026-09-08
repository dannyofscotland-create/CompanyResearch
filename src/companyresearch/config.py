from __future__ import annotations

from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    openai_api_key: str = ""
    openai_base_url: str = "https://api.openai.com/v1"
    llm_model: str = "gpt-4o-mini"
    ollama_host: str = "http://127.0.0.1:11434"
    ollama_model: str = "llama3.1"
    sec_user_agent: str = "CompanyResearch/0.1 (local research tool; you@example.com)"
    ssl_verify: bool = True
    host: str = "127.0.0.1"
    port: int = 8787
    # Wallet + cache live here. On a VPS set COMPANYRESEARCH_DATA=/data so a reboot keeps the pretend scoreboard.
    data_dir: Path = Path(".cache")
    # Required on the public internet so strangers cannot wipe your pretend wallet. Empty = open on localhost.
    access_code: str = ""


settings = Settings()
settings.data_dir.mkdir(parents=True, exist_ok=True)
