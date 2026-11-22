"""
Слой бизнес-логики модуля users. Без fastapi и sqlalchemy.

Проверка роли («только admin») делается в роутере через require_role.
Проверка прав на конкретный объект («пополнять можно только свой баланс»)
делается здесь, потому что это правило предметной области.
"""
from app.core.security import hash_password
from app.domain.entities import User
from app.domain.errors import AccessDeniedError, BusinessRuleError, NotFoundError
from app.domain.roles import ADMIN, ALL_ROLES, STUDENT
from app.modules.users.interfaces import UserRepository

# Бизнес-правило: максимальная сумма одного пополнения, рублей.
MAX_TOP_UP = 50000


class UserService:
    """Бизнес-правила регистрации, пополнения баланса и управления ролями."""

    def __init__(self, repository: UserRepository):
        self.repository = repository

    def register(self, email: str, password: str, phone: str | None = None) -> User:
        """
        Самостоятельная регистрация. Роль всегда student: выбрать себе роль
        клиент не может, остальные роли назначает администратор.
        """
        return self.create_user(email=email, password=password, role=STUDENT, phone=phone)

    def create_user(
        self, email: str, password: str, role: str, phone: str | None = None
    ) -> User:
        """Создаёт пользователя с заданной ролью. Для CLI и начальной настройки."""
        if role not in ALL_ROLES:
            raise BusinessRuleError(f"Неизвестная роль: {role}")
        if self.repository.get_user_by_email(email):
            raise BusinessRuleError("Пользователь с таким email уже зарегистрирован")
        return self.repository.create_user(
            email=email,
            phone=phone,
            balance=0.0,
            is_blocked=False,
            role=role,
            password_hash=hash_password(password),
        )

    def top_up(self, user_id: int, amount: float, actor: User) -> float:
        """
        Пополняет баланс и возвращает новое значение. Пополнить можно свой
        баланс; администратор может пополнить любой.
        """
        # Права проверяются раньше существования: иначе по 403/404 студент
        # узнал бы, какие id заняты.
        if actor.id != user_id and actor.role != ADMIN:
            raise AccessDeniedError("Нельзя пополнить чужой баланс")
        user = self.repository.get_user_by_id(user_id)
        if user is None:
            raise NotFoundError("Пользователь не найден")
        if user.is_blocked:
            raise AccessDeniedError("Пользователь заблокирован. Пополнение невозможно")
        if amount > MAX_TOP_UP:
            raise BusinessRuleError(f"Максимальная сумма пополнения — {MAX_TOP_UP} рублей")
        return self.repository.update_balance(user_id, user.balance + amount)

    def change_role(self, user_id: int, role: str, actor: User) -> User:
        """Назначает роль. Свою роль менять нельзя, чтобы не остаться без админа."""
        if role not in ALL_ROLES:
            raise BusinessRuleError(f"Неизвестная роль: {role}")
        self._get_other_user(user_id, actor, "Нельзя изменить собственную роль")
        return self.repository.set_role(user_id, role)

    def set_blocked(self, user_id: int, is_blocked: bool, actor: User) -> User:
        """
        Блокирует или разблокирует пользователя. Заблокированный получает 403
        на любой запрос с токеном и не может войти или обновить токен.
        """
        self._get_other_user(user_id, actor, "Нельзя заблокировать самого себя")
        return self.repository.set_blocked(user_id, is_blocked)

    def _get_other_user(self, user_id: int, actor: User, self_message: str) -> User:
        if user_id == actor.id:
            raise BusinessRuleError(self_message)
        user = self.repository.get_user_by_id(user_id)
        if user is None:
            raise NotFoundError("Пользователь не найден")
        return user
