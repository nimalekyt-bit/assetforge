"""Подключаемое key-value хранилище для rate-limit и сессий инструмента.

Бэкенд выбирается по окружению (graceful-фолбэк, ничего не падает без инфраструктуры):
  • ASSETFORGE_REDIS_URL   → Redis (счётчики + блобы общие между воркерами/инстансами);
  • ASSETFORGE_SESSION_DIR → блобы на диск (общая ФС → работает для нескольких воркеров
                              на одном хосте), счётчики — в памяти процесса;
  • иначе                  → всё в памяти процесса (по умолчанию; для одного воркера/desktop).

Используется:
  • ratelimit — счётчики с TTL (incr_window);
  • sessions  — блобы (raw-картинка + мета) с TTL, чтобы сессию мог отдать любой воркер.
"""
from __future__ import annotations

import os
import threading
import time
from pathlib import Path

from .logging_setup import get_logger

log = get_logger("kvstore")


# --- бэкенды ---------------------------------------------------------------

class MemoryBackend:
    name = "memory"

    def __init__(self) -> None:
        self._counters: dict[str, tuple[float, int]] = {}   # key -> (expires, count)
        self._blobs: dict[str, tuple[float, bytes]] = {}     # key -> (expires, data)
        self._lock = threading.Lock()

    def incr_window(self, key: str, window: float) -> int:
        now = time.monotonic()
        with self._lock:
            exp, cnt = self._counters.get(key, (0.0, 0))
            if exp < now:
                exp, cnt = now + window, 0
            cnt += 1
            self._counters[key] = (exp, cnt)
            if len(self._counters) > 10000:
                self._counters = {k: v for k, v in self._counters.items() if v[0] >= now}
            return cnt

    def blob_set(self, key: str, data: bytes, ttl: float) -> None:
        with self._lock:
            self._blobs[key] = (time.monotonic() + ttl, data)

    def blob_get(self, key: str) -> bytes | None:
        now = time.monotonic()
        with self._lock:
            v = self._blobs.get(key)
            if not v:
                return None
            if v[0] < now:
                self._blobs.pop(key, None)
                return None
            return v[1]

    def blob_del(self, key: str) -> None:
        with self._lock:
            self._blobs.pop(key, None)


class DiskBlobBackend(MemoryBackend):
    """Счётчики — в памяти (для rate-limit достаточно), блобы — на общий диск."""
    name = "disk"

    def __init__(self, directory: str) -> None:
        super().__init__()
        self._dir = Path(directory)
        self._dir.mkdir(parents=True, exist_ok=True)

    def _path(self, key: str) -> Path:
        safe = key.replace(":", "_").replace("/", "_")
        return self._dir / f"{safe}.blob"

    def blob_set(self, key: str, data: bytes, ttl: float) -> None:
        p = self._path(key)
        try:
            p.write_bytes(data)
            os.utime(p, (time.time(), time.time() + ttl))   # mtime = срок годности
        except OSError as exc:
            log.warning("blob_set на диск не удался (%s) — фолбэк в память", exc)
            super().blob_set(key, data, ttl)

    def blob_get(self, key: str) -> bytes | None:
        p = self._path(key)
        try:
            if not p.exists():
                return super().blob_get(key)
            if p.stat().st_mtime < time.time():      # просрочен
                p.unlink(missing_ok=True)
                return None
            return p.read_bytes()
        except OSError:
            return None

    def blob_del(self, key: str) -> None:
        try:
            self._path(key).unlink(missing_ok=True)
        except OSError:
            pass
        super().blob_del(key)


class RedisBackend:
    name = "redis"

    def __init__(self, url: str) -> None:
        import redis
        self._r = redis.Redis.from_url(url, socket_timeout=3, socket_connect_timeout=3)
        self._r.ping()

    def incr_window(self, key: str, window: float) -> int:
        pipe = self._r.pipeline()
        pipe.incr(key)
        pipe.expire(key, int(window), nx=True)
        cnt, _ = pipe.execute()
        return int(cnt)

    def blob_set(self, key: str, data: bytes, ttl: float) -> None:
        self._r.set(key, data, ex=int(ttl))

    def blob_get(self, key: str) -> bytes | None:
        return self._r.get(key)

    def blob_del(self, key: str) -> None:
        self._r.delete(key)


# --- выбор бэкенда ---------------------------------------------------------

_backend = None
_lock = threading.Lock()


def backend():
    global _backend
    if _backend is not None:
        return _backend
    with _lock:
        if _backend is not None:
            return _backend
        _backend = _build_backend()
    return _backend


def _build_backend():
    redis_url = os.environ.get("ASSETFORGE_REDIS_URL", "").strip()
    if redis_url:
        try:
            b = RedisBackend(redis_url)
            log.info("KV-бэкенд: Redis (%s)", redis_url.split("@")[-1])
            return b
        except Exception as exc:  # noqa: BLE001 — Redis недоступен → фолбэк
            log.warning("Redis недоступен (%s) — фолбэк на локальный бэкенд", exc)
    session_dir = os.environ.get("ASSETFORGE_SESSION_DIR", "").strip()
    if session_dir:
        log.info("KV-бэкенд: диск (%s) для блобов", session_dir)
        return DiskBlobBackend(session_dir)
    log.info("KV-бэкенд: память процесса (один воркер). Для нескольких воркеров задайте "
             "ASSETFORGE_REDIS_URL или ASSETFORGE_SESSION_DIR.")
    return MemoryBackend()
