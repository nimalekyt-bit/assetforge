@echo off
REM ============================================================================
REM  Сборка дистрибутива AssetForge.exe (один файл = установщик + приложение).
REM  Результат: dist\AssetForge.exe — его и раздаём пользователям.
REM
REM  Что делает готовый exe у пользователя:
REM    1-й запуск (из «Загрузок») -> окно установки -> ставит в %LOCALAPPDATA%,
REM       ярлыки, при необходимости WebView2 -> запускает приложение;
REM    последующие запуски -> тихая проверка обновлений -> приложение.
REM ============================================================================
cd /d "%~dp0"

echo [1/3] Зависимости...
python -m pip install pyinstaller pywebview >nul 2>&1

echo [2/3] Фирменная иконка...
python installer\make_assets.py

echo [3/3] Сборка exe (PyInstaller по AssetForge.spec)...
pyinstaller --noconfirm --clean AssetForge.spec

echo.
echo Готово: dist\AssetForge.exe
echo Раздавайте этот файл пользователям — ни Python, ни библиотеки им не нужны.
pause
