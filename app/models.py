"""SQLAlchemy ORM models and shared status constants."""
import datetime as dt

from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
)
from sqlalchemy.orm import relationship

from .crypto import EncryptedString
from .database import Base


def utcnow() -> dt.datetime:
    return dt.datetime.utcnow()


# ---------------------------------------------------------------------------
# Client status codes
# ---------------------------------------------------------------------------
STATUS_INACTIVE = 0
STATUS_ACTIVE = 1
STATUS_PENDING_PAYMENT = 2
STATUS_EXPIRED = 3
STATUS_BLOCKED = 4

CLIENT_STATUS_LABELS = {
    0: "inactive",
    1: "active",
    2: "pending_payment",
    3: "expired",
    4: "blocked",
}

# Bootstrap colour classes per status (active=green, inactive=red, etc.)
CLIENT_STATUS_COLORS = {
    0: "danger",     # red
    1: "success",    # green
    2: "warning",    # yellow
    3: "secondary",  # gray
    4: "dark",       # dark red / black
}

PAYMENT_STATUS_COLORS = {
    "pending": "warning",
    "paid": "success",
    "failed": "danger",
    "cancelled": "secondary",
    "expired": "secondary",
}


class AdminUser(Base):
    __tablename__ = "admin_users"

    id = Column(Integer, primary_key=True)
    username = Column(String(100), unique=True, nullable=False, index=True)
    password_hash = Column(String(255), nullable=False)
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=utcnow)
    updated_at = Column(DateTime, default=utcnow, onupdate=utcnow)


class MikroTikDevice(Base):
    __tablename__ = "mikrotik_devices"

    id = Column(Integer, primary_key=True)
    name = Column(String(120), nullable=False)
    host = Column(String(120), nullable=False)
    port = Column(Integer, default=8728)
    username = Column(String(120), nullable=False)
    # Encrypted at rest (Fernet). Legacy plaintext values still decrypt as-is.
    password = Column(EncryptedString(512), nullable=False)
    use_ssl = Column(Boolean, default=False)
    is_active = Column(Boolean, default=False)
    comment = Column(Text, nullable=True)
    created_at = Column(DateTime, default=utcnow)
    updated_at = Column(DateTime, default=utcnow, onupdate=utcnow)
    last_checked_at = Column(DateTime, nullable=True)
    last_status = Column(String(50), nullable=True)
    last_error = Column(Text, nullable=True)

    clients = relationship("Client", back_populates="mikrotik")


class Tariff(Base):
    __tablename__ = "tariffs"

    id = Column(Integer, primary_key=True)
    name = Column(String(120), nullable=False)
    description = Column(Text, nullable=True)
    price = Column(Float, default=0.0)
    currency = Column(String(10), default="TJS")
    speed_limit = Column(String(50), nullable=True)
    traffic_limit = Column(String(50), nullable=True)
    validity_days = Column(Integer, default=1)
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=utcnow)
    updated_at = Column(DateTime, default=utcnow, onupdate=utcnow)

    clients = relationship("Client", back_populates="tariff")
    payments = relationship("Payment", back_populates="tariff")


class Client(Base):
    __tablename__ = "clients"

    id = Column(Integer, primary_key=True)
    phone = Column(String(30), index=True, nullable=False)
    phone_verified = Column(Boolean, default=False)
    # MAC/IP are taken automatically from the MikroTik DHCP lease, never typed
    # by the client.
    mac_address = Column(String(30), index=True, nullable=True)
    ip_address = Column(String(45), index=True, nullable=True)
    hostname = Column(String(120), nullable=True)
    status = Column(Integer, default=STATUS_INACTIVE)
    tariff_id = Column(Integer, ForeignKey("tariffs.id"), nullable=True)
    mikrotik_id = Column(Integer, ForeignKey("mikrotik_devices.id"), nullable=True)
    created_at = Column(DateTime, default=utcnow)
    updated_at = Column(DateTime, default=utcnow, onupdate=utcnow)
    activated_at = Column(DateTime, nullable=True)
    deactivated_at = Column(DateTime, nullable=True)
    expires_at = Column(DateTime, nullable=True)
    # Last time the device was seen in a DHCP lease / portal interaction.
    last_seen = Column(DateTime, nullable=True)
    comment = Column(Text, nullable=True)

    tariff = relationship("Tariff", back_populates="clients")
    mikrotik = relationship("MikroTikDevice", back_populates="clients")
    payments = relationship("Payment", back_populates="client")

    @property
    def status_label(self) -> str:
        return CLIENT_STATUS_LABELS.get(self.status, "unknown")

    @property
    def status_color(self) -> str:
        return CLIENT_STATUS_COLORS.get(self.status, "secondary")


class OTPCode(Base):
    __tablename__ = "otp_codes"

    id = Column(Integer, primary_key=True)
    phone = Column(String(30), index=True, nullable=False)
    code_hash = Column(String(255), nullable=False)
    expires_at = Column(DateTime, nullable=False)
    is_used = Column(Boolean, default=False)
    attempts = Column(Integer, default=0)
    created_at = Column(DateTime, default=utcnow)


class SMSLog(Base):
    __tablename__ = "sms_logs"

    id = Column(Integer, primary_key=True)
    phone = Column(String(30), index=True)
    message = Column(Text)
    provider = Column(String(50))
    status = Column(String(50))
    error_message = Column(Text, nullable=True)
    created_at = Column(DateTime, default=utcnow)


class Payment(Base):
    __tablename__ = "payments"

    id = Column(Integer, primary_key=True)
    client_id = Column(Integer, ForeignKey("clients.id"), nullable=True)
    tariff_id = Column(Integer, ForeignKey("tariffs.id"), nullable=True)
    amount = Column(Float, default=0.0)
    currency = Column(String(10), default="TJS")
    provider = Column(String(50))
    provider_payment_id = Column(String(120), nullable=True)
    status = Column(String(20), default="pending")
    created_at = Column(DateTime, default=utcnow)
    paid_at = Column(DateTime, nullable=True)
    error_message = Column(Text, nullable=True)

    client = relationship("Client", back_populates="payments")
    tariff = relationship("Tariff", back_populates="payments")


class AccessLog(Base):
    __tablename__ = "access_logs"

    id = Column(Integer, primary_key=True)
    client_id = Column(Integer, ForeignKey("clients.id"), nullable=True)
    mikrotik_id = Column(Integer, ForeignKey("mikrotik_devices.id"), nullable=True)
    action = Column(String(50), index=True)
    old_status = Column(Integer, nullable=True)
    new_status = Column(Integer, nullable=True)
    mikrotik_result = Column(Text, nullable=True)
    error_message = Column(Text, nullable=True)
    created_at = Column(DateTime, default=utcnow)


class AppSetting(Base):
    """Key-value runtime settings (overrides .env), edited from the admin panel.

    Used for integration config (SMS / payment providers) so credentials can be
    set through the UI instead of editing .env and restarting.
    """

    __tablename__ = "app_settings"

    key = Column(String(100), primary_key=True)
    value = Column(Text, nullable=True)
    updated_at = Column(DateTime, default=utcnow, onupdate=utcnow)
