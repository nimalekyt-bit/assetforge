# 05 — Roadmap

Приоритезация 49 предложенных фич в 4 тира по принципу impact/effort и логической
последовательности зависимостей. Ключевая зависимость: **почти всё опирается на прямоугольные
таргеты W×H (Tier 0)** — это фундамент, без которого Tier 2 нереализуем.

Обозначения: сложность **S/M/L/XL**, эффект **низкий/средний/высокий**.

---

## Tier 0 — Быстрые победы

*S/M-задачи с высоким impact, без тяжёлых зависимостей, поверх существующего кода. Дают видимый
результат за дни. Часть из них — фундамент (rect-targets), без которого остальные тиры невозможны.*

| Фича | Сложность | Эффект |
|------|:---------:|:------:|
| Прямоугольные таргеты W×H в ExportConfig | L | высокий |
| QA-предупреждения о качестве (поверх готового канала notes/warnings) | S | высокий |
| JPG-вывод + retina @2x + непрозрачная подложка | S | средний |
| AVIF + animated-WebP/APNG passthrough | S | средний |
| Контурная die-cut обводка через numpy-дилатацию | M | средний |

### Прямоугольные таргеты W×H в ExportConfig — фундамент
- **Зачем:** `ExportConfig.sizes` — плоский `list[int]`, resize/crop жёстко «квадрат или по ширине».
  Любой несквадратный ассет физически невозможен. **Единственный блокер всей темы покрытия ассетов.**
- **Что сделать:** ввести `NamedTarget {name,w,h,fit,bg,format}` и `ExportConfig.targets: list`. В
  `resize.py` — `render_target(base,w,h,fit,bg,rcfg)` поверх существующего letterbox-кода:
  `fit ∈ {pad|cover|contain|stretch}`, `scale=min/max(w/bw,h/bh)`, ресайз lanczos, paste на холст W×H с
  заливкой bg (RGBA/сплошной/`'auto'`=медиана по краю). `build_export` получает ветку: при непустом
  `targets` рендерит `png/<name>.png` рядом со старым набором. Полная обратная совместимость.
- **В чём «ум»:** `fit=cover` масштабирует+центрирует под точную рамку; `bg='auto'` берёт доминирующий
  цвет края — логотип ложится на согласованную подложку без ручного подбора.
- **Затронуть:** `core/config.py`, `core/resize.py`, `core/export.py`, `core/pipeline.py`, `core/crop.py`.

### QA-предупреждения о качестве ассета
- **Зачем:** канал `meta['warnings']`/`notes` уже есть, но почти пуст. Дешевле всего превратить
  инструмент в «ассистента», который предупреждает «этот логотип будет мылиться в 512».
- **Что сделать:** numpy-проверки после рендера — апскейл выше исходного, bbox <X% холста, низкий
  контраст к подложке, контент упёрся в край, превышение лимита веса. Складывать в `meta['warnings']`,
  показывать в `/api/analyze`, contact-sheet, manifest.
- **Затронуть:** `core/export.py`, `core/pipeline.py`, `server/app.py`, `web/app.js`.

### JPG-вывод + retina @2x + непрозрачная подложка
- **Что сделать:** `'jpg'` в `formats` (Pillow `quality`); `ExportConfig.retina` дублирует каждый
  width/rect-таргет ×2 с суффиксом `@2x`; `bg`=сплошной для email/web (почтовики не любят alpha).
- **Затронуть:** `core/config.py`, `core/export.py`, `core/io_utils.py`.

### AVIF + animated passthrough
- **Что сделать:** `'avif'` в `formats` (try-import `pillow-avif-plugin`, проверять
  `features.check('avif')`); многокадровый вход → animated WebP/APNG через `save_all/append_images`.
- **В чём «ум»:** graceful-фолбэк — нет кодека → note + WebP, офлайн-ядро не ломается.
- **Затронуть:** `core/export.py`, `core/io_utils.py`, `requirements.txt`.

### Контурная die-cut обводка
- **Что сделать:** новый `core/effects.py`: `outline(rgba,width,color)` — дилатация alpha numpy сдвиг-OR,
  минус исходная маска → кольцо, залить, положить под объект. Адаптивная толщина (% от размера).
- **Затронуть:** `core/effects.py`, `core/export.py`, `core/config.py`, `presets/sticker-*.json`.

---

## Tier 1 — Ядро «умности»

*То, что превращает «набор ползунков» в ассистента. Большинство опирается на rect-targets из Tier 0.
Это сердце цели владельца — «сделать УМНЫМ».*

| Фича | Сложность | Эффект |
|------|:---------:|:------:|
| Авто-классификатор типа ассета + рекомендация пресета | M | высокий |
| Saliency / subject-aware центрирование под несквадратные рамки | L | высокий |
| Платформенные бандлы с настоящими манифестами (PWA/Android/iOS/Web) | M→XL | высокий |
| Эффекты подложки: тень, скругление, рамка, safe-area | M | средний |
| История / проекты (повторяемость и доверие) | M | средний |

### Авто-классификатор типа ассета + рекомендация пресета
- **Зачем:** `analyze()` возвращает только `bg_mode/objects/size` — пользователь не знает, какой из 9
  пресетов выбрать. Главный UX-разрыв на входе.
- **Что сделать:** `core/classify.py` — эвристики numpy/Pillow без сети: aspect bbox (>2.2 → wordmark,
  ~1:1 → icon), число уникальных цветов (`convert('P',ADAPTIVE,256).getcolors()`: мало + резкие края →
  vector-like, много + градиенты → photo), наличие исходной альфы, `objects>3` → sprite-sheet. Маппинг
  `kind→preset` таблицей. В `meta`: `asset_kind`, `suggested_preset`, `reasons[]`.
- **Затронуть:** `core/classify.py`, `core/pipeline.py`, `server/app.py`, `web/app.js`, тесты.

### Saliency / subject-aware центрирование
- **Зачем:** при cover-обрезке под несквадратную рамку тупой центр режет логотип/лицо. Нужно сразу
  после rect-targets, иначе `fit=cover` калечит контент.
- **Что сделать:** `core/saliency.py` — карта на чистом numpy: alpha-маска + |Sobel|-градиенты
  (+ опц. spectral-residual FFT). `saliency_center(arr)->(cx,cy)`. В `render_target` при `fit=cover`
  окно позиционируется так, чтобы центр значимости попал в центр (кламп к границам). `focus=[fx,fy]`
  для ручного override. Деградирует к центру при равномерной значимости.
- **Затронуть:** `core/saliency.py`, `core/crop.py`, `core/resize.py`, `core/config.py`, тесты.

### Платформенные бандлы с манифестами
- **Зачем:** инструмент отдаёт голые PNG. Разработчик вручную пишет manifest/Contents.json/densities —
  это съедает основную ценность «готового к интеграции» бандла. Манифесты — шаблоны, не алгоритмы.
- **Что сделать:** генераторы-спутники рядом с PNG: PWA `manifest.json` + maskable (safe-area 80%),
  Android adaptive (foreground/background + mipmap-*dpi), iOS `AppIcon.appiconset/Contents.json`,
  favicon-набор + HTML-сниппет. Новый `kind='bundle'` в `export.py`, пресеты `pwa.json` и т.д.
  **Совет по объёму:** начать с PWA (1 JSON + 3 PNG + HTML — путь M), потом iOS (Contents.json тривиален),
  потом Android adaptive (двуслойность — отдельная задача, путь XL).
- **Затронуть:** `core/export.py`, `core/config.py`, `presets/*.json`, `cli.py`.

### Эффекты подложки
- **Что сделать:** `effects.py`: `rounded()` (ImageDraw.rounded_rectangle/squircle), `drop_shadow()`
  (GaussianBlur альфы), `border()`, `safe_area` overlay для превью. Стадия перед `render_target`.
- **Затронуть:** `core/effects.py`, `core/export.py`, `core/config.py`, `server/app.py`.

### История / проекты
- **Что сделать:** сохранять `PipelineConfig.to_dict()` как «проект/рецепт» в БД (SaaS уже есть),
  кнопка «повторить», список прошлых прогонов. Переиспользует готовую сериализацию конфига.
- **Затронуть:** `saas/models.py`, `saas/routes.py`, `server/app.py`, `saas/templates/account.html`.

---

## Tier 2 — Расширение покрытия ассетов

*Когда есть rect-targets (Tier 0) и saliency-кроп (Tier 1), пресет-паки становятся почти-бесплатными:
`presets/*.json` автоподхватываются. Этот тир делает «почти любой ассет» за счёт контента, не ядра.*

| Фича | Сложность | Эффект |
|------|:---------:|:------:|
| Пресет-пак соцсетей с точными размерами платформ | M | высокий |
| App-store / Play скриншоты в рамке устройства (device-frame) | L | высокий |
| Замена / генерация фона под объект | M | средний |
| Игровой спрайт-атлас (texture atlas) с JSON/CSS-картой | L | средний |
| Печатные ассеты: DPI/мм/bleed/CMYK | M | средний |
| Email/маркетинг пресет-пак (hero/signature/header) | S | средний |

- **Соцсети:** `social-og.json` (1200×630), `twitter.json`, `youtube.json` (+safe-area), `instagram.json`,
  `linkedin.json`, `social-avatars.json`, агрегат `social-all`. После rect-targets — чистый JSON.
- **Device-frame mockup:** `core/mockup.py` — `frame_in_device(content, device_spec)`; спеки устройств в
  `assets/devices/*.json`; процедурная рамка через `ImageDraw.rounded_rectangle` (без бинарников в репо).
- **Замена фона:** объект на сплошной/градиент/авто-палитру/размытый кроп. Управляется `ExportConfig`.
- **Спрайт-атлас:** `core/atlas.py` — shelf-упаковка, `frames`-карта (TexturePacker-hash + CSS). Источник
  кадров — `detect.split_objects`. Переиспользует готовую сегментацию.
- **Печать:** `NamedTarget` + `unit/dpi/bleed_mm/safe_mm`; мм→px; запись DPI в PNG; опц. CMYK.
- **Email:** `email-hero.json` (600/1200@2x), непрозрачный bg, png+jpg. Опирается на retina/JPG из Tier 0.

---

## Tier 3 — Продвинутое / AI и рост

*Тяжёлые зависимости (onnxruntime-модели) и каналы роста (публичный API, плагины). Все AI-ветки — по
паттерну `_remove_ai`: try-import + graceful-фолбэк, чтобы офлайн-ядро не ломалось. Делается последним.*

| Фича | Сложность | Эффект |
|------|:---------:|:------:|
| Опциональное AI-матирование (волосы/полупрозрачность) | L | высокий |
| Edge-preserving / опц.-AI апскейл мелких источников | L | средний |
| Реальная векторизация (PNG→SVG path) для логотипов | L | средний |
| Публичный REST API + ключи (канал роста/интеграций) | M | средний |
| Figma-плагин / интеграции | L | низкий |

- **AI-матирование:** расширить `mode='ai'` — onnxruntime-модель (u2net/isnet/MODNet/BiRefNet) для
  волос/полупрозрачности, trimap из уже посчитанного ramp; фолбэк на color-key с note.
- **Апскейл:** `ResizeConfig.upscale='auto'(auto|lanczos|edge|ai)`; `edge` = многоступенчатый ×2 Lanczos +
  unsharp по Sobel-маске (чистый numpy); `ai` = опц. Real-ESRGAN, фолбэк на `edge`.
- **Векторизация:** настоящая трассировка (potrace/vtracer try-import) для vector-like ассетов (определяет
  `classify`); фото → честный raster-fallback с заметкой.
- **Публичный API:** документированный `/v1/*` поверх существующих ручек, API-ключи и квоты через готовый
  SaaS, OpenAPI-схема даром от FastAPI.
- **Figma-плагин:** тонкий клиент поверх `/v1/*` (требует публичного API).

---

## Логика последовательности (одной картинкой)

```
Tier 0: rect-targets ─┬─► QA-warnings ─┬─► JPG/retina ─► AVIF/animated ─► die-cut outline
                      │                │
                      ▼                ▼
Tier 1: saliency-crop ◄── classify+рекомендация пресета ──► платформенные бандлы ──► эффекты ──► история
                      │
                      ▼
Tier 2: соцсети · device-mockup · замена фона · спрайт-атлас · печать · email   (всё = JSON-пресеты + мелкие генераторы)
                      │
                      ▼
Tier 3: AI-матирование · AI-апскейл · векторизация · публичный API · Figma   (опц. зависимости + рост)
```
