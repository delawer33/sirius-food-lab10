"""
Хеширование паролей через bcrypt.
"""
from passlib.context import CryptContext

# Контекст для хеширования. bcrypt — медленный алгоритм с солью.
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

# Хеш случайного пароля: проверяется, когда пользователь не найден, чтобы
# время ответа не выдавало, зарегистрирован ли email.
DUMMY_HASH = pwd_context.hash("dummy-password-for-timing")


def hash_password(password: str) -> str:
    """Возвращает bcrypt-хеш пароля."""
    return pwd_context.hash(password)


def verify_password(plain: str, hashed: str) -> bool:
    """Проверяет соответствие пароля хешу. Непригодный хеш ("!") — всегда False."""
    try:
        return pwd_context.verify(plain, hashed)
    except ValueError:
        return False
