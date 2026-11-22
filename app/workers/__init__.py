"""
Фоновые процессы event-driven части. Каждый запускается в своём терминале:

    python -m app.workers.outbox_relay      # outbox -> RabbitMQ
    python -m app.workers.kitchen_consumer  # order.paid, order.cancelled -> kitchen_orders
    python -m app.workers.saga_consumer     # delivery.failed -> отмена и возврат денег
    python -m app.workers.event_log         # печатает все события (#)
"""
