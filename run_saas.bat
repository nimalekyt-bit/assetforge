@echo off
REM Запуск облачного SaaS-сайта AssetProcessor (http://127.0.0.1:8000)
cd /d "%~dp0"
set PYTHONIOENCODING=utf-8
python -m uvicorn assetforge.saas.app:app --host 127.0.0.1 --port 8000
pause
