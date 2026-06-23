"""Пути к ресурсам (web/, presets/) с поддержкой сборки PyInstaller.

В обычном запуске — относительно пакета. В .exe (frozen) — относительно sys._MEIPASS,
куда PyInstaller распаковывает --add-data.
"""
from __future__ import annotations

import sys
from pathlib import Path

_PKG = Path(__file__).resolve().parent


def base_dir() -> Path:
    if getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS"):
        return Path(sys._MEIPASS) / "assetforge"
    return _PKG


def web_dir() -> Path:
    return base_dir() / "web"


def presets_dir() -> Path:
    return base_dir() / "presets"
