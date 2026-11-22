"""
Кеш меню через HTTP, на обоих бэкендах: изменения видны сразу, категории,
прогрев при старте.
"""
from fastapi.testclient import TestClient

from app import container
from app.core import redis as core_redis


def editor(api):
    return api.headers(api.create_user("cook@sirius.ru", "cook"))


def test_new_item_visible_immediately(api, redis):
    headers = editor(api)
    api.client.post("/menu/items", json={"name": "Борщ", "price": 250}, headers=headers)
    assert [i["name"] for i in api.client.get("/menu/items").json()] == ["Борщ"]
    assert redis.exists("menu:all") == 1

    api.client.post("/menu/items", json={"name": "Компот", "price": 60}, headers=headers)
    api.client.patch("/menu/items/1", json={"price": 300}, headers=headers)

    items = api.client.get("/menu/items").json()
    assert [(i["name"], i["price"]) for i in items] == [("Борщ", 300.0), ("Компот", 60.0)]


def test_menu_response_did_not_change(api):
    """Поле category_id не попало в ответ GET /menu/items: клиенты прошлых лаб не ломаются."""
    api.client.post("/menu/items", json={"name": "Борщ", "price": 250}, headers=editor(api))

    assert api.client.get("/menu/items").json() == [
        {"id": 1, "name": "Борщ", "price": 250.0, "is_available": True}
    ]


def test_categories(api, redis):
    headers = editor(api)
    assert api.client.post("/menu/categories", json={"name": "Супы"}, headers=headers).json() == {
        "status": "success",
        "category_id": 1,
    }
    api.client.post(
        "/menu/items", json={"name": "Борщ", "price": 250, "category_id": 1}, headers=headers
    )
    api.client.post("/menu/items", json={"name": "Хлеб", "price": 10}, headers=headers)

    assert api.client.get("/menu/categories").json() == [{"id": 1, "name": "Супы"}]
    soups = api.client.get("/menu/categories/1")
    assert soups.status_code == 200
    assert soups.json() == {
        "id": 1,
        "name": "Супы",
        "items": [{"id": 1, "name": "Борщ", "price": 250.0, "is_available": True}],
    }
    assert redis.exists("menu:category:1") == 1

    api.client.patch("/menu/items/2", json={"category_id": 1}, headers=headers)
    assert [i["name"] for i in api.client.get("/menu/categories/1").json()["items"]] == [
        "Борщ",
        "Хлеб",
    ]


def test_category_errors(api):
    headers = editor(api)
    api.client.post("/menu/categories", json={"name": "Супы"}, headers=headers)

    assert api.client.get("/menu/categories/9").status_code == 404
    duplicate = api.client.post("/menu/categories", json={"name": "Супы"}, headers=headers)
    assert (duplicate.status_code, duplicate.json()["detail"]) == (
        400,
        "Категория с таким названием уже существует",
    )
    unknown = api.client.post(
        "/menu/items", json={"name": "Борщ", "price": 250, "category_id": 9}, headers=headers
    )
    assert (unknown.status_code, unknown.json()["detail"]) == (404, "Категория не найдена")


def test_only_editors_create_categories(api):
    student = api.headers(api.create_user("anna@sirius.ru"))

    assert api.client.post("/menu/categories", json={"name": "Супы"}).status_code == 401
    assert api.client.post("/menu/categories", json={"name": "Супы"}, headers=student).status_code == 403


def test_warm_up_on_startup(api, redis, monkeypatch):
    api.client.post("/menu/categories", json={"name": "Супы"}, headers=editor(api))
    redis.flushall()
    monkeypatch.setattr(container, "redis_client", redis)

    with TestClient(api.client.app):  # with запускает lifespan, как uvicorn
        pass

    assert sorted(redis.keys("menu:*")) == ["menu:all", "menu:categories", "menu:category:1"]


def test_warm_up_survives_redis_down(api, monkeypatch):
    monkeypatch.setattr(container, "redis_client", core_redis.redis.Redis(port=1))

    with TestClient(api.client.app) as client:
        assert client.get("/menu/items").status_code == 200


def test_get_item(api):
    """Карточка блюда для витрины ЛР № 8: то же тело, что в списке, или 404."""
    api.client.post("/menu/items", json={"name": "Борщ", "price": 250}, headers=editor(api))

    item = api.client.get("/menu/items/1")
    assert (item.status_code, item.json()) == (
        200,
        {"id": 1, "name": "Борщ", "price": 250.0, "is_available": True},
    )
    missing = api.client.get("/menu/items/999999")
    assert (missing.status_code, missing.json()["detail"]) == (404, "Блюдо не найдено")
