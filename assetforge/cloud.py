"""Клиент к облачному SaaS из desktop-приложения (логин/валидация тарифа).

Desktop работает локально, но за аккаунтом/тарифом ходит в облако. Все вызовы
устойчивы к офлайну: при сетевой ошибке возвращаем None (выше по стеку — гостевой режим).

Адрес облака настраивается ASSETFORGE_CLOUD_URL (по умолчанию — локальная сеть).
"""
from __future__ import annotations

import json
import os
import ssl
import urllib.error
import urllib.request

DEFAULT_CLOUD_URL = "http://192.168.0.105:8000"


def cloud_base() -> str:
    return os.environ.get("ASSETFORGE_CLOUD_URL", DEFAULT_CLOUD_URL).strip().rstrip("/")


def pricing_url() -> str:
    return cloud_base() + "/pricing"


def register_url() -> str:
    return cloud_base() + "/register"


def _opener() -> urllib.request.OpenerDirector:
    ctx = ssl.create_default_context()
    return urllib.request.build_opener(urllib.request.HTTPSHandler(context=ctx))


def post_json(path: str, payload: dict, timeout: float = 8.0) -> dict | None:
    """POST JSON на облако. Возвращает разобранный JSON (в т.ч. при 4xx с телом),
    либо None при сетевой ошибке/таймауте/невалидном ответе (офлайн-safe)."""
    url = cloud_base() + path
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        url, data=data, method="POST",
        headers={"Content-Type": "application/json", "User-Agent": "AssetForge-Desktop"},
    )
    try:
        with _opener().open(req, timeout=timeout) as r:
            return json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        try:
            return json.loads(e.read().decode("utf-8"))   # тело ошибки тоже полезно (detail)
        except Exception:  # noqa: BLE001
            return None
    except Exception:  # noqa: BLE001 — офлайн/таймаут/битый JSON
        return None
