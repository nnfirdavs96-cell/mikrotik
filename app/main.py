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

# Routers
app.include_router(api_health.router)
app.include_router(admin.router)
app.include_router(portal.router)
app.include_router(api_clients.router)
app.include_router(api_mikrotik.router)
app.include_router(api_sync.router)
app.include_router(api_payments.router)
app.include_router(api_tasks.router)


@app.get("/")
def root():
    return RedirectResponse(url="/portal")
