<div align="center">

<a name="readme-top"></a>

<img src="assets/screenshot.png" alt="AssetForge Banner" width="100%" style="border-radius: 8px; box-shadow: 0 4px 8px rgba(0,0,0,0.2);" />

# AssetForge

<p align="center">
  <strong>The Ultimate Local-First Image Asset Pipeline</strong>
</p>

<p align="center">
  <a href="#english">English</a> • <a href="#русский">Русский</a>
</p>

<p align="center">
  <a href="https://python.org"><img src="https://img.shields.io/badge/Python-3.10%2B-blue?style=flat-square&logo=python&logoColor=white" alt="Python"></a>
  <a href="https://fastapi.tiangolo.com/"><img src="https://img.shields.io/badge/FastAPI-0.100%2B-009688?style=flat-square&logo=fastapi&logoColor=white" alt="FastAPI"></a>
  <a href="https://opensource.org/licenses/MIT"><img src="https://img.shields.io/badge/License-MIT-success?style=flat-square" alt="License"></a>
  <a href="https://github.com/nimalekyt-bit/assetforge/stargazers"><img src="https://img.shields.io/github/stars/nimalekyt-bit/assetforge?style=flat-square" alt="Stars"></a>
</p>

*AssetForge automates background removal, smart cropping, and batch exporting for developers and designers.*

</div>

<br/>

<details>
<summary><kbd>Table of contents</kbd></summary>

- [🇬🇧 English](#-english)
  - [✨ Features](#-features)
  - [👋🏻 Getting Started](#-getting-started)
  - [📦 Architecture](#-architecture)
- [🇷🇺 Русский](#-русский)
  - [✨ Возможности](#-возможности)
  - [👋🏻 С чего начать](#-с-чего-начать)

</details>

<br/>

## 🇬🇧 English <a id="english"></a>

> [!NOTE]
> **Star Us!** If you find this project useful, please consider giving it a ⭐️. It helps others discover the tool!

AssetForge is a high-performance tool built to handle the heavy lifting of image asset preparation. Whether you're generating iOS/Android app icons, preparing assets for a game, or cleaning up e-commerce product photos, AssetForge provides a seamless experience via Web UI, CLI, or Desktop app.

### ✨ Features

| Feature | Description |
| :--- | :--- |
| 🧠 **AI Background Removal** | Seamlessly extract subjects using Rembg and ONNXRuntime. |
| 🎯 **Smart Auto-Crop** | Detects the actual object boundaries and applies mathematically perfect padding. |
| 📦 **Batch Exporting** | Generate dozens of formats (PNG, ICO, ICNS, WebP) and sizes in a single click. |
| 🔌 **Versatile Interfaces** | Use the Web Dashboard, CLI mode, or Native Desktop App wrapper (`pywebview`). |
| ☁️ **SaaS Ready** | Includes built-in billing adapters, quota management, and an admin dashboard. |

### 👋🏻 Getting Started

Get up and running in less than 2 minutes.

```bash
git clone https://github.com/nimalekyt-bit/assetforge.git
cd assetforge

# Setup virtual environment
python -m venv .venv

# Activate it (Windows)
.venv\Scripts\activate
# For macOS/Linux: source .venv/bin/activate

pip install -r requirements.txt
python -m assetforge
```

Open `http://localhost:8000` in your browser.

### 📦 Architecture

```text
📦 assetforge
 ┣ 📂 core/         # Image-processing pipeline & AI models
 ┣ 📂 server/       # FastAPI application and routing
 ┣ 📂 web/          # Frontend assets (HTML, CSS, JS)
 ┣ 📂 saas/         # Billing, user accounts, quotas, and admin APIs
 ┣ 📂 presets/      # JSON configuration for export presets
 ┣ 📜 cli.py        # Command-line interface entry point
 ┗ 📜 desktop.py    # Desktop wrapper
```

<p align="right"><a href="#readme-top">⤴️ Back to Top</a></p>

---

## 🇷🇺 Русский <a id="русский"></a>

> [!NOTE]
> **Поддержите проект!** Если вам нравится этот инструмент, поставьте ⭐️ репозиторию.

AssetForge — это мощный локальный инструмент для подготовки изображений. Если вы когда-либо тратили часы на удаление фона, выравнивание иконок или нарезку логотипов под разные платформы, этот инструмент сделает всё за вас.

### ✨ Возможности

| Фича | Описание |
| :--- | :--- |
| 🧠 **Удаление фона** | Поддержка хромакея и AI-удаления (Rembg / ONNXRuntime). |
| 🎯 **Smart Auto-Crop** | Алгоритм сам находит границы объекта и добавляет идеальные отступы. |
| 📦 **Массовый экспорт** | Готовые пресеты для favicon, иконок приложений (iOS/Android), Discord и Steam. |
| 🔌 **Три режима** | Удобный Web UI, мощный CLI и Desktop-версия. |
| ☁️ **SaaS Модуль** | Встроенная админка, биллинг и квоты для запуска как SaaS-продукта. |

### 👋🏻 С чего начать

```bash
git clone https://github.com/nimalekyt-bit/assetforge.git
cd assetforge

# Создать окружение
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt

# Запустить приложение
python -m assetforge
```

<p align="right"><a href="#readme-top">⤴️ Back to Top</a></p>
