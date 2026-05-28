"""initial schema

Creates all tables from the application's SQLAlchemy metadata. This keeps the
initial migration in perfect sync with the models. Subsequent schema changes
can be produced with ``alembic revision --autogenerate``.

Revision ID: 0001_initial
Revises:
Create Date: 2024-01-01 00:00:00
"""
from alembic import op

from app.database import Base
from app import models  # noqa: F401  (register tables on Base.metadata)

revision = "0001_initial"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    Base.metadata.create_all(bind=bind)


def downgrade() -> None:
    bind = op.get_bind()
    Base.metadata.drop_all(bind=bind)
