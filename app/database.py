"""
Модуль инициализации подключения к СУБД.
Строка подключения берётся из настроек (DATABASE_URL в .env). Для локального
запуска без Docker можно указать DATABASE_URL=sqlite:///./sirius.db.
"""
from sqlalchemy import create_engine
from sqlalchemy.pool import StaticPool
from sqlalchemy.orm import sessionmaker, declarative_base

from app.core.config import settings

DATABASE_URL = settings.DATABASE_URL

# SQLite по умолчанию запрещает использовать соединение из другого потока,
# а FastAPI выполняет синхронные обработчики в пуле потоков.
connect_args = {"check_same_thread": False} if DATABASE_URL.startswith("sqlite") else {}

# SQLite в памяти (используется в тестах) живёт, пока открыто соединение,
# поэтому все сессии должны делить одно соединение.
if DATABASE_URL in ("sqlite://", "sqlite:///:memory:"):
    pool_args = {"poolclass": StaticPool}
elif DATABASE_URL.startswith("sqlite"):
    pool_args = {}
else:
    pool_args = {"pool_size": settings.DB_POOL_SIZE, "max_overflow": settings.DB_MAX_OVERFLOW,
                 "pool_timeout": settings.DB_POOL_TIMEOUT}

# pool_pre_ping: после перезапуска PostgreSQL старые соединения пула мертвы,
# без проверки первый запрос получил бы 500 (видно в demo/03_dlq.sh).
engine = create_engine(DATABASE_URL, connect_args=connect_args, echo=settings.SQL_ECHO,
                       pool_pre_ping=True, **pool_args)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()


def get_db():
    """Генератор сессии базы данных для использования в Depends."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
