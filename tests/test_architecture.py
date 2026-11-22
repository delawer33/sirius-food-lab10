"""
Архитектурные тесты: зависимости направлены снаружи внутрь.
"""
import ast
from pathlib import Path

import pytest

MODULES_DIR = Path(__file__).resolve().parent.parent / "app" / "modules"
REFACTORED = ("users", "menu", "orders", "delivery", "auth")
INFRASTRUCTURE = (
    "fastapi",
    "sqlalchemy",
    "redis",
    "app.core.redis",
    "celery",
    "app.core.celery_app",
    "app.tasks",
    "app.models",
    "app.database",
    "app.infrastructure",
    "grpc",
    "delivery_grpc",
    "delivery_service",
)


def imported_modules(path: Path) -> list[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    names = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            names.append(node.module)
    return names


def violations(path: Path, forbidden) -> list[str]:
    return [
        name
        for name in imported_modules(path)
        if any(name == f or name.startswith(f + ".") for f in forbidden)
        or name.endswith(".repository")
    ]


@pytest.mark.parametrize("module", REFACTORED)
def test_service_depends_only_on_domain_and_interfaces(module):
    """service.py не знает ни про веб-фреймворк, ни про ORM, ни про кеш и Celery, ни про реализации репозиториев."""
    assert violations(MODULES_DIR / module / "service.py", INFRASTRUCTURE) == []


@pytest.mark.parametrize("module", REFACTORED)
def test_router_does_not_touch_storage(module):
    """router.py получает сервис из контейнера и не трогает БД напрямую."""
    forbidden = ("sqlalchemy", "redis", "app.core.redis", "app.models", "app.database", "app.infrastructure")
    assert violations(MODULES_DIR / module / "router.py", forbidden) == []


ROOT = MODULES_DIR.parent.parent


def test_delivery_service_does_not_import_monolith():
    """Микросервис общается с монолитом только по gRPC, код app/ ему недоступен."""
    for path in (ROOT / "delivery_service").glob("*.py"):
        assert [n for n in imported_modules(path) if n == "app" or n.startswith("app.")] == [], path


def test_generated_grpc_code_matches_proto(tmp_path):
    """delivery_grpc/ сгенерирован из текущего proto/delivery.proto."""
    from scripts.gen_proto import DEFAULT_OUT, generate

    generate(tmp_path)
    for name in ("delivery_pb2.py", "delivery_pb2_grpc.py"):
        assert (tmp_path / name).read_text() == (DEFAULT_OUT / name).read_text(), (
            f"{name} устарел: python -m scripts.gen_proto"
        )
