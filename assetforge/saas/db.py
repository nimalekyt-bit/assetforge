"""Подключение к БД (SQLAlchemy 2.0) и сессии."""
from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager

from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import Session, sessionmaker

from ..logging_setup import get_logger
from .config import settings

log = get_logger("db")

# SQLite требует check_same_thread=False для использования в многопоточном uvicorn
_is_sqlite = settings.db_url.startswith("sqlite")
_connect_args = {"check_same_thread": False} if _is_sqlite else {}
# Для облачного Postgres (Supabase и пр.): pre-ping переустанавливает «протухшие»
# соединения, которые пулер закрывает по простою; recycle подстраховывает.
_engine_kw = {} if _is_sqlite else {"pool_pre_ping": True, "pool_recycle": 300}
engine = create_engine(settings.db_url, echo=False, future=True,
                       connect_args=_connect_args, **_engine_kw)
SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False, future=True)


def _column_ddl_default(col) -> str:
    """SQL-фрагмент DEFAULT для ALTER ADD COLUMN, если у колонки есть константный дефолт."""
    d = getattr(col.default, "arg", None) if col.default is not None else None
    if d is None or callable(d):
        return ""
    if isinstance(d, bool):
        return " DEFAULT TRUE" if d else " DEFAULT FALSE"   # портабельно: Postgres+SQLite
    if isinstance(d, (int, float)):
        return f" DEFAULT {d}"
    if isinstance(d, str):
        return " DEFAULT '" + d.replace("'", "''") + "'"
    return ""


def _ensure_columns() -> None:
    """Лёгкая авто-миграция: добавляет недостающие колонки в существующие таблицы.

    create_all() создаёт только отсутствующие таблицы, но не достраивает старые.
    Это безопасно достраивает новые поля (например User.reset_token) без потери данных
    и без Alembic. Только для аддитивных изменений (новые колонки с дефолтом/nullable).
    """
    from . import models
    insp = inspect(engine)
    existing = set(insp.get_table_names())
    with engine.begin() as conn:
        for table in models.Base.metadata.sorted_tables:
            if table.name not in existing:
                continue
            have = {c["name"] for c in insp.get_columns(table.name)}
            for col in table.columns:
                if col.name in have:
                    continue
                if not col.nullable and col.default is None:
                    log.warning("пропущена колонка %s.%s (NOT NULL без дефолта — нужна ручная миграция)",
                                table.name, col.name)
                    continue
                coltype = col.type.compile(dialect=engine.dialect)
                ddl = f'ALTER TABLE {table.name} ADD COLUMN {col.name} {coltype}{_column_ddl_default(col)}'
                conn.execute(text(ddl))
                log.info("добавлена колонка %s.%s", table.name, col.name)


def init_db() -> None:
    """Создать таблицы (idempotent) и достроить недостающие колонки."""
    from . import models  # noqa: F401 — регистрирует модели в metadata
    models.Base.metadata.create_all(engine)
    _ensure_columns()


@contextmanager
def session_scope() -> Iterator[Session]:
    """Транзакционная сессия: commit при успехе, rollback при ошибке."""
    s = SessionLocal()
    try:
        yield s
        s.commit()
    except Exception:
        s.rollback()
        raise
    finally:
        s.close()


def get_db() -> Iterator[Session]:
    """FastAPI-зависимость: открыть сессию на время запроса."""
    s = SessionLocal()
    try:
        yield s
        s.commit()
    except Exception:
        s.rollback()
        raise
    finally:
        s.close()
