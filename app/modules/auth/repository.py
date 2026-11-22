"""
Инфраструктурный слой модуля auth (круг 3: Interface Adapters).
"""
from dataclasses import replace
from datetime import datetime

from sqlalchemy.orm import Session

from app.domain.entities import RefreshToken, User
from app.infrastructure.memory import InMemoryStorage
from app.infrastructure.sql import user_to_entity
from app.models import RefreshToken as RefreshTokenModel
from app.models import User as UserModel
from app.modules.auth.interfaces import AuthRepository


class SqlAlchemyAuthRepository(AuthRepository):
    def __init__(self, db: Session):
        self.db = db

    def get_user_by_id(self, user_id: int) -> User | None:
        row = self.db.get(UserModel, user_id)
        return user_to_entity(row) if row else None

    def get_user_by_email(self, email: str) -> User | None:
        row = self.db.query(UserModel).filter(UserModel.email == email).first()
        return user_to_entity(row) if row else None

    def save_refresh_token(self, user_id: int, token_hash: str, expires_at: datetime) -> None:
        self.db.add(RefreshTokenModel(user_id=user_id, token_hash=token_hash, expires_at=expires_at))
        self.db.commit()

    def get_refresh_token(self, token_hash: str) -> RefreshToken | None:
        row = (
            self.db.query(RefreshTokenModel)
            .filter(RefreshTokenModel.token_hash == token_hash)
            .first()
        )
        if row is None:
            return None
        return RefreshToken(row.id, row.user_id, row.token_hash, row.expires_at, row.is_revoked)

    def revoke_refresh_token(self, token_id: int) -> bool:
        # UPDATE ... WHERE is_revoked = false: из двух конкурентных запросов
        # строку изменит только один, второй получит rowcount 0.
        updated = (
            self.db.query(RefreshTokenModel)
            .filter(RefreshTokenModel.id == token_id, RefreshTokenModel.is_revoked.is_(False))
            .update({RefreshTokenModel.is_revoked: True}, synchronize_session=False)
        )
        self.db.commit()
        return updated == 1

    def revoke_all_sessions(self, user_id: int) -> None:
        self.db.query(RefreshTokenModel).filter(RefreshTokenModel.user_id == user_id).update(
            {RefreshTokenModel.is_revoked: True}, synchronize_session=False
        )
        self.db.query(UserModel).filter(UserModel.id == user_id).update(
            {UserModel.token_version: UserModel.token_version + 1}, synchronize_session=False
        )
        self.db.commit()


class InMemoryAuthRepository(AuthRepository):
    def __init__(self, storage: InMemoryStorage):
        self.storage = storage

    def get_user_by_id(self, user_id: int) -> User | None:
        user = self.storage.users.get(user_id)
        return replace(user) if user else None

    def get_user_by_email(self, email: str) -> User | None:
        user = next((u for u in self.storage.users.values() if u.email == email), None)
        return replace(user) if user else None

    def save_refresh_token(self, user_id: int, token_hash: str, expires_at: datetime) -> None:
        with self.storage.lock:
            token_id = self.storage.next_id(self.storage.refresh_tokens)
            self.storage.refresh_tokens[token_id] = RefreshToken(
                token_id, user_id, token_hash, expires_at, False
            )

    def get_refresh_token(self, token_hash: str) -> RefreshToken | None:
        token = next(
            (t for t in self.storage.refresh_tokens.values() if t.token_hash == token_hash), None
        )
        return replace(token) if token else None

    def revoke_refresh_token(self, token_id: int) -> bool:
        with self.storage.lock:
            token = self.storage.refresh_tokens[token_id]
            if token.is_revoked:
                return False
            token.is_revoked = True
            return True

    def revoke_all_sessions(self, user_id: int) -> None:
        with self.storage.lock:
            for token in self.storage.refresh_tokens.values():
                if token.user_id == user_id:
                    token.is_revoked = True
            self.storage.users[user_id].token_version += 1
