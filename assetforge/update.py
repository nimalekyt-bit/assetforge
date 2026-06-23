"""Проверка и загрузка обновлений desktop-приложения AssetForge.

Модель: приложение при старте обращается к манифесту (JSON) и сравнивает версии.
Если на сервере версия новее — скачивает новый установщик (.exe) и запускает его.
Всё устойчиво к офлайну: любая сетевая ошибка → просто продолжаем работу без обновления.

Манифест (latest.json) на сервере:
    {
      "version": "0.2.0",
      "url": "https://.../AssetForge-Setup.exe",
      "notes": "Что нового",
      "size": 48230000
    }

URL манифеста настраивается переменной окружения ASSETFORGE_UPDATE_URL.
"""
from __future__ import annotations

import os
import re
import ssl
import urllib.request
from dataclasses import dataclass

from . import __version__

# По умолчанию — локальный сервер (поменяй на свой домен/IP при деплое)
# или задай переменную окружения ASSETFORGE_UPDATE_URL.
DEFAULT_MANIFEST_URL = "http://192.168.0.105:8000/desktop/latest.json"


def manifest_url() -> str:
    return os.environ.get("ASSETFORGE_UPDATE_URL", DEFAULT_MANIFEST_URL).strip()


@dataclass
class Release:
    version: str
    url: str
    notes: str = ""
    size: int = 0


def parse_version(v: str) -> tuple[int, ...]:
    """'1.2.10' → (1, 2, 10). Нечисловые части игнорируем (устойчиво к 'v1.2', '1.2-beta')."""
    nums = re.findall(r"\d+", v or "")
    return tuple(int(n) for n in nums) or (0,)


def is_newer(candidate: str, current: str) -> bool:
    """True, если candidate строго новее current (посегментное числовое сравнение)."""
    a, b = parse_version(candidate), parse_version(current)
    n = max(len(a), len(b))
    a += (0,) * (n - len(a))
    b += (0,) * (n - len(b))
    return a > b


def _opener() -> urllib.request.OpenerDirector:
    # не валим обновление из-за корпоративных прокси/самоподписанных — но по умолчанию
    # проверяем сертификат; контекст создаём явно для предсказуемости.
    ctx = ssl.create_default_context()
    return urllib.request.build_opener(urllib.request.HTTPSHandler(context=ctx))


def fetch_manifest(timeout: float = 4.0) -> Release | None:
    """Скачать и разобрать манифест. None — если недоступен/битый (офлайн-safe)."""
    import json
    url = manifest_url()
    if not url:
        return None
    sep = "&" if "?" in url else "?"
    url = f"{url}{sep}from={__version__}"          # сервер учитывает версию (статистика)
    try:
        req = urllib.request.Request(url, headers={"User-Agent": f"AssetForge/{__version__}"})
        with _opener().open(req, timeout=timeout) as r:
            data = json.loads(r.read().decode("utf-8"))
        ver = str(data.get("version", "")).strip()
        dl = str(data.get("url", "")).strip()
        if not ver or not dl:
            return None
        return Release(version=ver, url=dl, notes=str(data.get("notes", "")),
                       size=int(data.get("size", 0) or 0))
    except Exception:  # noqa: BLE001 — офлайн/таймаут/битый JSON → без обновления
        return None


def check(current: str = __version__, timeout: float = 4.0) -> Release | None:
    """Вернёт Release, если доступна более новая версия, иначе None."""
    rel = fetch_manifest(timeout=timeout)
    if rel and is_newer(rel.version, current):
        return rel
    return None


def download(url: str, dest: str, progress_cb=None, timeout: float = 30.0) -> str:
    """Скачать файл по url в dest, дёргая progress_cb(done_bytes, total_bytes).

    Возвращает путь dest. Бросает исключение при ошибке сети/записи.
    """
    req = urllib.request.Request(url, headers={"User-Agent": f"AssetForge/{__version__}"})
    with _opener().open(req, timeout=timeout) as r:
        total = int(r.headers.get("Content-Length", 0) or 0)
        done = 0
        chunk = 64 * 1024
        tmp = dest + ".part"
        with open(tmp, "wb") as f:
            while True:
                buf = r.read(chunk)
                if not buf:
                    break
                f.write(buf)
                done += len(buf)
                if progress_cb:
                    try:
                        progress_cb(done, total)
                    except Exception:  # noqa: BLE001 — UI-колбэк не должен ронять загрузку
                        pass
    os.replace(tmp, dest)
    return dest
