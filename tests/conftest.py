import os
import sys
from datetime import datetime
from unittest.mock import AsyncMock, MagicMock

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Окружение задаём до импорта модулей проекта
os.environ.setdefault("BOT_TOKEN", "test_token")
os.environ["ADMIN_ID"] = "1"
os.environ["DATABASE_URL"] = "sqlite://"

from database.models import Base  # noqa: E402
from database.session import SessionLocal, engine  # noqa: E402
from services.booking_time import TASHKENT_TZ  # noqa: E402


@pytest.fixture
def db_session():
    """Чистая in-memory БД; хендлеры через SessionLocal видят те же данные."""
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    with SessionLocal() as session:
        yield session


def tashkent(year, month, day, hour=0, minute=0) -> datetime:
    return datetime(year, month, day, hour, minute, tzinfo=TASHKENT_TZ)


def _user(user_id: int):
    user = MagicMock()
    user.id = user_id
    user.username = f"user{user_id}"
    user.language_code = "ru"
    return user


@pytest.fixture
def make_message():
    def factory(user_id: int = 100):
        message = AsyncMock()
        message.from_user = _user(user_id)
        return message
    return factory


@pytest.fixture
def make_callback():
    def factory(user_id: int = 100):
        callback = AsyncMock()
        callback.from_user = _user(user_id)
        callback.message = AsyncMock()
        return callback
    return factory
