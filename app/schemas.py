"""
Pydantic-схемы для валидации входных и выходных данных.
"""
from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator


class UserCreate(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8)
    phone: str | None = None

    @field_validator("password")
    @classmethod
    def fits_bcrypt(cls, value: str) -> str:
        # bcrypt учитывает только первые 72 байта, остальное молча отбрасывает.
        if len(value.encode()) > 72:
            raise ValueError("Пароль длиннее 72 байт")
        return value


class UserResponse(BaseModel):
    id: int
    email: str
    balance: float

    model_config = ConfigDict(from_attributes=True)


class UserProfile(BaseModel):
    id: int
    email: str
    phone: str | None
    balance: float
    role: str
    is_blocked: bool

    model_config = ConfigDict(from_attributes=True)


class RoleUpdate(BaseModel):
    role: str


class BlockUpdate(BaseModel):
    is_blocked: bool


class MenuItemCreate(BaseModel):
    name: str
    price: float
    category_id: int | None = None


class MenuItemUpdate(BaseModel):
    name: str | None = None
    price: float | None = None
    is_available: bool | None = None
    category_id: int | None = None


class MenuItemResponse(BaseModel):
    id: int
    name: str
    price: float
    is_available: bool

    model_config = ConfigDict(from_attributes=True)


class CategoryCreate(BaseModel):
    name: str = Field(min_length=2)


class CategoryResponse(BaseModel):
    id: int
    name: str

    model_config = ConfigDict(from_attributes=True)


class CategoryMenuResponse(BaseModel):
    id: int
    name: str
    items: list[MenuItemResponse]


class OrderCreate(BaseModel):
    # user_id в теле больше нет: кто заказывает, сервер узнаёт из токена.
    item_id: int
    quantity: int


class OrderResponse(BaseModel):
    id: int
    user_id: int
    item_id: int
    quantity: int
    status: str
    total_cost: float

    model_config = ConfigDict(from_attributes=True)


class DeliveryAssign(BaseModel):
    order_id: int
    courier_id: int


class DeliveryResponse(BaseModel):
    id: int
    order_id: int
    courier_id: int
    status: str

    model_config = ConfigDict(from_attributes=True)


class LoginSchema(BaseModel):
    """Схема запроса на вход."""

    email: EmailStr
    password: str


class RefreshSchema(BaseModel):
    """Схема запроса на обновление токена и на выход."""

    refresh_token: str


class TokenResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"

    model_config = ConfigDict(from_attributes=True)
