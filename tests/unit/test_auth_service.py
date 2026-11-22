"""
Unit-тесты AuthService: вход, проверка access-токена, Refresh Token rotation.
"""
from datetime import timedelta

import pytest
from jose import jwt

from app.core.config import settings
from app.core.jwt import ALGORITHM, create_access_token
from app.core.security import hash_password
from app.domain.entities import User
from app.domain.errors import AccessDeniedError, AuthenticationError
from app.modules.auth.repository import InMemoryAuthRepository
from app.modules.auth.service import AuthService, hash_token


@pytest.fixture
def service(storage):
    storage.users[1] = User(
        1, "anna@sirius.ru", None, 0.0, False, "student", hash_password("secret-password")
    )
    return AuthService(InMemoryAuthRepository(storage))


def test_login_returns_working_tokens(service, storage):
    pair = service.login("anna@sirius.ru", "secret-password")

    assert service.authenticate(pair.access_token).id == 1
    # Refresh-токен хранится только в виде хеша.
    [record] = storage.refresh_tokens.values()
    assert record.token_hash == hash_token(pair.refresh_token) != pair.refresh_token


@pytest.mark.parametrize(
    "email, password",
    [("anna@sirius.ru", "wrong-password"), ("nobody@sirius.ru", "secret-password")],
)
def test_login_error_does_not_reveal_which_part_is_wrong(service, email, password):
    with pytest.raises(AuthenticationError, match="^Неверный email или пароль$"):
        service.login(email, password)


def test_user_without_password_cannot_log_in(service, storage):
    storage.users[1].password_hash = "!"  # так миграция помечает старых пользователей

    with pytest.raises(AuthenticationError):
        service.login("anna@sirius.ru", "!")


def test_blocked_user_cannot_log_in(service, storage):
    storage.users[1].is_blocked = True

    with pytest.raises(AccessDeniedError):
        service.login("anna@sirius.ru", "secret-password")


def test_payload_contains_only_technical_fields(service):
    pair = service.login("anna@sirius.ru", "secret-password")

    payload = jwt.get_unverified_claims(pair.access_token)
    assert set(payload) == {"sub", "type", "ver", "iat", "exp", "jti"}


def test_refresh_token_is_not_accepted_as_access(service):
    pair = service.login("anna@sirius.ru", "secret-password")

    with pytest.raises(AuthenticationError):
        service.authenticate(pair.refresh_token)


def test_token_signed_with_other_key_is_rejected(service):
    forged = jwt.encode(
        {"sub": "1", "type": "access", "ver": 0}, "x" * 40, algorithm=ALGORITHM
    )

    with pytest.raises(AuthenticationError):
        service.authenticate(forged)


def test_expired_token_is_rejected(service, monkeypatch):
    monkeypatch.setattr(settings, "ACCESS_TOKEN_EXPIRE_MINUTES", -1)
    token = create_access_token(1)

    with pytest.raises(AuthenticationError):
        service.authenticate(token)


def test_token_for_deleted_user_is_rejected(service, storage):
    token = create_access_token(1)
    del storage.users[1]

    with pytest.raises(AuthenticationError):
        service.authenticate(token)


def test_refresh_rotates_tokens(service, storage):
    first = service.login("anna@sirius.ru", "secret-password")

    second = service.refresh(first.refresh_token)

    assert second.refresh_token != first.refresh_token
    assert service.authenticate(second.access_token).id == 1
    old, new = storage.refresh_tokens.values()
    assert (old.is_revoked, new.is_revoked) == (True, False)


def test_reused_refresh_token_resets_all_sessions(service):
    laptop = service.login("anna@sirius.ru", "secret-password")
    phone = service.login("anna@sirius.ru", "secret-password")
    rotated = service.refresh(laptop.refresh_token)

    # Кто-то предъявил уже использованный токен: его украли.
    with pytest.raises(AuthenticationError, match="Все сессии завершены"):
        service.refresh(laptop.refresh_token)

    # Сброшены все сессии: и новая пара, и другое устройство.
    for pair in (rotated, phone):
        with pytest.raises(AuthenticationError):
            service.refresh(pair.refresh_token)
        with pytest.raises(AuthenticationError):
            service.authenticate(pair.access_token)
    # Войти заново можно.
    assert service.authenticate(service.login("anna@sirius.ru", "secret-password").access_token)


def test_stale_token_after_reset_does_not_reset_again(service, storage):
    stolen = service.login("anna@sirius.ru", "secret-password")
    service.refresh(stolen.refresh_token)
    with pytest.raises(AuthenticationError):
        service.refresh(stolen.refresh_token)
    fresh = service.login("anna@sirius.ru", "secret-password")

    # Повторный заход со старым токеном не выкидывает пользователя из новой сессии.
    with pytest.raises(AuthenticationError, match="Недействительный"):
        service.refresh(stolen.refresh_token)
    assert service.authenticate(fresh.access_token).id == 1
    assert storage.users[1].token_version == 1


def test_refresh_with_unknown_token(service, monkeypatch):
    pair = service.login("anna@sirius.ru", "secret-password")
    service.repository.storage.refresh_tokens.clear()

    with pytest.raises(AuthenticationError):
        service.refresh(pair.refresh_token)


def test_refresh_for_blocked_user(service, storage):
    pair = service.login("anna@sirius.ru", "secret-password")
    storage.users[1].is_blocked = True

    with pytest.raises(AccessDeniedError):
        service.refresh(pair.refresh_token)


def test_expired_refresh_token_is_rejected(service, monkeypatch):
    monkeypatch.setattr(settings, "REFRESH_TOKEN_EXPIRE_DAYS", -1)
    pair = service.login("anna@sirius.ru", "secret-password")

    with pytest.raises(AuthenticationError):
        service.refresh(pair.refresh_token)


def test_logout_revokes_refresh_token(service):
    pair = service.login("anna@sirius.ru", "secret-password")

    service.logout(pair.refresh_token)

    with pytest.raises(AuthenticationError):
        service.refresh(pair.refresh_token)


def test_access_token_lifetime_is_short(service):
    pair = service.login("anna@sirius.ru", "secret-password")

    claims = jwt.get_unverified_claims(pair.access_token)
    assert timedelta(seconds=claims["exp"] - claims["iat"]) == timedelta(minutes=15)
