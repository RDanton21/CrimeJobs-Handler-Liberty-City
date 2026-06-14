from pathlib import Path
from pydantic_settings import BaseSettings, SettingsConfigDict

ROOT_DIR = Path(__file__).resolve().parent.parent


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=str(ROOT_DIR / ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    discord_bot_token: str = ""
    discord_guild_id: str = ""

    anthropic_api_key: str = ""
    openai_api_key: str = ""

    default_ai_provider: str = "anthropic"
    default_claude_model: str = "claude-sonnet-4-6"
    default_openai_model: str = "gpt-4o"

    host: str = "127.0.0.1"
    port: int = 8000

    admin_username: str = "admin"
    admin_password: str = "change-me"

    database_url: str = f"sqlite+aiosqlite:///{(ROOT_DIR / 'data' / 'crime.db').as_posix()}"
    image_dir: str = str(ROOT_DIR / "data" / "images")

    # Container-Networking: in Docker zeigt das auf den Bot-Container.
    # Lokal/Windows-NSSM: localhost. Im docker-compose: "http://crime-bot:8001".
    bot_api_url: str = "http://127.0.0.1:8001"

    # Bot-eigene HTTP-API-Bindings (für den Bot-Prozess selbst).
    bot_api_host: str = "127.0.0.1"
    bot_api_port: int = 8001

    # Override für DB-Pfad (Container nutzt /app/data/crime.db).
    db_path: str = ""


settings = Settings()

# Falls DB_PATH per ENV gesetzt ist (Docker), override database_url
if settings.db_path:
    settings.database_url = f"sqlite+aiosqlite:///{settings.db_path}"
