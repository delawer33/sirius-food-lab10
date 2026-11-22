"""
Инфраструктурный слой модуля users (круг 3: Interface Adapters).

SqlAlchemyUserRepository и InMemoryUserRepository реализуют UserRepository.
"""
from dataclasses import replace

from sqlalchemy.orm import Session

from app.domain.entities import User
from app.infrastructure.memory import InMemoryStorage
from app.infrastructure.sql import role_id, user_to_entity
from app.models import User as UserModel
from app.modules.users.interfaces import UserRepository


class SqlAlchemyUserRepository(UserRepository):
    def __init__(self, db: Session):
        self.db = db

    def get_user_by_id(self, user_id: int) -> User | None:
        row = self.db.get(UserModel, user_id)
        return user_to_entity(row) if row else None

    def get_user_by_email(self, email: str) -> User | None:
        row = self.db.query(UserModel).filter(UserModel.email == email).first()
        return user_to_entity(row) if row else None

    def create_user(
        self,
        email: str,
        phone: str | None,
        balance: float,
        is_blocked: bool,
        role: str,
        password_hash: str,
    ) -> User:
        row = UserModel(
            email=email,
            phone=phone,
            balance=balance,
            is_blocked=is_blocked,
            role_id=role_id(self.db, role),
            password_hash=password_hash,
        )
        self.db.add(row)
        self.db.commit()
        self.db.refresh(row)
        return user_to_entity(row)

    def update_balance(self, user_id: int, new_balance: float) -> float:
        row = self.db.get(UserModel, user_id)
        row.balance = new_balance
        self.db.commit()
        self.db.refresh(row)
        return row.balance

    def set_role(self, user_id: int, role: str) -> User:
        row = self.db.get(UserModel, user_id)
        row.role_id = role_id(self.db, role)
        self.db.commit()
        self.db.refresh(row)
        return user_to_entity(row)

    def set_blocked(self, user_id: int, is_blocked: bool) -> User:
        row = self.db.get(UserModel, user_id)
        row.is_blocked = is_blocked
        self.db.commit()
        self.db.refresh(row)
        return user_to_entity(row)


class InMemoryUserRepository(UserRepository):
    def __init__(self, storage: InMemoryStorage):
        self.storage = storage

    def get_user_by_id(self, user_id: int) -> User | None:
        user = self.storage.users.get(user_id)
        return replace(user) if user else None

    def get_user_by_email(self, email: str) -> User | None:
        user = next((u for u in self.storage.users.values() if u.email == email), None)
        return replace(user) if user else None

    def create_user(
        self,
        email: str,
        phone: str | None,
        balance: float,
        is_blocked: bool,
        role: str,
        password_hash: str,
    ) -> User:
        with self.storage.lock:
            user_id = self.storage.next_id(self.storage.users)
            user = User(user_id, email, phone, balance, is_blocked, role, password_hash)
            self.storage.users[user_id] = user
            return replace(user)

    def update_balance(self, user_id: int, new_balance: float) -> float:
        with self.storage.lock:
            self.storage.users[user_id].balance = new_balance
            return new_balance

    def set_role(self, user_id: int, role: str) -> User:
        with self.storage.lock:
            self.storage.users[user_id].role = role
            return replace(self.storage.users[user_id])

    def set_blocked(self, user_id: int, is_blocked: bool) -> User:
        with self.storage.lock:
            self.storage.users[user_id].is_blocked = is_blocked
            return replace(self.storage.users[user_id])
