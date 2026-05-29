"""FastAPI application entrypoint."""
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.sessions import SessionMiddleware

from .auth import ensure_default_admin
from .config import settings
from .database import SessionLocal, init_db
from .routers import (
    admin,
    api_clients,
    api_compat,
    api_health,
    api_mikrotik,
    api_payments,
    api_sync,
    api_tasks,
    portal,
)
from .services.scheduler import shutdown_scheduler, start_scheduler
from .services.tariffs import seed_default_tariffs

BASE_DIR = Path(__file__).resolve().parent


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Create tables and seed the first admin + example tariffs on startup.
    init_db()
    db = SessionLocal()
    try:
        ensure_default_admin(db)
        seed_default_tariffs(db)
    finally:
        db.close()
    # Stage 2: start the background scheduler (auto-expire / traffic checks).
    start_scheduler()
    yield
    shutdown_scheduler()


app = FastAPI(title=settings.APP_NAME, version=settings.APP_VERSION, lifespan=lifespan)
app.add_middleware(SessionMiddleware, secret_key=settings.SECRET_KEY)
app.mount("/static", StaticFiles(directory=str(BASE_DIR / "static")), name="static")

# Paths that belong to the app itself and must never be captive-redirected.
_CAPTIVE_PASSTHROUGH = (
    "/portal", "/admin", "/api", "/health", "/static",
    "/docs", "/openapi.json", "/redoc",
)


def _captive_target() -> str:
    if settings.CAPTIVE_PORTAL_URL:
        return settings.CAPTIVE_PORTAL_URL
    if settings.PUBLIC_BASE_URL:
        return settings.PUBLIC_BASE_URL.rstrip("/") + "/portal"
    return "/portal"


@app.middleware("http")
async def captive_redirect(request, call_next):
    """Redirect intercepted/foreign requests to the portal (captive behaviour).

    Enabled by CAPTIVE_REDIRECT_ENABLED. App paths pass through untouched; any
    other request (OS captive probe, foreign Host via MikroTik dst-nat) gets a
    302 to the portal so the device shows the "Sign in to network" prompt.
    """
    if settings.CAPTIVE_REDIRECT_ENABLED and not request.url.path.startswith(
        _CAPTIVE_PASSTHROUGH
    ):
        return RedirectResponse(url=_captive_target(), status_code=302)
    return await call_next(request)

# Routers
app.include_router(api_health.router)
app.include_router(admin.router)
app.include_router(portal.router)
app.include_router(api_clients.router)
app.include_router(api_mikrotik.router)
app.include_router(api_sync.router)
app.include_router(api_payments.router)
app.include_router(api_tasks.router)
app.include_router(api_compat.router)


@app.get("/")
def root():
    return RedirectResponse(url="/portal")
