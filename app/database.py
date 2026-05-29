"""Database engine, session factory and helpers."""
from sqlalchemy import create_engine
from sqlalchemy.orm import declarative_base, sessionmaker

from .config import settings

connect_args = {}
if settings.DATABASE_URL.startswith("sqlite"):
    # Needed so the SQLite connection can be shared across threads (FastAPI).
    connect_args = {"check_same_thread": False}

engine = create_engine(settings.DATABASE_URL, connect_args=connect_args, future=True)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)
Base = declarative_base()


def get_db():
    """FastAPI dependency that yields a database session."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def init_db():
    """Create all tables. Safe to call on every startup (idempotent)."""
    from . import models  # noqa: F401  (ensure models are registered)

    Base.metadata.create_all(bind=engine)
    ensure_schema()


def ensure_schema():
    """Add columns introduced after the first release (create_all won't ALTER).

    Idempotent and DB-agnostic enough for SQLite/Postgres.
    """
    from sqlalchemy import inspect, text

    inspector = inspect(engine)

    def add_column(table: str, column: str, ddl_type: str) -> None:
        try:
            existing = {c["name"] for c in inspector.get_columns(table)}
        except Exception:
            return
        if column not in existing:
            try:
                with engine.begin() as conn:
                    conn.execute(
                        text(f"ALTER TABLE {table} ADD COLUMN {column} {ddl_type}")
                    )
            except Exception:
                # Already added / added concurrently; ignore.
                pass

    add_column("clients", "last_seen", "DATETIME")
