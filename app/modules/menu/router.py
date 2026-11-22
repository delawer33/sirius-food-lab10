"""
Транспортный слой модуля menu. Меню видят все, меняют повар и администратор.

После внедрения кеша здесь ничего не поменялось: роутер не знает, что
данные приходят из Redis.
"""
from fastapi import APIRouter, Depends, HTTPException

from app.container import get_menu_service
from app.core.dependencies import require_role
from app.domain.errors import DomainError
from app.domain.roles import ADMIN, COOK
from app.http_errors import to_http_exception
from app.modules.menu.service import MenuService
from app.schemas import (
    CategoryCreate,
    CategoryMenuResponse,
    CategoryResponse,
    MenuItemCreate,
    MenuItemResponse,
    MenuItemUpdate,
)

router = APIRouter()

menu_editor = require_role(ADMIN, COOK)


@router.get("/items", response_model=list[MenuItemResponse])
def list_menu_items(service: MenuService = Depends(get_menu_service)):
    """Меню открыто без входа: его смотрят до регистрации."""
    return service.list_items()


@router.get("/items/{item_id}", response_model=MenuItemResponse)
def get_menu_item(item_id: int, service: MenuService = Depends(get_menu_service)):
    """Карточка блюда для SSR-витрины (ЛР № 8). Нет блюда — 404."""
    try:
        return service.get_item(item_id)
    except DomainError as error:
        raise to_http_exception(error)


@router.post("/items", dependencies=[Depends(menu_editor)])
def create_menu_item(
    payload: MenuItemCreate,
    service: MenuService = Depends(get_menu_service),
):
    # Техническая валидация цены и названия.
    if payload.price <= 0:
        raise HTTPException(
            status_code=400,
            detail="Цена должна быть положительной",
        )
    if len(payload.name) < 2:
        raise HTTPException(
            status_code=400,
            detail="Название блюда слишком короткое",
        )

    try:
        item = service.create_item(
            name=payload.name, price=payload.price, category_id=payload.category_id
        )
    except DomainError as error:
        raise to_http_exception(error)

    return {"status": "success", "item_id": item.id}


@router.patch("/items/{item_id}", dependencies=[Depends(menu_editor)])
def update_menu_item(
    item_id: int,
    payload: MenuItemUpdate,
    service: MenuService = Depends(get_menu_service),
):
    # Техническая валидация нового значения цены.
    if payload.price is not None and payload.price <= 0:
        raise HTTPException(
            status_code=400,
            detail="Цена должна быть положительной",
        )

    try:
        item = service.update_item(
            item_id=item_id,
            name=payload.name,
            price=payload.price,
            is_available=payload.is_available,
            category_id=payload.category_id,
        )
    except DomainError as error:
        raise to_http_exception(error)

    return {"status": "success", "item_id": item.id}


@router.get("/categories", response_model=list[CategoryResponse])
def list_categories(service: MenuService = Depends(get_menu_service)):
    return service.list_categories()


@router.get("/categories/{category_id}", response_model=CategoryMenuResponse)
def get_category(category_id: int, service: MenuService = Depends(get_menu_service)):
    """Категория со всеми её блюдами. Открыта без входа, как и меню."""
    try:
        menu = service.get_category_menu(category_id)
    except DomainError as error:
        raise to_http_exception(error)
    return {"id": menu.category.id, "name": menu.category.name, "items": menu.items}


@router.post("/categories", dependencies=[Depends(menu_editor)])
def create_category(payload: CategoryCreate, service: MenuService = Depends(get_menu_service)):
    try:
        category = service.create_category(payload.name)
    except DomainError as error:
        raise to_http_exception(error)
    return {"status": "success", "category_id": category.id}
