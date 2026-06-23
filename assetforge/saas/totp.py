"""TOTP (RFC 6238) на стандартной библиотеке — для 2FA сотрудников.

Без внешних зависимостей. QR-картинка рендерится опционально (если установлен `qrcode`),
иначе показываем секрет и otpauth-URI для ручного ввода в приложении-аутентификаторе.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import secrets
import struct
import time
from urllib.parse import quote

ISSUER = "AssetForge"
_DIGITS = 6
_PERIOD = 30


def new_secret() -> str:
    """Случайный base32-секрет (160 бит)."""
    return base64.b32encode(secrets.token_bytes(20)).decode("ascii").rstrip("=")


def _code_at(secret: str, counter: int) -> str:
    key = base64.b32decode(secret + "=" * (-len(secret) % 8), casefold=True)
    msg = struct.pack(">Q", counter)
    digest = hmac.new(key, msg, hashlib.sha1).digest()
    offset = digest[-1] & 0x0F
    code = (struct.unpack(">I", digest[offset:offset + 4])[0] & 0x7FFFFFFF) % (10 ** _DIGITS)
    return str(code).zfill(_DIGITS)


def verify(secret: str, code: str, window: int = 1) -> bool:
    """Проверить код с допуском ±window периодов (компенсация рассинхрона часов)."""
    code = (code or "").strip().replace(" ", "")
    if not secret or not code.isdigit():
        return False
    counter = int(time.time()) // _PERIOD
    for drift in range(-window, window + 1):
        if hmac.compare_digest(_code_at(secret, counter + drift), code):
            return True
    return False


def provisioning_uri(secret: str, account: str) -> str:
    label = quote(f"{ISSUER}:{account}")
    return (f"otpauth://totp/{label}?secret={secret}&issuer={quote(ISSUER)}"
            f"&digits={_DIGITS}&period={_PERIOD}")


def qr_data_uri(uri: str) -> str | None:
    """PNG QR как data-URI (если установлен `qrcode`); иначе None — покажем текстом."""
    try:
        import io
        import qrcode
        img = qrcode.make(uri)
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        return "data:image/png;base64," + base64.b64encode(buf.getvalue()).decode("ascii")
    except Exception:  # noqa: BLE001 — qrcode не установлен / любой сбой
        return None
