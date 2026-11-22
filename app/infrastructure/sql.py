"""
Общие преобразования для SQLAlchemy-репозиториев.
"""
from sqlalchemy.orm import Session

from app.domain.entities import User
from app.models import Role
from app.models import User as UserModel


def user_to_entity(row: UserModel) -> User:
    return User(
        id=row.id,
        email=row.email,
        phone=row.phone,
        balance=row.balance,
        is_blocked=row.is_blocked,
        role=row.role.name,
        password_hash=row.password_hash,
        token_version=row.token_version,
    )


def role_id(db: Session, name: str) -> int:
    """id роли по названию. Справочник ролей заполняет миграция."""
    return db.query(Role.id).filter(Role.name == name).scalar()
