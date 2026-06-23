# AssetForge

AssetForge is a local-first tool for preparing image assets: background removal, smart cropping, resizing and exporting icon/logo packs for web, desktop and mobile products.

The project works as a web app, a CLI tool and a Windows desktop wrapper. It also includes an optional SaaS layer with accounts, plans, quotas, admin tools and API access.

## Highlights

- Automatic background detection: transparent, white, solid, chroma key and AI-assisted removal.
- Smart crop and split: detects content bounds, adds padding and can split multiple objects from one image.
- Export presets for favicons, launchers, Discord, Steam, Android, iOS and custom sizes.
- Multiple output formats: PNG, ICO, ICNS, WebP and SVG wrapper.
- FastAPI web interface with live preview.
- CLI mode for batch processing.
- Optional desktop mode through `pywebview`.
- Optional SaaS mode with auth, billing adapters, quotas, admin dashboard and public API.
- Test suite for image-processing metrics, SaaS flows and admin features.

## Stack

- Python
- FastAPI / Uvicorn
- Pillow / NumPy
- SQLAlchemy / Alembic
- Jinja2
- Optional: rembg, onnxruntime, Redis, pywebview

## Quick Start

```bash
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
python -m assetforge
```

The local web interface starts in the browser. For online deployment, run:

```bash
uvicorn assetforge.server.app:app --host 0.0.0.0 --port 8000
```

## CLI

```bash
python -m assetforge.cli logo.png -o out --preset icon-set
python -m assetforge.cli assets/ -o out --preset all --split auto --bg auto
python -m assetforge.cli a.png b.png -o out --sizes 16,32,64,128 --formats png,ico --zip
```

## SaaS Mode

```bash
python run_saas.py
```

SaaS mode includes registration, login, plans, quotas, promo codes, API keys, admin roles, audit logs, settings, payment adapters and desktop release management.

## Tests

```bash
python -m tests.test_engine
python -m tests.test_saas
python -m tests.test_admin
python -m tests.test_hardening
python -m tests.test_features
```

## Project Structure

```text
assetforge/
  core/       image-processing pipeline
  server/     FastAPI app and local web interface
  web/        frontend assets for the local tool
  saas/       accounts, plans, payments, admin and public API
  presets/    JSON export presets
  cli.py      batch-processing CLI
  desktop.py  desktop wrapper
migrations/   Alembic migrations
installer/    desktop installer helpers
tests/        engine, SaaS, admin and hardening tests
```

## Notes

This repository intentionally excludes local secrets, databases, generated builds and temporary processing output. Use `.env.example` as a template for local configuration.
