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
    # Fernet key for encrypting MikroTik passwords at rest. If empty, a key is
    # derived from SECRET_KEY. Generate a dedicated one with:
    #   python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
    ENCRYPTION_KEY: str = ""

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

    # ----- Stage 2: speed / traffic limits on MikroTik -----
    # Apply per-tariff speed limits via MikroTik simple queues on activation.
    APPLY_QUEUES: bool = True
    QUEUE_PREFIX: str = "wam"  # simple-queue name prefix: wam-<client_id>

    # ----- Stage 2: in-app scheduler (APScheduler) -----
    SCHEDULER_ENABLED: bool = True
    EXPIRE_INTERVAL_MINUTES: int = 10
    # Periodic traffic-quota enforcement (reads simple-queue byte counters).
    TRAFFIC_CHECK_ENABLED: bool = False
    TRAFFIC_CHECK_INTERVAL_MINUTES: int = 15

    # ----- Stage 2: generic HTTP SMS provider -----
    # SMS_PROVIDER=mock (default) or http
    SMS_API_URL: str = ""
    SMS_API_KEY: str = ""
    SMS_API_METHOD: str = "POST"          # GET | POST
    SMS_API_AUTH_HEADER: str = "Authorization"  # header name for the key
    SMS_API_AUTH_PREFIX: str = "Bearer "  # prefix before the key value
    SMS_SENDER: str = ""                   # optional sender/from
    SMS_PHONE_PARAM: str = "phone"         # request field for the phone
    SMS_TEXT_PARAM: str = "text"           # request field for the message
    SMS_SENDER_PARAM: str = "from"         # request field for the sender
    SMS_EXTRA_PARAMS: str = ""             # optional JSON of extra fields
    SMS_JSON_BODY: bool = True             # POST as JSON (True) or form (False)

    # ----- Stage 2: generic HTTP payment provider -----
    # PAYMENT_PROVIDER=mock (default) or http
    PAYMENT_API_URL: str = ""             # endpoint to create a payment
    PAYMENT_API_KEY: str = ""
    PAYMENT_API_AUTH_HEADER: str = "Authorization"
    PAYMENT_API_AUTH_PREFIX: str = "Bearer "
    PAYMENT_RETURN_URL: str = ""          # where the user returns after paying
    PAYMENT_CALLBACK_URL: str = ""        # provider -> our /api/payments/webhook
    PAYMENT_PAY_URL_FIELD: str = "payment_url"  # field with the redirect URL
    PAYMENT_ID_FIELD: str = "id"          # field with the provider payment id

    # Public base URL of this app (used to build return/callback URLs).
    PUBLIC_BASE_URL: str = ""

    # ----- Stage 3: captive portal redirect -----
    # When enabled, any request that is not an app path (foreign Host / unknown
    # path, e.g. intercepted by MikroTik dst-nat or OS captive probes) is
    # redirected to the portal so the "Sign in to network" popup appears.
    CAPTIVE_REDIRECT_ENABLED: bool = False
    # Absolute URL to redirect to. If empty, PUBLIC_BASE_URL + /portal is used.
    CAPTIVE_PORTAL_URL: str = ""


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
