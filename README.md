# 🎨 AssetForge

[![Python](https://img.shields.io/badge/Python-3.10%2B-blue?logo=python&logoColor=white)](https://python.org)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.100%2B-009688?logo=fastapi&logoColor=white)](https://fastapi.tiangolo.com/)
[![License](https://img.shields.io/badge/License-MIT-green.svg)](https://opensource.org/licenses/MIT)

*(Scroll down for Russian version / Прокрутите вниз для русской версии)*

## 🇬🇧 English

**AssetForge** is a local-first, high-performance tool for preparing image assets. It automates background removal, smart cropping, resizing, and exporting icon/logo packs for web, desktop, and mobile products.

Whether you are a developer preparing icons for your next app, or a designer needing a quick batch export, AssetForge handles the heavy lifting through a clean Web UI, a Desktop app, or a CLI.

### ✨ Key Features
- **Intelligent Background Removal:** Supports transparent, white, solid, chroma key, and AI-assisted removal.
- **Smart Crop & Split:** Automatically detects content bounds, adds safe padding, and splits multiple objects from a single canvas.
- **Export Presets:** Ready-made presets for favicons, app launchers, Discord, Steam, Android, iOS, and custom dimensions.
- **Multiple Formats:** Export to PNG, ICO, ICNS, WebP, and SVG wrapper.
- **Flexible Interfaces:** 
  - **Web UI:** FastAPI-powered dashboard with live preview.
  - **CLI Mode:** Perfect for batch processing pipelines.
  - **Desktop Wrapper:** Native-like experience via `pywebview`.
- **Optional SaaS Layer:** Built-in support for accounts, billing, quotas, and admin tools (ideal for scaling into a product).

### 🛠 Tech Stack
- **Backend:** Python, FastAPI, Uvicorn, SQLAlchemy
- **Image Processing:** Pillow, NumPy, Rembg (AI), ONNXRuntime
- **Frontend/Desktop:** Jinja2, PyWebview

### 🚀 Quick Start
```bash
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
python -m assetforge
```
Then open `http://localhost:8000` in your browser.

---

## 🇷🇺 Русский

**AssetForge** — это мощный локальный инструмент для подготовки изображений. Он автоматизирует удаление фона, умную обрезку, изменение размера и экспорт наборов иконок и логотипов для веб-, десктоп- и мобильных продуктов.

Проект работает как веб-приложение, утилита командной строки (CLI) и десктопное приложение.

### ✨ Главные возможности
- **Умное удаление фона:** Поддержка прозрачного, белого, сплошного фона, хромакея и AI-удаления.
- **Smart Crop и разделение:** Автоматическое определение границ объекта, добавление отступов и извлечение нескольких объектов с одного изображения.
- **Пресеты для экспорта:** Готовые шаблоны для favicon, иконок приложений, Discord, Steam, Android, iOS.
- **Поддерживаемые форматы:** PNG, ICO, ICNS, WebP и SVG (wrapper).
- **Разные режимы работы:**
  - **Web UI:** Удобный интерфейс на FastAPI с предпросмотром в реальном времени.
  - **CLI:** Режим командной строки для массовой обработки.
  - **Desktop:** Десктопная версия на базе `pywebview`.
- **SaaS Модуль (опционально):** Встроенная поддержка аккаунтов, тарифов, квот, админ-панели и API.

### 🛠 Стек технологий
- **Backend:** Python, FastAPI, Uvicorn, SQLAlchemy
- **Обработка изображений:** Pillow, NumPy, Rembg (AI), ONNXRuntime

### 🚀 Быстрый старт
```bash
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
python -m assetforge
```
Откройте `http://localhost:8000` в браузере.
