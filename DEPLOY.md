# Деплой AssetForge SaaS (инструкция)

> Деплой пока **не выполняется** — это пошаговая инструкция на будущее.
> Локально сайт уже работает: `python run_saas.py` → http://127.0.0.1:8000

---

## 0. Что деплоим

`assetforge.saas.app:app` — облачный сайт: лендинг, регистрация/вход, тарифы, оплата,
личный кабинет, админка + сам инструмент под `/app`. Desktop `.exe` деплоить не нужно —
это отдельный офлайн-продукт.

## 1. Переменные окружения (`.env` / окружение сервера)

Обязательно поменять в проде:

```bash
ASSETFORGE_SECRET: сгенерированная случайная строка для подписи cookie-сессий
ASSETFORGE_BASE_URL=https://assetforge.example.com # публичный URL (ссылки/редиректы оплаты)
ASSETFORGE_ADMIN_EMAIL=you@example.com             # этот email при регистрации станет админом
ASSETFORGE_DB_URL=postgresql+psycopg://<user>:<password>@<host>/<db>   # прод-БД (вместо SQLite)
```

Опционально:

```bash
ASSETFORGE_REQUIRE_VERIFY=1          # требовать подтверждение email
ASSETFORGE_EMAIL=smtp                 # реальная почта
SMTP_HOST / SMTP_PORT / SMTP_USER / SMTP_PASSWORD: параметры SMTP-провайдера
ASSETFORGE_CURRENCY=RUB               # валюта цен (USD по умолчанию)

# масштабирование на несколько воркеров/инстансов (общие сессии и rate-limit):
ASSETFORGE_REDIS_URL=redis://localhost:6379/0     # иначе — память процесса (нужны липкие сессии)
ASSETFORGE_SESSION_DIR=/var/lib/assetforge/sessions  # альтернатива Redis для блобов сессий (один хост)

# наблюдаемость и лимиты:
ASSETFORGE_SENTRY_DSN=...             # сбор ошибок (нужен pip install sentry-sdk)
ASSETFORGE_LOG_LEVEL=INFO             # DEBUG/INFO/WARNING/ERROR
ASSETFORGE_MAX_UPLOAD_MB=25           # лимит размера загрузки
ASSETFORGE_MAX_IMAGE_PIXELS=50000000  # защита от «декомпрессионных бомб»

# desktop-приложение (раздаётся этим же сайтом):
ASSETFORGE_RELEASE_DIR=/var/lib/assetforge/releases  # каталог релизов exe (или dist/ по умолчанию)
ASSETFORGE_CLOUD_URL=https://assetforge.example.com  # куда desktop ходит за логином/тарифом
#   а сам desktop собирается с DEFAULT_MANIFEST_URL/ASSETFORGE_UPDATE_URL = {BASE_URL}/desktop/latest.json
```

> Часть настроек меняется **из админки** без передеплоя: режим обслуживания, открытость регистрации,
> анонс (с расписанием), Telegram/webhook-уведомления, IP-allowlist админки и IP-блок-лист сайта,
> тарифы (цены/лимиты), A/B-флаги, релизы десктопа.

Платежи (по умолчанию `manual` — демо без денег). Включить реальные:

```bash
# вариант мира:
ASSETFORGE_PAYMENTS=stripe
STRIPE_SECRET_KEY=<stripe-secret-key>
STRIPE_WEBHOOK_SECRET: секрет webhook из панели Stripe
#   затем: pip install stripe  и раскомментировать вызовы в saas/payments/stripe_provider.py

# вариант РФ:
ASSETFORGE_PAYMENTS=yookassa
YOOKASSA_SHOP_ID=<yookassa-shop-id>
YOOKASSA_SECRET_KEY=<yookassa-secret-key>
#   затем: pip install yookassa  и раскомментировать вызовы в saas/payments/yookassa_provider.py
```

Webhook провайдера настраивается на `POST {BASE_URL}/billing/webhook/{stripe|yookassa}`.

## 2. База данных

- Dev: SQLite (файл `assetforge.db`) создаётся автоматически.
- Прод: **PostgreSQL**. Поставить драйвер `pip install psycopg2-binary` и задать `ASSETFORGE_DB_URL`.
  Таблицы создаются на старте (`init_db()`), недостающие колонки достраиваются авто-миграцией
  (аддитивно, безопасно для Postgres). Для контролируемых миграций подключён **Alembic**:
  `alembic upgrade head` (конфиг `alembic.ini`, ревизии в `migrations/versions/`, URL берётся из
  `ASSETFORGE_DB_URL`). На свежей проде запускайте `alembic upgrade head`.

### 2.1. Supabase (managed Postgres)

Supabase — это управляемый Postgres, приложение работает с ним «из коробки» через `ASSETFORGE_DB_URL`
(меняется только переменная окружения, код не трогаем). Десктоп-`.exe` это НЕ затрагивает — он использует
локальный движок без БД; Supabase нужен только хостящемуся сайту.

1. Создать проект на supabase.com → **Project Settings → Database → Connection string**.
2. Взять **Session pooler** (порт `5432`) — он лучше всего дружит с долгоживущим uvicorn:
   ```
   ASSETFORGE_DB_URL=postgresql+psycopg2://postgres.<ref>:<password>@aws-0-<region>.pooler.supabase.com:5432/postgres?sslmode=require
   ```
   (Прямое подключение `db.<ref>.supabase.co:5432` тоже годится, если у проекта доступен IPv4.)
3. `pip install psycopg2-binary` (драйвер; в repo уже закомментирован в `requirements.txt`).
4. Первый старт сам создаст все таблицы. SSL обязателен — оставьте `?sslmode=require`.
5. В коде уже включены `pool_pre_ping=True` и `pool_recycle=300` — переживают закрытие idle-соединений пулером.

> Транзакционный пулер (порт `6543`) — для serverless/edge; с обычным сервером используйте session-пулер (5432).
> Supabase Auth/Storage не нужны: у нас своя аутентификация (bcrypt + подписанные cookie), файлы не хранятся.

## 3. Запуск (production)

Через Gunicorn + Uvicorn-воркеры (Linux):

```bash
pip install -r requirements.txt gunicorn psycopg[binary]
gunicorn assetforge.saas.app:app \
  -k uvicorn.workers.UvicornWorker -w 4 -b 0.0.0.0:8000 \
  --timeout 120
```

> Важно: сессии инструмента (загруженные картинки) по умолчанию **в памяти процесса**.
> При нескольких воркерах задайте `ASSETFORGE_REDIS_URL` (или `ASSETFORGE_SESSION_DIR` на одном хосте) —
> тогда сессии и rate-limit общие между воркерами. Иначе включите «липкие сессии» или `-w 1`.

## 4. Reverse-proxy (nginx) + HTTPS

```nginx
server {
  listen 443 ssl;
  server_name assetforge.example.com;
  ssl_certificate     /etc/letsencrypt/live/.../fullchain.pem;
  ssl_certificate_key /etc/letsencrypt/live/.../privkey.pem;

  client_max_body_size 50m;          # под загрузку крупных картинок

  location / {
    proxy_pass http://127.0.0.1:8000;
    proxy_set_header Host $host;
    proxy_set_header X-Forwarded-Proto $scheme;
    proxy_set_header X-Forwarded-For $remote_addr;
  }
}
```
HTTPS обязателен: cookie-сессии и оплата по HTTP небезопасны.

## 5. Docker (опционально)

```dockerfile
FROM python:3.11-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt gunicorn psycopg[binary]
COPY . .
ENV PYTHONIOENCODING=utf-8
CMD ["gunicorn","assetforge.saas.app:app","-k","uvicorn.workers.UvicornWorker","-w","4","-b","0.0.0.0:8000"]
```

```bash
docker build -t assetforge .
docker run -p 8000:8000 --env-file .env assetforge
```

## 6. Чеклист перед продом

- [ ] `ASSETFORGE_SECRET` задан случайной строкой (не дефолт!)
- [ ] PostgreSQL вместо SQLite, бэкапы настроены
- [ ] HTTPS включён, `client_max_body_size` поднят
- [ ] Реальный платёжный провайдер подключён и webhook настроен
- [ ] `ASSETFORGE_ADMIN_EMAIL` — твой email; зарегистрируйся им для доступа к `/admin`
- [ ] Email-backend = smtp (для подтверждений/чеков), если включена верификация
- [ ] Решён вопрос сессий при нескольких воркерах (Redis / `ASSETFORGE_SESSION_DIR` / липкие сессии / `-w 1`)
- [ ] `alembic upgrade head` на свежей проде; тарифы проверены (`saas/plans.json` + правки из админки)
- [ ] Desktop собран с прод-`DEFAULT_MANIFEST_URL`/`ASSETFORGE_CLOUD_URL` (HTTPS-домен), exe подписан
- [ ] Заданы лимиты загрузки и (опц.) Sentry; настроен cron на `python -m assetforge.saas.tasks reminders`

> Полный список «что доделать для бизнеса» (платежи ЮKassa, очередь обработки, security-хардненинг,
> интеграции) — в `improvements/09-аудит-saas-desktop.md`.
