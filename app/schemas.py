"""Pydantic schemas used by the REST API."""
import datetime as dt
from typing import Optional

from pydantic import BaseModel, ConfigDict


class APIResponse(BaseModel):
    success: bool
    message: str = ""
    details: Optional[str] = None


class ClientOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    phone: str
    phone_verified: bool
    mac_address: Optional[str] = None
    ip_address: Optional[str] = None
    hostname: Optional[str] = None
    status: int
    tariff_id: Optional[int] = None
    mikrotik_id: Optional[int] = None
    created_at: Optional[dt.datetime] = None
    activated_at: Optional[dt.datetime] = None
    deactivated_at: Optional[dt.datetime] = None
    expires_at: Optional[dt.datetime] = None
    comment: Optional[str] = None


class ClientUpdate(BaseModel):
    phone: Optional[str] = None
    tariff_id: Optional[int] = None
    mikrotik_id: Optional[int] = None
    comment: Optional[str] = None
    status: Optional[int] = None
    expires_at: Optional[dt.datetime] = None


class MikroTikCreate(BaseModel):
    name: str
    host: str
    port: int = 8728
    username: str
    password: str
    use_ssl: bool = False
    is_active: bool = False
    comment: Optional[str] = None


class MikroTikOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    host: str
    port: int
    username: str
    use_ssl: bool
    is_active: bool
    comment: Optional[str] = None
    last_status: Optional[str] = None
    last_error: Optional[str] = None
    last_checked_at: Optional[dt.datetime] = None


class PaymentWebhook(BaseModel):
    provider_payment_id: Optional[str] = None
    payment_id: Optional[int] = None
    status: str = "paid"
