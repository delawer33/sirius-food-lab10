from app.models import Order


def add_order(session_factory, status="processing", total=250.0) -> int:
    with session_factory() as db:
        order = Order(user_id=1, item_id=1, quantity=1, status=status, total_cost=total)
        db.add(order)
        db.commit()
        return order.id
