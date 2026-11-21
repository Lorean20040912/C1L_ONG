"""Configurația aplicației, citită din variabilele de mediu (.env)."""

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = "postgresql+psycopg://contahub:contahub@localhost:5432/contahub"
    redis_url: str = "redis://localhost:6379/0"

    jwt_secret: str = "schimba-acest-secret-in-env"
    jwt_algorithm: str = "HS256"
    access_token_minutes: int = 15
    refresh_token_days: int = 7

    cors_origins: str = "http://localhost:5173"

    # cheia Fernet pentru IDNP (app/core/crypto.py); goală = derivată din jwt_secret
    personal_data_key: str | None = None
    # cheia de criptare a datelor sensibile (IBAN-urile conturilor bancare); orice șir lung și aleator
    encryption_key: str = "schimba-cheia-de-criptare-in-env"

    # asistentul AI (Claude API); fără cheie, chatul răspunde cu un mesaj clar că nu e configurat
    anthropic_api_key: str | None = None
    ai_model: str = "claude-sonnet-5-5"

    # utilizatorul demonstrativ creat de `python -m app.seed` (doar pentru dezvoltare)
    demo_email: str | None = None
    demo_password: str | None = None

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()
