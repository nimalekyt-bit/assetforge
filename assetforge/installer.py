"""Самоустановка desktop-приложения AssetForge (Windows, без прав администратора).

Один файл AssetForge.exe умеет:
  • определить, запущен ли он «из загрузок» или уже установлен;
  • установить себя в %LOCALAPPDATA%\\AssetForge, создать ярлыки (меню Пуск + рабочий стол),
    зарегистрироваться в «Программах и компонентах» (удаление), при необходимости поставить
    WebView2 Runtime;
  • удалить себя (--uninstall).

Установка идёт в пользовательский профиль → НЕ требует админ-прав и UAC.
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

from . import __version__

APP_NAME = "AssetForge"
PUBLISHER = "AssetForge"
EXE_NAME = "AssetForge.exe"

# GUID компонента Evergreen WebView2 Runtime (Microsoft) — по нему проверяем наличие.
_WEBVIEW2_GUID = "{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}"
_WEBVIEW2_BOOTSTRAPPER = "https://go.microsoft.com/fwlink/p/?LinkId=2124703"
_UNINSTALL_KEY = r"Software\Microsoft\Windows\CurrentVersion\Uninstall\AssetForge"

# флаг для subprocess: не мигать консольными окнами
_NO_WINDOW = 0x08000000 if os.name == "nt" else 0


def install_root() -> Path:
    base = os.environ.get("LOCALAPPDATA") or str(Path.home() / "AppData" / "Local")
    return Path(base) / APP_NAME


def installed_exe() -> Path:
    return install_root() / EXE_NAME


def is_frozen() -> bool:
    return bool(getattr(sys, "frozen", False))


def current_exe() -> Path:
    return Path(sys.executable).resolve()


def is_installed() -> bool:
    """True, если работаем уже из установленной копии (или не frozen — dev-режим)."""
    if not is_frozen():
        return True   # запуск из исходников — установка не нужна
    try:
        return os.path.normcase(str(current_exe())) == os.path.normcase(str(installed_exe().resolve()))
    except OSError:
        return False


def needs_install() -> bool:
    """Нужно показать установку: это frozen-exe, запущенный НЕ из места установки."""
    return is_frozen() and not is_installed()


def installed_version() -> str | None:
    """Версия уже установленной копии (из реестра), либо None если не установлено."""
    if os.name != "nt":
        return None
    if not installed_exe().exists():
        return None
    import winreg
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, _UNINSTALL_KEY) as k:
            ver, _ = winreg.QueryValueEx(k, "DisplayVersion")
            return str(ver) if ver else "0"
    except OSError:
        return "0"   # exe есть, записи нет — считаем «древней» версией


# --- сам процесс установки --------------------------------------------------

def install(progress_cb=None) -> Path:
    """Скопировать exe в install_root, создать ярлыки и запись удаления.

    progress_cb(stage: str, pct: int) — для брендированного окна. Возвращает путь exe.
    """
    def step(stage, pct):
        if progress_cb:
            try:
                progress_cb(stage, pct)
            except Exception:  # noqa: BLE001
                pass

    root = install_root()
    step("Подготовка папки…", 5)
    root.mkdir(parents=True, exist_ok=True)

    step("Копирование приложения…", 20)
    dst = installed_exe()
    _copy_self(dst)

    step("Создание ярлыков…", 65)
    _make_shortcuts(dst)

    step("Регистрация в системе…", 80)
    _register_uninstall(dst)

    step("Готово", 100)
    return dst


def _copy_self(dst: Path) -> None:
    import shutil
    src = current_exe()
    if os.path.normcase(str(src)) == os.path.normcase(str(dst)):
        return
    # если старая копия запущена/занята — пишем рядом и подменяем
    try:
        shutil.copy2(src, dst)
    except PermissionError:
        tmp = dst.with_suffix(".new.exe")
        shutil.copy2(src, tmp)
        os.replace(tmp, dst)


def _start_menu_dir() -> Path:
    appdata = os.environ.get("APPDATA") or str(Path.home() / "AppData" / "Roaming")
    return Path(appdata) / "Microsoft" / "Windows" / "Start Menu" / "Programs"


def _desktop_dir() -> Path:
    return Path.home() / "Desktop"


def _make_shortcuts(exe: Path) -> None:
    for folder in (_start_menu_dir(), _desktop_dir()):
        try:
            folder.mkdir(parents=True, exist_ok=True)
            _create_shortcut(folder / f"{APP_NAME}.lnk", exe)
        except Exception:  # noqa: BLE001 — ярлык не критичен для запуска
            pass


def _create_shortcut(lnk: Path, target: Path) -> None:
    """Создать .lnk через WScript.Shell (PowerShell) — без сторонних зависимостей."""
    ps = (
        "$s=(New-Object -ComObject WScript.Shell).CreateShortcut('{lnk}');"
        "$s.TargetPath='{tgt}';"
        "$s.WorkingDirectory='{wd}';"
        "$s.IconLocation='{tgt},0';"
        "$s.Description='AssetForge — нарезка ассетов, удаление фона, иконки';"
        "$s.Save()"
    ).format(lnk=str(lnk), tgt=str(target), wd=str(target.parent))
    subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-Command", ps],
                   creationflags=_NO_WINDOW, check=False,
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def _register_uninstall(exe: Path) -> None:
    if os.name != "nt":
        return
    import winreg
    root = install_root()
    size_kb = 0
    try:
        size_kb = int(exe.stat().st_size / 1024)
    except OSError:
        pass
    values = {
        "DisplayName": (winreg.REG_SZ, APP_NAME),
        "DisplayVersion": (winreg.REG_SZ, __version__),
        "Publisher": (winreg.REG_SZ, PUBLISHER),
        "DisplayIcon": (winreg.REG_SZ, str(exe)),
        "InstallLocation": (winreg.REG_SZ, str(root)),
        "UninstallString": (winreg.REG_SZ, f'"{exe}" --uninstall'),
        "QuietUninstallString": (winreg.REG_SZ, f'"{exe}" --uninstall'),
        "NoModify": (winreg.REG_DWORD, 1),
        "NoRepair": (winreg.REG_DWORD, 1),
        "EstimatedSize": (winreg.REG_DWORD, size_kb),
    }
    with winreg.CreateKey(winreg.HKEY_CURRENT_USER, _UNINSTALL_KEY) as k:
        for name, (typ, val) in values.items():
            winreg.SetValueEx(k, name, 0, typ, val)


# --- удаление ---------------------------------------------------------------

def uninstall() -> None:
    """Удалить ярлыки, запись реестра и (отложенно) папку установки."""
    for folder in (_start_menu_dir(), _desktop_dir()):
        lnk = folder / f"{APP_NAME}.lnk"
        try:
            lnk.unlink(missing_ok=True)
        except OSError:
            pass
    if os.name == "nt":
        import winreg
        try:
            winreg.DeleteKey(winreg.HKEY_CURRENT_USER, _UNINSTALL_KEY)
        except OSError:
            pass
    _schedule_self_delete()


def _schedule_self_delete() -> None:
    """Удалить папку установки после выхода (exe не может удалить сам себя на лету)."""
    root = install_root()
    if not root.exists():
        return
    if os.name != "nt":
        import shutil
        shutil.rmtree(root, ignore_errors=True)
        return
    # отложенное удаление через временный .bat: ждём закрытия exe, затем rmdir с
    # повтором. .bat (а не строка в cmd /c) — чтобы кавычки вокруг пути не ломали разбор.
    import tempfile
    r = str(root)
    bat = Path(tempfile.gettempdir()) / "assetforge_uninstall.bat"
    bat.write_text(
        "@echo off\r\n"
        "ping 127.0.0.1 -n 3 >nul\r\n"
        f'rmdir /s /q "{r}"\r\n'
        f'if exist "{r}" (ping 127.0.0.1 -n 2 >nul & rmdir /s /q "{r}")\r\n'
        'del "%~f0"\r\n',
        encoding="ascii",
    )
    subprocess.Popen(["cmd", "/c", str(bat)], creationflags=0x00000008,  # DETACHED_PROCESS
                     cwd=os.environ.get("SystemRoot", "C:\\Windows"),
                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, close_fds=True)


# --- WebView2 Runtime -------------------------------------------------------

def webview2_present() -> bool:
    """Проверить, установлен ли Edge WebView2 Runtime (нужен для нативного окна)."""
    if os.name != "nt":
        return False
    import winreg
    paths = [
        (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\WOW6432Node\Microsoft\EdgeUpdate\Clients\\" + _WEBVIEW2_GUID),
        (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Microsoft\EdgeUpdate\Clients\\" + _WEBVIEW2_GUID),
        (winreg.HKEY_CURRENT_USER, r"SOFTWARE\Microsoft\EdgeUpdate\Clients\\" + _WEBVIEW2_GUID),
    ]
    for hive, sub in paths:
        try:
            with winreg.OpenKey(hive, sub) as k:
                pv, _ = winreg.QueryValueEx(k, "pv")
                if pv and str(pv) not in ("", "0.0.0.0"):
                    return True
        except OSError:
            continue
    return False


def ensure_webview2(progress_cb=None) -> bool:
    """Если WebView2 нет — скачать и тихо установить bootstrapper. True, если в итоге есть."""
    if webview2_present():
        return True
    if os.name != "nt":
        return False
    try:
        from . import update
        import tempfile
        if progress_cb:
            progress_cb("Установка компонента WebView2…", 0)
        boot = Path(tempfile.gettempdir()) / "MicrosoftEdgeWebview2Setup.exe"
        update.download(_WEBVIEW2_BOOTSTRAPPER, str(boot),
                        progress_cb=lambda d, t: progress_cb and progress_cb(
                            "Загрузка WebView2…", int(d * 100 / t) if t else 0))
        subprocess.run([str(boot), "/silent", "/install"],
                       creationflags=_NO_WINDOW, check=False)
    except Exception:  # noqa: BLE001 — не вышло → откат на браузер при запуске
        return False
    return webview2_present()


def launch(exe: Path | None = None) -> None:
    """Запустить установленную копию приложения (новый процесс) и не ждать."""
    target = str(exe or installed_exe())
    subprocess.Popen([target], creationflags=0x00000008,  # DETACHED_PROCESS
                     close_fds=True)
