"""
POST /orders/create через HTTP: заказ сохраняется, обработка уходит в фон.
"""


def setup_menu(api):
    cook = api.headers(api.create_user("cook@sirius.ru", "cook"))
    api.client.post("/menu/items", json={"name": "Борщ", "price": 250}, headers=cook)


def test_order_handed_to_background(api):
    setup_menu(api)
    anna = api.create_user("anna@sirius.ru", balance=1000)

    response = api.client.post("/orders/create", json={"item_id": 1, "quantity": 2}, headers=api.headers(anna))

    assert response.json() == {"status": "success", "order_id": 1}
    assert api.notifier.calls == [(1, "anna@sirius.ru", None)]


def test_failed_order_not_handed_to_background(api):
    setup_menu(api)
    anna = api.create_user("anna@sirius.ru", balance=10)

    response = api.client.post("/orders/create", json={"item_id": 1, "quantity": 1}, headers=api.headers(anna))

    assert response.status_code == 400
    assert api.notifier.calls == []
