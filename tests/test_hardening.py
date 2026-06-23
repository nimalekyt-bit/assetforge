"""Тесты усиления: лимиты загрузки/бомбы (#1), сессии на пользователя и кросс-воркер
(#5/#6), rate-limit, CSRF (#12). Запуск: python -m tests.test_hardening (или pytest)."""
from __future__ import annotations

import asyncio
import io
import os
import re
import tempfile

from fastapi import HTTPException
from PIL import Image
from starlette.datastructures import UploadFile


def test_pixel_bomb_guard():
    from assetforge.core import io_utils
    saved = io_utils.MAX_IMAGE_PIXELS
    io_utils.MAX_IMAGE_PIXELS = 1000
    try:
        try:
            io_utils.load_rgba(Image.new("RGBA", (50, 50)))   # 2500 > 1000
            assert False, "ожидали ImageTooLargeError"
        except io_utils.ImageTooLargeError:
            pass
    finally:
        io_utils.MAX_IMAGE_PIXELS = saved


def test_upload_size_cap():
    from assetforge.server.app import _read_capped

    async def go():
        big = UploadFile(filename="b.png", file=io.BytesIO(b"x" * 5000))
        try:
            await _read_capped(big, limit=1000)
            return False
        except HTTPException as e:
            return e.status_code == 413
    assert asyncio.run(go())


def test_session_per_user_cap_and_rehydrate():
    from assetforge import kvstore
    kvstore._backend = kvstore.DiskBlobBackend(tempfile.mkdtemp(prefix="af_sess_"))
    from assetforge.server.sessions import SessionStore, MAX_SESSIONS_PER_USER
    s1 = SessionStore()
    ids = [s1.create(Image.new("RGBA", (20, 20), (200, 0, 0, 255)), f"f{i}.png", owner="u1").id
           for i in range(MAX_SESSIONS_PER_USER + 3)]
    in_proc = sum(1 for _, s in s1._sessions.items() if s.owner == "u1")
    assert in_proc <= MAX_SESSIONS_PER_USER, in_proc
    # другой "воркер" — свежий стор, поднимает сессию из общего блоб-стора
    s2 = SessionStore()
    got = s2.get(ids[-1])
    assert got is not None and got.owner == "u1" and got.image.size == (20, 20)


def test_ratelimit_fixed_window():
    from assetforge import kvstore
    kvstore._backend = kvstore.MemoryBackend()
    from assetforge.saas import ratelimit

    class _Req:
        headers: dict = {}

        class _C:
            host = "9.9.9.9"
        client = _C()
    r = _Req()
    assert [ratelimit.allowed(r, "b", 2, 60) for _ in range(3)] == [True, True, False]


def test_csrf_protects_login():
    from fastapi.testclient import TestClient
    from assetforge.saas.app import app
    c = TestClient(app)
    tok = re.search(r'name="csrf_token" value="([^"]+)"', c.get("/login").text)
    assert tok, "нет csrf-токена в форме"
    no = c.post("/login", data={"email": "a@b.com", "password": "x"}, follow_redirects=False)
    assert no.status_code == 403, no.status_code
    ok = c.post("/login", data={"email": "a@b.com", "password": "x",
                                "csrf_token": tok.group(1), "next": "/app"},
                follow_redirects=False)
    assert ok.status_code in (200, 303), ok.status_code


def _run_all():
    import traceback
    tests = [v for k, v in sorted(globals().items())
             if k.startswith("test_") and callable(v)]
    passed = failed = 0
    for t in tests:
        try:
            t(); passed += 1; print(f"  PASS  {t.__name__}")
        except Exception:  # noqa: BLE001
            failed += 1; print(f"  FAIL  {t.__name__}"); traceback.print_exc()
    print(f"\n{passed} passed, {failed} failed из {len(tests)}")
    return failed == 0


if __name__ == "__main__":
    import sys
    sys.exit(0 if _run_all() else 1)
