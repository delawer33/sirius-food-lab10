"""
Secure by Default: без секретов приложение не стартует.
"""
import pytest
from pydantic import ValidationError

from app.core.config import Settings


def test_secret_key_is_required(monkeypatch):
    monkeypatch.delenv("SECRET_KEY")

    with pytest.raises(ValidationError, match="SECRET_KEY"):
        Settings(_env_file=None)


def test_short_secret_key_is_rejected():
    with pytest.raises(ValidationError, match="не короче 32"):
        Settings(SECRET_KEY="secret", DATABASE_URL="sqlite://", _env_file=None)


def test_production_defaults(monkeypatch):
    for name in ("DEBUG", "ALLOWED_ORIGINS"):
        monkeypatch.delenv(name)

    config = Settings(_env_file=None)

    assert config.DEBUG is False
    assert config.ALLOWED_ORIGINS == []
