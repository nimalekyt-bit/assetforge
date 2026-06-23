@echo off
REM Запуск веб-интерфейса AssetForge (откроется в браузере/нативном окне).
cd /d "%~dp0"
set PYTHONIOENCODING=utf-8
python -m assetforge
pause
