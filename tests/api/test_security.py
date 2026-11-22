"""
Тесты безопасности через HTTP. Каждый тест идёт на обоих бэкендах (фикстура api).

Обязательный минимум из методички: без токена — 401, чужая роль — 403,
чужой объект — 403, rate limiting — 429.
"""
import pytest
from fastapi.testclient import TestClient
from jose import jwt

from app.core.config import Settings
from app.core.jwt import ALGORITHM
from app.core.redis import get_redis
from app.main import create_app
from redis.exceptions import ConnectionError as RedisConnectionError


@pytest.fixture
def menu(api):
    cook = api.create_user("cook@sirius.ru", "cook")
    api.client.post("/menu/items", json={"name": "Борщ", "price": 200}, headers=api.headers(cook))
    return cook


# --- 401: нет токена или он недействителен -------------------------------------

PROTECTED = [
    ("POST", "/orders/create", {"item_id": 1, "quantity": 1}),
    ("GET", "/orders/my", None),
    ("POST", "/orders/1/cancel", None),
    ("GET", "/users/me", None),
    ("POST", "/users/1/topup?amount=100", None),
    ("POST", "/menu/items", {"name": "Плов", "price": 100}),
    ("GET", "/kitchen/orders", None),
    ("POST", "/delivery/assign", {"order_id": 1, "courier_id": 1}),
    ("GET", "/delivery/1", None),
]


@pytest.mark.parametrize("method, url, body", PROTECTED)
def test_without_token_401(api, method, url, body):
    response = api.client.request(method, url, json=body)

    assert response.status_code == 401
    assert response.headers["WWW-Authenticate"] == "Bearer"


def test_forged_token_401(api):
    anna = api.create_user("anna@sirius.ru")
    forged = jwt.encode({"sub": str(anna.id), "type": "access", "ver": 0}, "k" * 40, ALGORITHM)

    response = api.client.get("/users/me", headers={"Authorization": f"Bearer {forged}"})

    assert response.status_code == 401


def test_unsigned_token_401(api):
    """Токен с alg=none и без подписи не принимается."""
    anna = api.create_user("anna@sirius.ru")
    header = "eyJhbGciOiJub25lIiwidHlwIjoiSldUIn0"  # {"alg":"none","typ":"JWT"}
    real = api.headers(anna)["Authorization"].split()[1]
    unsigned = f"{header}.{real.split('.')[1]}."

    response = api.client.get("/users/me", headers={"Authorization": f"Bearer {unsigned}"})

    assert response.status_code == 401


def test_refresh_token_instead_of_access_401(api):
    api.create_user("anna@sirius.ru")
    refresh = api.login("anna@sirius.ru").json()["refresh_token"]

    response = api.client.get("/users/me", headers={"Authorization": f"Bearer {refresh}"})

    assert response.status_code == 401


def test_blocked_user_403(api):
    anna = api.create_user("anna@sirius.ru")
    admin = api.create_user("admin@sirius.ru", "admin")
    api.client.patch(f"/users/{anna.id}/block", json={"is_blocked": True}, headers=api.headers(admin))

    assert api.client.get("/users/me", headers=api.headers(anna)).status_code == 403
    assert api.login("anna@sirius.ru").status_code == 403


# --- 403: чужая роль ---------------------------------------------------------

ROLE_DENIED = [
    ("student", "GET", "/kitchen/orders", None),
    ("courier", "GET", "/kitchen/orders", None),
    ("student", "POST", "/kitchen/orders/1/ready", None),
    ("cook", "POST", "/orders/create", {"item_id": 1, "quantity": 1}),
    ("courier", "POST", "/orders/create", {"item_id": 1, "quantity": 1}),
    ("student", "POST", "/menu/items", {"name": "Плов", "price": 100}),
    ("courier", "PATCH", "/menu/items/1", {"price": 1}),
    ("student", "POST", "/delivery/assign", {"order_id": 1, "courier_id": 1}),
    ("cook", "POST", "/delivery/assign", {"order_id": 1, "courier_id": 1}),
    ("student", "GET", "/delivery/my", None),
    ("student", "PATCH", "/delivery/1/complete", None),
    ("student", "PATCH", "/users/1/role", {"role": "admin"}),
    ("cook", "PATCH", "/users/1/block", {"is_blocked": True}),
]


@pytest.mark.parametrize("role, method, url, body", ROLE_DENIED)
def test_wrong_role_403(api, role, method, url, body):
    user = api.create_user(f"{role}@sirius.ru", role)

    response = api.client.request(method, url, json=body, headers=api.headers(user))

    assert response.status_code == 403
    assert response.json() == {"detail": "Доступ запрещён для вашей роли"}


def test_register_always_gives_student_role(api):
    api.client.post(
        "/users/register",
        json={"email": "hacker@sirius.ru", "password": "secret-password", "role": "admin"},
    )
    token = api.login("hacker@sirius.ru", "secret-password").json()["access_token"]

    me = api.client.get("/users/me", headers={"Authorization": f"Bearer {token}"}).json()

    assert me["role"] == "student"


# --- 403: чужой объект (IDOR) ----------------------------------------------------

@pytest.fixture
def two_students(api, menu):
    anna = api.create_user("anna@sirius.ru", balance=1000)
    boris = api.create_user("boris@sirius.ru", balance=1000)
    order_id = api.client.post(
        "/orders/create", json={"item_id": 1, "quantity": 1}, headers=api.headers(anna)
    ).json()["order_id"]
    return anna, boris, order_id


def test_foreign_order_cancel_403(api, two_students):
    anna, boris, order_id = two_students

    response = api.client.post(f"/orders/{order_id}/cancel", headers=api.headers(boris))

    assert response.status_code == 403
    order = api.client.get(f"/orders/{order_id}", headers=api.headers(anna)).json()
    assert order["status"] == "processing"


def test_foreign_order_view_403(api, two_students):
    _, boris, order_id = two_students

    assert api.client.get(f"/orders/{order_id}", headers=api.headers(boris)).status_code == 403


def test_foreign_balance_topup_403(api, two_students):
    anna, boris, _ = two_students

    response = api.client.post(f"/users/{anna.id}/topup?amount=100", headers=api.headers(boris))

    assert response.status_code == 403


def test_order_ignores_user_id_from_body(api, two_students):
    anna, boris, _ = two_students

    api.client.post(
        "/orders/create",
        json={"user_id": anna.id, "item_id": 1, "quantity": 1},
        headers=api.headers(boris),
    )

    assert api.client.get("/users/me", headers=api.headers(anna)).json()["balance"] == 800
    assert api.client.get("/users/me", headers=api.headers(boris)).json()["balance"] == 800


def test_foreign_delivery_403(api, two_students, menu):
    anna, boris, order_id = two_students
    admin = api.create_user("admin@sirius.ru", "admin")
    courier = api.create_user("courier@sirius.ru", "courier")
    other_courier = api.create_user("courier2@sirius.ru", "courier")
    api.client.post(f"/kitchen/orders/{order_id}/ready", headers=api.headers(menu))
    delivery_id = api.client.post(
        "/delivery/assign",
        json={"order_id": order_id, "courier_id": courier.id},
        headers=api.headers(admin),
    ).json()["delivery_id"]

    for outsider in (boris, other_courier):
        assert api.client.get(f"/delivery/{delivery_id}", headers=api.headers(outsider)).status_code == 403
    assert api.client.patch(
        f"/delivery/{delivery_id}/complete", headers=api.headers(other_courier)
    ).status_code == 403
    assert api.client.get("/delivery/my", headers=api.headers(other_courier)).json() == []
    assert api.client.get(f"/delivery/{delivery_id}", headers=api.headers(anna)).status_code == 200


# --- 429: rate limiting ----------------------------------------------------------

def test_login_rate_limit_429(api):
    api.create_user("anna@sirius.ru")

    statuses = [api.login("anna@sirius.ru", "wrong-password").status_code for _ in range(6)]

    assert statuses == [401] * 5 + [429]
    blocked = api.login("anna@sirius.ru")
    assert blocked.status_code == 429  # даже с верным паролем
    assert int(blocked.headers["Retry-After"]) > 0


def test_login_and_token_share_limit(api):
    """Swagger-эндпоинт /auth/token не даёт обойти лимит /auth/login."""
    api.create_user("anna@sirius.ru")
    for _ in range(5):
        api.login("anna@sirius.ru", "wrong-password")

    response = api.client.post(
        "/auth/token", data={"username": "anna@sirius.ru", "password": "test-password"}
    )

    assert response.status_code == 429


def test_rate_limit_window_expires(api, redis):
    api.create_user("anna@sirius.ru")
    for _ in range(6):
        api.login("anna@sirius.ru", "wrong-password")

    [key] = redis.keys("rate_limit:login:*")
    assert 0 < redis.ttl(key) <= 60
    redis.delete(key)  # окно истекло

    assert api.login("anna@sirius.ru").status_code == 200


def test_register_rate_limit_429(api):
    statuses = [
        api.client.post(
            "/users/register", json={"email": f"u{i}@sirius.ru", "password": "secret-password"}
        ).status_code
        for i in range(6)
    ]

    assert statuses == [200] * 5 + [429]


def test_redis_down_fails_closed(api):
    class BrokenRedis:
        def pipeline(self):
            raise RedisConnectionError("redis is down")

    api.client.app.dependency_overrides[get_redis] = lambda: BrokenRedis()

    assert api.login("anna@sirius.ru").status_code == 503


# --- Refresh Token rotation через HTTP ----------------------------------------

def test_refresh_rotation_and_reuse_detection(api):
    api.create_user("anna@sirius.ru")
    first = api.login("anna@sirius.ru").json()

    second = api.client.post("/auth/refresh", json={"refresh_token": first["refresh_token"]})
    assert second.status_code == 200
    second = second.json()

    reuse = api.client.post("/auth/refresh", json={"refresh_token": first["refresh_token"]})
    assert reuse.status_code == 401
    assert "Все сессии завершены" in reuse.json()["detail"]

    # Новая пара тоже мертва: и refresh, и access.
    assert api.client.post("/auth/refresh", json={"refresh_token": second["refresh_token"]}).status_code == 401
    me = api.client.get("/users/me", headers={"Authorization": f"Bearer {second['access_token']}"})
    assert me.status_code == 401


def test_swagger_login_form(api):
    api.create_user("anna@sirius.ru")

    response = api.client.post(
        "/auth/token", data={"username": "anna@sirius.ru", "password": "test-password"}
    )

    assert response.status_code == 200
    assert response.json()["token_type"] == "bearer"


# --- Secure by Default: Swagger и CORS -----------------------------------------

def make_client(**overrides) -> TestClient:
    config = Settings(
        SECRET_KEY="s" * 32, DATABASE_URL="sqlite://", ALLOWED_ORIGINS=["https://sirius-food.ru"], **overrides
    )
    return TestClient(create_app(config))


def test_swagger_disabled_in_production():
    client = make_client(DEBUG=False)

    assert client.get("/docs").status_code == 404
    assert client.get("/openapi.json").status_code == 404


def test_swagger_enabled_in_debug():
    client = make_client(DEBUG=True)

    assert client.get("/docs").status_code == 200
    schema = client.get("/openapi.json").json()
    assert "OAuth2PasswordBearer" in schema["components"]["securitySchemes"]


def preflight(client: TestClient, origin: str):
    return client.options(
        "/orders/create",
        headers={
            "Origin": origin,
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "Authorization",
        },
    )


def test_cors_allows_own_domain():
    response = preflight(make_client(), "https://sirius-food.ru")

    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == "https://sirius-food.ru"


def test_cors_rejects_foreign_domain():
    response = preflight(make_client(), "https://evil.example")

    assert "access-control-allow-origin" not in response.headers
