"""Password hashing and admin authentication helpers."""
from passlib.context import CryptContext
from sqlalchemy.orm import Session

from .config import settings
from .models import AdminUser

# pbkdf2_sha256 is pure-python and avoids native bcrypt version issues.
pwd_context = CryptContext(schemes=["pbkdf2_sha256"], deprecated="auto")


def hash_password(password: str) -> str:
    return pwd_context.hash(password)


def verify_password(password: str, password_hash: str) -> bool:
    try:
        return pwd_context.verify(password, password_hash)
    except Exception:
        return False


def authenticate_admin(db: Session, username: str, password: str):
    user = (
        db.query(AdminUser)
        .filter(AdminUser.username == username, AdminUser.is_active.is_(True))
        .first()
    )
    if not user:
        return None
    if not verify_password(password, user.password_hash):
        return None
    return user


def ensure_default_admin(db: Session) -> AdminUser:
    """Create the first admin from .env if it does not exist yet."""
    existing = (
        db.query(AdminUser)
        .filter(AdminUser.username == settings.ADMIN_USERNAME)
        .first()
    )
    if existing:
        return existing
    user = AdminUser(
        username=settings.ADMIN_USERNAME,
        password_hash=hash_password(settings.ADMIN_PASSWORD),
        is_active=True,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user
