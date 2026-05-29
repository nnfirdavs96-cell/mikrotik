"""Shared FastAPI dependencies, the Jinja2 templates object and helpers."""
from pathlib import Path

from fastapi import Depends, Header, HTTPException, Request, status
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from .config import settings
from .database import get_db
from .models import (
    CLIENT_STATUS_COLORS,
    CLIENT_STATUS_LABELS,
    PAYMENT_STATUS_COLORS,
    AdminUser,
)

BASE_DIR = Path(__file__).resolve().parent

templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))
templates.env.globals["app_name"] = settings.APP_NAME
templates.env.globals["app_version"] = settings.APP_VERSION
templates.env.globals["currency"] = settings.DEFAULT_CURRENCY
templates.env.globals["status_labels"] = CLIENT_STATUS_LABELS
templates.env.globals["status_colors"] = CLIENT_STATUS_COLORS
templates.env.globals["payment_status_colors"] = PAYMENT_STATUS_COLORS


# ---------------------------------------------------------------------------
# Flash messages (stored in the signed session cookie)
# ---------------------------------------------------------------------------
def flash(request: Request, message: str, category: str = "info") -> None:
    request.session.setdefault("_flash", []).append(
        {"category": category, "message": message}
    )


def get_flashed(request: Request):
    return request.session.pop("_flash", [])


def render(request: Request, name: str, **context):
    """Render a template, automatically injecting request + flash messages."""
    context.setdefault("request", request)
    context["flashes"] = get_flashed(request)
    context["current_admin_id"] = request.session.get("admin_id")
    return templates.TemplateResponse(name, context)


# ---------------------------------------------------------------------------
# Auth dependencies
# ---------------------------------------------------------------------------
def get_current_admin(request: Request, db: Session = Depends(get_db)):
    admin_id = request.session.get("admin_id")
    if not admin_id:
        return None
    return (
        db.query(AdminUser)
        .filter(AdminUser.id == admin_id, AdminUser.is_active.is_(True))
        .first()
    )


def require_admin(request: Request, db: Session = Depends(get_db)) -> AdminUser:
    """Protect admin pages; redirect to the login page when not authenticated."""
    admin = get_current_admin(request, db)
    if not admin:
        raise HTTPException(
            status_code=status.HTTP_303_SEE_OTHER,
            headers={"Location": "/admin/login"},
        )
    return admin


def require_api_key(x_api_key: str = Header(default=None)) -> bool:
    """Protect REST API endpoints with the X-API-Key header."""
    if not x_api_key or x_api_key != settings.API_SECRET_KEY:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"success": False, "message": "Invalid or missing API key"},
        )
    return True
