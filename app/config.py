"""Application configuration loaded from environment / .env file."""
from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", extra="ignore"
    )

    # Application
    APP_NAME: str = "WiFi Access Manager"
    APP_HOST: str = "0.0.0.0"
    APP_PORT: int = 8000
    APP_VERSION: str = "1.0.0-mvp"

    # Storage / security
    DATABASE_URL: str = "sqlite:///./wifi_access.db"
    SECRET_KEY: str = "change_this_secret_key"
    API_SECRET_KEY: str = "change_this_api_key"

    # First admin (seeded on first run)
    ADMIN_USERNAME: str = "admin"
    ADMIN_PASSWORD: str = "strong_password"

    # MikroTik defaults
    DEFAULT_ALLOWED_LIST: str = "allowed_clients"
    DEFAULT_GUEST_NETWORK: str = "192.168.50.0/24"
    MIKROTIK_TIMEOUT: int = 10

    # Providers
    SMS_PROVIDER: str = "mock"
    PAYMENT_PROVIDER: str = "mock"

    # Money
    DEFAULT_CURRENCY: str = "TJS"

    # OTP
    OTP_LENGTH: int = 6
    OTP_TTL_MINUTES: int = 5
    OTP_MAX_ATTEMPTS: int = 3

    # Portal behaviour: require a real DHCP lease (MAC) before registering.
    # Keep False for MVP testing without hardware.
    PORTAL_REQUIRE_LEASE: bool = False


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
