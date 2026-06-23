<div align="center">
  <img src="https://placehold.co/120x120/1e1e1e/ffffff?text=AF" alt="AssetForge Logo" width="120" height="120" style="border-radius: 20%; margin-bottom: 20px;" />

  # 🎨 AssetForge

  **The Ultimate Local-First Image Asset Pipeline**

  [![Python](https://img.shields.io/badge/Python-3.10%2B-3776AB?style=for-the-badge&logo=python&logoColor=white)](https://python.org)
  [![FastAPI](https://img.shields.io/badge/FastAPI-0.100%2B-009688?style=for-the-badge&logo=fastapi&logoColor=white)](https://fastapi.tiangolo.com/)
  [![License](https://img.shields.io/badge/License-MIT-success?style=for-the-badge)](https://opensource.org/licenses/MIT)

  *AssetForge automates background removal, smart cropping, and batch exporting for developers and designers.*

  [English](#english) • [Русский](#русский)
</div>

---

<a id="english"></a>
## 🇬🇧 English

AssetForge is a high-performance tool built to handle the heavy lifting of image asset preparation. Whether you're generating iOS/Android app icons, preparing assets for a game, or cleaning up e-commerce product photos, AssetForge provides a seamless experience via Web UI, CLI, or Desktop app.

### ✨ Why AssetForge?

> **"Stop wasting hours cropping and resizing icons manually."**

- 🧠 **AI-Powered Background Removal**: Seamlessly extract subjects using Rembg and ONNXRuntime.
- 🎯 **Smart Auto-Crop**: Detects the actual object boundaries and applies safe, mathematically perfect padding.
- 📦 **Batch Exporting**: Generate dozens of formats (PNG, ICO, ICNS, WebP) and sizes (16px to 1024px) in a single click.
- 🔌 **Versatile Interfaces**:
  - **Web Dashboard**: Clean, responsive FastAPI interface with live previews.
  - **CLI Mode**: Perfect for integrating into CI/CD pipelines.
  - **Native Desktop**: Packaged as a standalone app via `pywebview`.
- ☁️ **SaaS Ready**: Includes built-in billing adapters, quota management, and an admin dashboard.

<br>

<div align="center">
  <!-- TODO: Replace with an actual screenshot -->
  <img src="https://placehold.co/800x400/1e1e1e/ffffff?text=Drop+your+awesome+screenshot+here" alt="AssetForge UI" style="border-radius: 8px; box-shadow: 0 4px 8px rgba(0,0,0,0.2);" />
</div>

<br>

### 🚀 Quick Start

Get up and running in less than 2 minutes.

```bash
# 1. Clone the repository
git clone https://github.com/nimalekyt-bit/assetforge.git
cd assetforge

# 2. Set up the virtual environment
python -m venv .venv

# On Windows:
.venv\Scripts\activate
# On macOS/Linux:
# source .venv/bin/activate

# 3. Install dependencies
pip install -r requirements.txt

# 4. Launch the Web UI
python -m assetforge
```
🌐 Open `http://localhost:8000` in your browser.

---

### 📂 Architecture Overview

```text
📦 assetforge
 ┣ 📂 core/         # Image-processing pipeline & AI models
 ┣ 📂 server/       # FastAPI application and routing
 ┣ 📂 web/          # Frontend assets (HTML, CSS, JS)
 ┣ 📂 saas/         # Billing, user accounts, quotas, and admin APIs
 ┣ 📂 presets/      # JSON configuration for export presets (iOS, Android, Steam)
 ┣ 📜 cli.py        # Command-line interface entry point
 ┗ 📜 desktop.py    # Desktop wrapper (pywebview)
```

<br>

---

<a id="русский"></a>
## 🇷🇺 Русский

AssetForge — это мощный локальный инструмент для подготовки изображений. Если вы когда-либо тратили часы на удаление фона, выравнивание иконок или нарезку логотипов под разные платформы (iOS, Android, Web), этот инструмент сделает всё за вас.

### ✨ Почему AssetForge?

> **"Автоматизируйте рутину работы с графикой."**

- 🧠 **Умное удаление фона**: Поддержка хромакея и AI-удаления фона (Rembg / ONNXRuntime).
- 🎯 **Smart Auto-Crop**: Алгоритм сам находит границы объекта и добавляет идеальные отступы.
- 📦 **Массовый экспорт**: Готовые пресеты для генерации favicon, иконок приложений, ассетов для Discord, Steam, iOS и Android.
- 🔌 **Три режима работы**:
  - **Web UI**: Удобный дашборд с предпросмотром.
  - **CLI**: Для интеграции в пайплайны и массовой обработки.
  - **Desktop**: Нативное приложение через `pywebview`.
- ☁️ **SaaS Модуль**: Встроенная админка, биллинг, квоты и система пользователей (для развертывания как полноценного продукта).

<br>

### 🚀 Быстрый старт

```bash
git clone https://github.com/nimalekyt-bit/assetforge.git
cd assetforge
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
python -m assetforge
```
🌐 Откройте `http://localhost:8000` в браузере.
