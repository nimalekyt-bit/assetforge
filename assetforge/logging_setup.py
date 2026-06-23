"""Единая настройка логирования AssetForge.

Уровень — через ASSETFORGE_LOG_LEVEL (DEBUG/INFO/WARNING/ERROR), по умолчанию INFO.
Опционально Sentry: если задан ASSETFORGE_SENTRY_DSN и установлен sentry-sdk —
ошибки уходят туда (мягкая зависимость, без неё всё работает).
"""
from __future__ import annotations

import logging
import os
import sys
from collections import deque

_CONFIGURED = False

# кольцевой буфер последних записей (для просмотра в админке)
_RING: deque = deque(maxlen=500)


class _RingHandler(logging.Handler):
    def emit(self, record: logging.LogRecord) -> None:
        try:
            _RING.append({
                "time": self.formatter.formatTime(record, "%Y-%m-%d %H:%M:%S") if self.formatter else "",
                "level": record.levelname,
                "name": record.name,
                "msg": record.getMessage(),
            })
        except Exception:  # noqa: BLE001
            pass


def recent_logs(limit: int = 200, level: str | None = None) -> list[dict]:
    items = list(_RING)[::-1]
    if level:
        items = [r for r in items if r["level"] == level.upper()]
    return items[:limit]


def setup_logging() -> logging.Logger:
    global _CONFIGURED
    logger = logging.getLogger("assetforge")
    if _CONFIGURED:
        return logger
    level_name = os.environ.get("ASSETFORGE_LOG_LEVEL", "INFO").upper()
    level = getattr(logging, level_name, logging.INFO)

    handler = logging.StreamHandler(sys.stderr)
    handler.setFormatter(logging.Formatter(
        "%(asctime)s %(levelname)-7s [%(name)s] %(message)s", "%Y-%m-%d %H:%M:%S"))
    logger.addHandler(handler)
    # кольцевой буфер для просмотра логов в админке (WARNING и выше)
    ring = _RingHandler()
    ring.setLevel(logging.WARNING)
    ring.setFormatter(handler.formatter)
    logger.addHandler(ring)
    logger.setLevel(level)
    logger.propagate = False

    _init_sentry(logger)
    _CONFIGURED = True
    return logger


def _init_sentry(logger: logging.Logger) -> None:
    dsn = os.environ.get("ASSETFORGE_SENTRY_DSN", "").strip()
    if not dsn:
        return
    try:
        import sentry_sdk
        sentry_sdk.init(dsn=dsn, traces_sample_rate=0.0,
                        environment=os.environ.get("ASSETFORGE_ENV", "dev"))
        logger.info("Sentry подключён.")
    except Exception as exc:  # noqa: BLE001 — мягкая зависимость
        logger.warning("Sentry DSN задан, но sentry-sdk недоступен: %s", exc)


def get_logger(name: str = "assetforge") -> logging.Logger:
    setup_logging()
    return logging.getLogger(name if name.startswith("assetforge") else f"assetforge.{name}")


log = setup_logging()
