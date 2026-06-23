"""Запуск AssetForge как desktop-приложения с самоустановкой и авто-обновлением.

Поведение одного AssetForge.exe:
  • запущен «из загрузок» (ещё не установлен) → брендированное окно УСТАНОВКИ →
    копирует себя в %LOCALAPPDATA%\\AssetForge, ярлыки, WebView2 → запускает установленную копию;
  • запущен из установленной папки → краткая проверка ОБНОВЛЕНИЙ (брендированный сплэш):
    есть новее → скачивает и ставит; нет → сразу открывает приложение в нативном окне.

Флаги:
  --uninstall        удалить приложение (ярлыки, реестр, папку)
  --install-silent   установить без окна (используется авто-обновлением)
  --no-update        пропустить проверку обновлений (открыть приложение сразу)
"""
from __future__ import annotations

import json
import os
import socket
import sys
import tempfile
import threading
import time
from pathlib import Path

import uvicorn

from . import installer, update
from ._ui_html import install_html, splash_html
from . import __version__

HOST = "127.0.0.1"
APP_TITLE = "AssetForge"


def _ensure_std_streams() -> None:
    """windowed-сборка PyInstaller: sys.stdout/stderr == None → uvicorn падает. Чиним."""
    if sys.stdout is None or sys.stderr is None:
        devnull = open(os.devnull, "w", encoding="utf-8")
        if sys.stdout is None:
            sys.stdout = devnull
        if sys.stderr is None:
            sys.stderr = devnull


# --- точка входа ------------------------------------------------------------

def main() -> None:
    _ensure_std_streams()
    args = set(sys.argv[1:])

    if "--uninstall" in args:
        installer.uninstall()
        return

    if "--install-silent" in args:
        exe = installer.install()
        installer.ensure_webview2()
        installer.launch(exe)
        return

    if installer.needs_install():
        # уже установлено? — запускаем установленную копию; переустанавливаем только
        # если этот setup новее (обновление). Иначе повторный запуск setup просто
        # открывает приложение, а не предлагает установку заново.
        if installer.installed_exe().exists():
            inst = installer.installed_version() or "0"
            if update.is_newer(__version__, inst):
                _run_installer()                 # setup новее → переустановка/обновление
            else:
                installer.launch()               # уже установлено → просто открыть
            return
        _run_installer()
        return

    _run_app(check_update="--no-update" not in args)


# --- веб-сервер -------------------------------------------------------------

def _free_port(preferred: int = 8731) -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        try:
            s.bind((HOST, preferred))
            return preferred
        except OSError:
            s.bind((HOST, 0))
            return s.getsockname()[1]


def _serve(port: int) -> None:
    from .server.desktop_app import app
    uvicorn.run(app, host=HOST, port=port, log_level="warning")


def _refresh_entitlement() -> None:
    """Подтянуть сохранённую сессию и (если есть сеть) валидировать тариф в облаке."""
    from .server import entitlement
    from . import cloud
    entitlement.load_cached()
    cur = entitlement.current()
    token = cur.get("token")
    if not token:
        return
    resp = cloud.post_json("/api/desktop/validate", {"token": token}, timeout=3.0)
    if resp is None:
        return                              # офлайн → используем кэш (в пределах грейса)
    if resp.get("ok"):
        entitlement.set_logged_in(resp["token"], resp.get("email"), resp.get("name"),
                                  resp.get("plan", "free"), resp.get("limits") or {})
    else:
        entitlement.clear()                 # токен отозван/просрочен/тариф снят


def _wait_up(port: int, timeout: float = 8.0) -> None:
    deadline = time.time() + timeout
    while time.time() < deadline:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            if s.connect_ex((HOST, port)) == 0:
                return
        time.sleep(0.1)


# --- окно установки ---------------------------------------------------------

class _InstallApi:
    """Мост JS→Python: кнопка «Установить» в окне."""

    def __init__(self) -> None:
        self.go = threading.Event()

    def begin(self) -> None:
        self.go.set()


def _run_installer() -> None:
    try:
        import webview
    except ImportError:
        # нет pywebview → ставим молча и запускаем
        exe = installer.install()
        installer.ensure_webview2()
        installer.launch(exe)
        return

    api = _InstallApi()
    win = webview.create_window(APP_TITLE, html=install_html(), js_api=api,
                                width=600, height=470, resizable=False)

    def worker() -> None:
        api.go.wait()                       # ждём клик «Установить»
        try:
            exe = installer.install(progress_cb=lambda s, p: _stage(win, s, p))
            installer.ensure_webview2(progress_cb=lambda s, p: _stage(win, s, p))
            _notes(win, f"Установлено в:\n{exe.parent}\nЯрлык «AssetForge» создан на рабочем "
                        f"столе и в меню Пуск.")
            _stage(win, "Готово · открываю AssetForge…", 100)
            time.sleep(1.6)
            installer.launch(exe)
        finally:
            _destroy(win)

    try:
        webview.start(worker)
    except Exception:  # noqa: BLE001 — рантайм окна недоступен → молчаливая установка
        exe = installer.install()
        installer.ensure_webview2()
        installer.launch(exe)


# --- окно приложения + проверка обновлений ----------------------------------

def _run_app(check_update: bool = True) -> None:
    port = _free_port()
    url = f"http://{HOST}:{port}/"
    threading.Thread(target=_serve, args=(port,), daemon=True).start()
    _wait_up(port)
    _refresh_entitlement()                  # вход/тариф из кэша + онлайн-валидация

    # 1) быстрая проверка обновлений (без окна). Есть новее → окно загрузки → выход.
    if check_update:
        try:
            rel = update.check(timeout=3.0)
        except Exception:  # noqa: BLE001 — проверка не должна мешать запуску
            rel = None
        if rel and _run_update_window(rel):
            return                          # обновление запущено → процесс завершится

    # 2) приложение в нативном окне (прямой, проверенный путь — без промежуточной навигации)
    if not _open_app_window(url):
        _run_browser(url)


class _AppApi:
    """Мост JS→Python для окна приложения: открыть ссылку (тарифы/регистрация) в браузере."""

    def open_external(self, url: str) -> None:
        try:
            import webbrowser
            webbrowser.open(str(url))
        except Exception:  # noqa: BLE001
            pass


def _open_app_window(url: str) -> bool:
    """Нативное окно прямо на приложении. False — окно недоступно (→ браузер)."""
    try:
        import webview
    except ImportError:
        return False
    try:
        webview.create_window(APP_TITLE, url, js_api=_AppApi(),
                              width=1280, height=860, min_size=(1024, 680))
        webview.start()
        return True
    except Exception as exc:  # noqa: BLE001 — нет WebView2-рантайма → браузер
        print(f"[AssetForge] нативное окно недоступно ({exc}); открываю в браузере.")
        return False


def _run_update_window(rel) -> bool:
    """Окно загрузки обновления. True — обновление скачано и запущена установка (надо выйти)."""
    try:
        import webview
    except ImportError:
        return _silent_update(rel)

    dest = str(Path(tempfile.gettempdir()) / "AssetForge-Setup.exe")
    win = webview.create_window(APP_TITLE, html=splash_html(),
                                width=600, height=470, resizable=False)
    state = {"ok": False}

    def worker() -> None:
        try:
            notes = f"Доступна версия {rel.version}" + (f"\n{rel.notes}" if rel.notes else "")
            _notes(win, notes)
            _stage(win, f"Загрузка обновления {rel.version}…", 0)

            def prog(done: int, total: int) -> None:
                pct = int(done * 100 / total) if total else -1
                _stage(win, f"Загрузка обновления {rel.version}…", pct)

            update.download(rel.url, dest, progress_cb=prog)
            _stage(win, "Применение обновления…", 100)
            time.sleep(0.3)
            import subprocess
            subprocess.Popen([dest, "--install-silent"], creationflags=0x00000008)  # DETACHED
            state["ok"] = True
        except Exception:  # noqa: BLE001 — обновление не удалось → запустим текущую версию
            state["ok"] = False
        finally:
            _destroy(win)

    try:
        webview.start(worker)
    except Exception:  # noqa: BLE001 — окно недоступно → тихое обновление
        return _silent_update(rel)

    if state["ok"]:
        os._exit(0)        # освобождаем порт/файлы для установщика
    return state["ok"]


def _silent_update(rel) -> bool:
    """Обновление без окна (нет pywebview/рантайма): скачать и запустить установку."""
    import subprocess
    dest = str(Path(tempfile.gettempdir()) / "AssetForge-Setup.exe")
    try:
        update.download(rel.url, dest)
    except Exception:  # noqa: BLE001
        return False
    subprocess.Popen([dest, "--install-silent"], creationflags=0x00000008)  # DETACHED
    os._exit(0)
    return True


def _run_browser(url: str) -> None:
    import webbrowser
    print(f"AssetForge запущен: {url}  (Ctrl+C для выхода)")
    webbrowser.open(url)
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        pass


# --- помощники для обновления DOM в окне ------------------------------------

def _stage(win, text: str, pct: int) -> None:
    try:
        win.evaluate_js(f"setStage({json.dumps(text)});setPct({int(pct)})")
    except Exception:  # noqa: BLE001
        pass


def _notes(win, text: str) -> None:
    try:
        win.evaluate_js(f"setNotes({json.dumps(text)})")
    except Exception:  # noqa: BLE001
        pass


def _destroy(win) -> None:
    try:
        win.destroy()
    except Exception:  # noqa: BLE001
        pass


if __name__ == "__main__":
    main()
