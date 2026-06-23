#!/usr/bin/env bash
# Запуск веб-интерфейса AssetForge.
cd "$(dirname "$0")" || exit 1
export PYTHONIOENCODING=utf-8
exec python -m assetforge
