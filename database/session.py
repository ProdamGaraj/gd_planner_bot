import logging
import os

from sqlalchemy import create_engine, event, inspect, text
from sqlalchemy.engine import Engine
from sqlalchemy.engine.url import make_url
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import NullPool, StaticPool

from config import DATABASE_URL
from .models import Base

# Сколько секунд ждать, если БД занята записью другого запроса
SQLITE_BUSY_TIMEOUT = 15


def make_engine(url: str) -> Engine:
    is_sqlite = url.startswith("sqlite")
    kwargs = {}
    if is_sqlite:
        kwargs["connect_args"] = {"check_same_thread": False, "timeout": SQLITE_BUSY_TIMEOUT}
        if make_url(url).database in (None, "", ":memory:"):
            # In-memory база (тесты): одно соединение на всех, иначе у каждого своя пустая БД
            kwargs["poolclass"] = StaticPool
        else:
            # Хендлеры держат сессию, пока ждут ответа Telegram. С пулом по умолчанию
            # (5 + 10) при наплыве клиентов соединения кончались (TimeoutError).
            # Для файловой SQLite соединение дешёвое — открываем на каждый запрос.
            kwargs["poolclass"] = NullPool
    engine = create_engine(url, **kwargs)
    if is_sqlite:
        @event.listens_for(engine, "connect")
        def _sqlite_pragmas(dbapi_conn, _record):
            cur = dbapi_conn.cursor()
            cur.execute("PRAGMA foreign_keys=ON")
            cur.execute("PRAGMA journal_mode=WAL")
            cur.close()
    return engine


engine = make_engine(DATABASE_URL)
SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


def init_db(target: Engine = engine) -> None:
    url = make_url(str(target.url))
    if url.get_backend_name() == "sqlite" and url.database and url.database != ":memory:":
        os.makedirs(os.path.dirname(os.path.abspath(url.database)), exist_ok=True)
    Base.metadata.create_all(bind=target)
    add_missing_columns(target)


def add_missing_columns(target: Engine) -> list[str]:
    """Добавить в существующие таблицы новые колонки моделей (create_all этого не делает).

    Только добавление: колонки без значения по умолчанию добавляются как NULL,
    с default — как NOT NULL DEFAULT. Возвращает добавленные «таблица.колонка».
    """
    added = []
    inspector = inspect(target)
    with target.begin() as conn:
        for table in Base.metadata.sorted_tables:
            existing = {c["name"] for c in inspector.get_columns(table.name)}
            for column in table.columns:
                if column.name in existing:
                    continue
                ddl = f"ALTER TABLE {table.name} ADD COLUMN {column.name} {column.type.compile(target.dialect)}"
                default = column.default.arg if column.default is not None and column.default.is_scalar else None
                if default is not None:
                    literal = int(default) if isinstance(default, bool) else default
                    ddl += f" NOT NULL DEFAULT {literal!r}" if not column.nullable else f" DEFAULT {literal!r}"
                conn.execute(text(ddl))
                added.append(f"{table.name}.{column.name}")
    if added:
        logging.getLogger(__name__).info("Миграция БД: добавлены колонки %s", ", ".join(added))
    return added
