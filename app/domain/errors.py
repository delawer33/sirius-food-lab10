"""
Исключения бизнес-логики.

Сервисы сообщают о нарушении правил этими исключениями и ничего не знают
про HTTP. Транспортный слой сам решает, какой статус ответа им соответствует.
"""


class DomainError(Exception):
    """Базовое исключение предметной области."""

    def __init__(self, message: str):
        super().__init__(message)
        self.message = message


class NotFoundError(DomainError):
    """Запрошенный объект не существует."""


class BusinessRuleError(DomainError):
    """Операция нарушает бизнес-правило."""


class AlreadyRefundedError(BusinessRuleError):
    """Деньги за заказ уже возвращены: повторная компенсация ничего не делает."""


class AccessDeniedError(DomainError):
    """Операция запрещена для данного участника: чужой объект, блокировка."""


class AuthenticationError(DomainError):
    """Не удалось установить, кто делает запрос: неверный пароль или токен."""


class ServiceUnavailableError(DomainError):
    """Внешний сервис (например, доставки) недоступен. Повторить позже."""


class ServiceTimeoutError(ServiceUnavailableError):
    """Внешний сервис не ответил вовремя. Результат операции неизвестен."""
