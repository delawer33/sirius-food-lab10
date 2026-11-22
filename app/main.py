"""
Точка входа приложения: создание FastAPI, CORS, подключение модулей.

Схему БД создаёт не приложение, а миграции: alembic upgrade head.

Наблюдаемость (лабораторная № 9): JSON-логи и Sentry настраиваются при
импорте, в create_app — correlation_id, /metrics и span'ы HTTP-запросов.
"""
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from prometheus_fastapi_instrumentator import Instrumentator

import observability
from app import container
from app.core.config import Settings, settings
from app.core.correlation import correlation_id_middleware
from app.database import engine
from app.modules.auth.router import router as auth_router
from app.modules.delivery.router import router as delivery_router
from app.modules.menu.router import router as menu_router
from app.modules.orders.router import kitchen_router
from app.modules.orders.router import router as orders_router
from app.modules.users.router import router as users_router
from observability import correlation, tracing

observability.setup("sirius-app")
tracing.instrument_engine(engine)


def create_app(config: Settings = settings) -> FastAPI:
    @asynccontextmanager
    async def lifespan(app: FastAPI):
        # Прогрев кеша: первый запрос к меню после старта не идёт в БД.
        if config.CACHE_WARM_UP:
            container.warm_up_cache()
        yield

    # Swagger раскрывает структуру API, поэтому в продакшене (DEBUG=False)
    # выключены и страница /docs, и сама схема /openapi.json.
    app = FastAPI(
        title="Sirius.Food API",
        docs_url="/docs" if config.DEBUG else None,
        redoc_url=None,
        openapi_url="/openapi.json" if config.DEBUG else None,
        lifespan=lifespan,
    )

    # CORS: браузер пустит к API только страницы с перечисленных доменов.
    app.add_middleware(
        CORSMiddleware,
        allow_origins=config.ALLOWED_ORIGINS,
        allow_credentials=True,
        allow_methods=["GET", "POST", "PATCH"],
        allow_headers=["Authorization", "Content-Type", correlation.HEADER],
        expose_headers=[correlation.HEADER],
    )
    # RED-метрики каждого эндпоинта на /metrics. Коды статусов не группируются
    # в 2xx/5xx, чтобы работал запрос status=~"5.." из методички.
    Instrumentator(should_group_status_codes=False, excluded_handlers=["/metrics"]).instrument(app).expose(
        app, include_in_schema=False
    )
    # Добавлен последним — снаружи CORS и метрик: correlation_id есть у любого ответа.
    app.middleware("http")(correlation_id_middleware)
    if tracing.enabled():
        from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor

        FastAPIInstrumentor.instrument_app(app, excluded_urls="metrics")

    app.include_router(auth_router, prefix="/auth", tags=["auth"])
    app.include_router(users_router, prefix="/users", tags=["users"])
    app.include_router(menu_router, prefix="/menu", tags=["menu"])
    app.include_router(orders_router, prefix="/orders", tags=["orders"])
    app.include_router(kitchen_router, prefix="/kitchen", tags=["kitchen"])
    app.include_router(delivery_router, prefix="/delivery", tags=["delivery"])

    if config.DEBUG:
        @app.get("/debug/error", include_in_schema=False)
        def debug_error():
            """Необработанная ошибка → 500 и событие в Sentry. Только при DEBUG."""
            raise RuntimeError("Проверка Sentry: необработанная ошибка в обработчике")

    return app


app = create_app()
