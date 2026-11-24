"""Configurația aplicației, citită din variabilele de mediu (.env)."""

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = "postgresql+psycopg://contahub:contahub@localhost:5432/contahub"
    # rolul aplicației (fără superuser/BYPASSRLS), ca politicile RLS să se aplice; migrările și seed-ul
    # folosesc `database_url` (proprietarul schemei). Gol = aplicația folosește `database_url`.
    app_database_url: str | None = None
    # crearea rolului de aplicație la migrare (parola vine din mediu)
    app_db_user: str | None = None
    app_db_password: str | None = None
    # în producție: pornirea e refuzată dacă rolul bazei de date ocolește RLS
    require_rls_role: bool = False
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

    # sincronizarea surselor de documente (nicio cheie reală în depozit: totul din mediu)
    # rădăcina permisă pentru sursele „folder pe server”; goală = folderele de pe server nu se sincronizează
    document_sync_root: str | None = None
    # cheia API Google (opțională) pentru foldere Drive partajate prin link public; goală = Drive nu se sincronizează
    google_api_key: str | None = None
    # la câte minute worker-ul verifică sursele scadente (0 = sincronizare automată oprită)
    document_sync_tick_minutes: int = 15

    # utilizatorul demonstrativ creat de `python -m app.seed` (doar pentru dezvoltare)
    demo_email: str | None = None
    demo_password: str | None = None

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()
