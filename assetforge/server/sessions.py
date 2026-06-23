"""Сессии и кэш промежуточных результатов.

Загруженный файл живёт в сессии (по session_id). Сырьё (исходная картинка) дублируется
в общий блоб-стор (kvstore: память/диск/Redis) — поэтому сессию может отдать ЛЮБОЙ воркер
(не только тот, что принял загрузку). Тяжёлые промежуточные результаты (удаление фона,
поиск объектов) кэшируются в памяти процесса по хэшу конфига — чтобы /preview и /export
не гоняли весь pipeline заново.

Лимиты: на одного владельца (MAX_SESSIONS_PER_USER) и общий потолок в процессе
(MAX_SESSIONS). Вытеснение из памяти НЕ теряет картинку — она остаётся в блоб-сторе
(в пределах TTL) и при следующем обращении регидрируется.
"""
from __future__ import annotations

import hashlib
import io
import json
import os
import threading
import time
import uuid
from dataclasses import dataclass, field

from PIL import Image

from ..core.background import BackgroundResult
from ..core.config import PipelineConfig
from ..kvstore import backend

# время жизни простаивающей сессии и потолки числа сессий в памяти процесса
SESSION_TTL_SEC = int(os.environ.get("ASSETFORGE_SESSION_TTL", str(60 * 30)) or 60 * 30)
MAX_SESSIONS = int(os.environ.get("ASSETFORGE_MAX_SESSIONS", "128") or 128)
MAX_SESSIONS_PER_USER = int(os.environ.get("ASSETFORGE_MAX_SESSIONS_PER_USER", "5") or 5)
# сколько вариантов фона/детекта держать в кэше одной сессии (крутят ползунки → растёт)
MAX_CACHE_PER_SESSION = 8

_BLOB_PREFIX = "afsess:"


def _hash(obj) -> str:
    return hashlib.sha1(json.dumps(obj, sort_keys=True, default=str).encode()).hexdigest()[:16]


def _cap(cache: dict, limit: int = MAX_CACHE_PER_SESSION) -> None:
    """Ограничить размер кэша: выкидываем самые старые записи (FIFO по вставке)."""
    while len(cache) > limit:
        cache.pop(next(iter(cache)))


# --- сериализация сырья в блоб-стор ----------------------------------------

def _encode_blob(image: Image.Image, filename: str, owner: str | None) -> bytes:
    meta = json.dumps({"filename": filename, "owner": owner}).encode("utf-8")
    buf = io.BytesIO()
    image.save(buf, format="PNG")
    return len(meta).to_bytes(4, "big") + meta + buf.getvalue()


def _decode_blob(data: bytes) -> tuple[Image.Image, str, str | None]:
    n = int.from_bytes(data[:4], "big")
    meta = json.loads(data[4:4 + n].decode("utf-8"))
    img = Image.open(io.BytesIO(data[4 + n:]))
    img.load()
    if img.mode != "RGBA":
        img = img.convert("RGBA")
    return img, meta.get("filename", "image.png"), meta.get("owner")


@dataclass
class Session:
    id: str
    image: Image.Image                       # исходный RGBA (как загрузили)
    filename: str = "image.png"
    owner: str | None = None
    created: float = field(default_factory=lambda: time.time())
    touched: float = field(default_factory=lambda: time.time())

    # кэши
    _fg_cache: dict[str, BackgroundResult] = field(default_factory=dict)
    _obj_cache: dict[str, list] = field(default_factory=dict)

    def touch(self) -> None:
        self.touched = time.time()

    # --- ключи кэша ----
    @staticmethod
    def bg_key(cfg: PipelineConfig) -> str:
        return _hash(cfg.background.__dict__)

    @staticmethod
    def obj_key(cfg: PipelineConfig) -> str:
        return _hash({
            "bg": cfg.background.__dict__,
            "split": cfg.crop.split,
            "min_area": cfg.crop.min_object_area,
            "thr": cfg.background.trim_alpha_threshold,
        })

    # --- кэшируемые стадии ----
    def foreground(self, cfg: PipelineConfig) -> BackgroundResult:
        from ..core.pipeline import stage_background
        key = self.bg_key(cfg)
        if key not in self._fg_cache:
            self._fg_cache[key] = stage_background(self.image, cfg)
            _cap(self._fg_cache)     # не копим полноразмерные RGBA без предела
        return self._fg_cache[key]

    def objects(self, cfg: PipelineConfig) -> list:
        from ..core.pipeline import stage_detect
        key = self.obj_key(cfg)
        if key not in self._obj_cache:
            fg = self.foreground(cfg)
            self._obj_cache[key] = stage_detect(fg.image, cfg)
            _cap(self._obj_cache)
        return self._obj_cache[key]


class SessionStore:
    """In-memory кэш сессий процесса + общий блоб-стор сырья (kvstore) для кросс-воркера."""

    def __init__(self) -> None:
        self._sessions: dict[str, Session] = {}
        self._lock = threading.Lock()

    def create(self, image: Image.Image, filename: str = "image.png",
               owner: str | None = None) -> Session:
        sid = uuid.uuid4().hex[:12]
        s = Session(id=sid, image=image, filename=filename, owner=owner)
        # сырьё — в общий стор (любой воркер сможет регидрировать сессию)
        try:
            backend().blob_set(_BLOB_PREFIX + sid, _encode_blob(image, filename, owner),
                               SESSION_TTL_SEC)
        except Exception:  # noqa: BLE001 — блоб-стор недоступен → сессия только в этом процессе
            pass
        with self._lock:
            self._sessions[sid] = s
            self._evict_locked(owner)
        return s

    def get(self, sid: str) -> Session | None:
        with self._lock:
            s = self._sessions.get(sid)
            if s:
                s.touch()
                return s
        # нет в этом процессе — пробуем регидрировать из общего блоб-стора
        return self._rehydrate(sid)

    def _rehydrate(self, sid: str) -> Session | None:
        try:
            data = backend().blob_get(_BLOB_PREFIX + sid)
        except Exception:  # noqa: BLE001
            data = None
        if not data:
            return None
        try:
            img, filename, owner = _decode_blob(bytes(data))
        except Exception:  # noqa: BLE001 — битый блоб
            return None
        s = Session(id=sid, image=img, filename=filename, owner=owner)
        with self._lock:
            self._sessions[sid] = s
            self._evict_locked(owner)
        return s

    def drop(self, sid: str) -> None:
        with self._lock:
            self._sessions.pop(sid, None)
        try:
            backend().blob_del(_BLOB_PREFIX + sid)
        except Exception:  # noqa: BLE001
            pass

    def _evict_locked(self, owner: str | None) -> None:
        """Вызывать только под self._lock. Чистим по TTL, по лимиту на пользователя и общему."""
        now = time.time()
        # по TTL
        for k in [k for k, s in self._sessions.items() if now - s.touched > SESSION_TTL_SEC]:
            self._sessions.pop(k, None)
        # по лимиту на владельца (один юзер не вытесняет чужие сессии)
        if owner is not None:
            mine = sorted([(k, s) for k, s in self._sessions.items() if s.owner == owner],
                          key=lambda kv: kv[1].touched)
            for k, _ in mine[: max(0, len(mine) - MAX_SESSIONS_PER_USER)]:
                self._sessions.pop(k, None)
        # общий потолок процесса — выкидываем самые старые
        if len(self._sessions) > MAX_SESSIONS:
            ordered = sorted(self._sessions.items(), key=lambda kv: kv[1].touched)
            for k, _ in ordered[: len(self._sessions) - MAX_SESSIONS]:
                self._sessions.pop(k, None)


STORE = SessionStore()
