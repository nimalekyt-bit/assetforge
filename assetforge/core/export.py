"""Экспорт: генерация размеров/форматов, contact-sheet с подписями, ZIP."""
from __future__ import annotations

import io
import zipfile
from dataclasses import dataclass, field
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

from . import io_utils
from .config import ICNS_SIZES, ICO_SIZES, ICON_SIZES, ExportConfig, ResizeConfig
from .resize import resize_to


@dataclass
class RenderedSize:
    size: int
    image: Image.Image
    has_alpha: bool
    bbox: tuple[int, int, int, int] | None


@dataclass
class ExportArtifact:
    name: str           # имя файла (относительно корня бандла)
    data: bytes
    kind: str           # png | ico | icns | webp | svg | sheet


@dataclass
class ExportResult:
    artifacts: list[ExportArtifact] = field(default_factory=list)
    rendered: list[RenderedSize] = field(default_factory=list)
    meta: dict = field(default_factory=dict)

    def by_kind(self, kind: str) -> list[ExportArtifact]:
        return [a for a in self.artifacts if a.kind == kind]


# --- основной экспорт ------------------------------------------------------

def render_sizes(
    base: Image.Image,
    sizes: list[int],
    rcfg: ResizeConfig,
    square: bool = True,
) -> list[RenderedSize]:
    """Сгенерировать все целевые размеры из подготовленной (обрезанной) картинки."""
    out: list[RenderedSize] = []
    for s in sorted(set(sizes)):
        img = resize_to(base, s, rcfg, square=square)
        out.append(RenderedSize(s, img, _has_alpha(img), img.getbbox()))
    return out


def build_export(
    base: Image.Image,
    ecfg: ExportConfig,
    rcfg: ResizeConfig,
    square: bool = True,
    meta: dict | None = None,
) -> ExportResult:
    """Полный экспорт: PNG-набор + выбранные форматы + contact-sheet (+ всё в ZIP отдельно)."""
    meta = dict(meta or {})
    if getattr(ecfg, "effects", None):          # эффекты (контур/тень/скругление/рамка/фон)
        base = _apply_effects(base, ecfg.effects)
    sizes = sorted({int(s) for s in ecfg.sizes if int(s) > 0})
    # пустой список размеров: при наличии прямоугольных таргетов рендерим ТОЛЬКО их
    # (targets-only пресет, напр. соцсети), иначе берём базовый набор иконок.
    if not sizes and not ecfg.targets:
        sizes = list(ICON_SIZES)
    max_size = max(sizes) if sizes else 0
    rendered = render_sizes(base, sizes, rcfg, square=square) if sizes else []
    result = ExportResult(rendered=rendered, meta=meta)
    bn = ecfg.basename or "icon"
    formats = [f.lower() for f in ecfg.formats]

    # PNG всегда
    for r in rendered:
        result.artifacts.append(
            ExportArtifact(f"png/{bn}_{r.size}.png",
                           io_utils.to_png_bytes(r.image, optimize=ecfg.png_optimize), "png")
        )

    if "webp" in formats:
        for r in rendered:
            result.artifacts.append(
                ExportArtifact(f"webp/{bn}_{r.size}.webp", _save_bytes(r.image, "WEBP",
                               lossless=ecfg.webp_lossless,
                               quality=int(ecfg.webp_quality)), "webp")
            )

    if "jpg" in formats or "jpeg" in formats:
        # JPG не держит прозрачность — кладём на непрозрачную подложку (email/web)
        for r in rendered:
            result.artifacts.append(
                ExportArtifact(f"jpg/{bn}_{r.size}.jpg",
                               _jpg_bytes(r.image, ecfg.jpg_bg, int(ecfg.jpg_quality)), "jpg")
            )

    if "avif" in formats:
        for r in rendered:
            data, ok = _avif_bytes(r.image, int(ecfg.webp_quality))
            if ok:
                result.artifacts.append(ExportArtifact(f"avif/{bn}_{r.size}.avif", data, "avif"))
            else:
                meta.setdefault("warnings", []).append(
                    "AVIF недоступен (нет кодека pillow-avif-plugin) — отдан WebP вместо него.")
                result.artifacts.append(ExportArtifact(f"webp/{bn}_{r.size}.webp", data, "webp"))

    if "svg" in formats and rendered:
        # «SVG wrapper» — PNG, встроенный в SVG (не настоящая векторизация!)
        biggest = max(rendered, key=lambda r: r.size).image
        result.artifacts.append(
            ExportArtifact(f"svg/{bn}.svg", _svg_wrap_bytes(biggest), "svg")
        )

    if "ico" in formats and square and sizes:
        # кадры .ico строим тем же resize_to, что и PNG (один Lanczos-шаг + unsharp
        # на мелких), а не двойным ресайзом из одного квадрата — иначе кадры мылятся
        ico_sizes = [s for s in ICO_SIZES if s <= max_size]
        result.artifacts.append(
            ExportArtifact(f"{bn}.ico", _ico_bytes(base, ico_sizes, rcfg), "ico")
        )

    if "icns" in formats and square and sizes:
        # иконка приложения почти всегда нужна в 1024, поэтому берём полный ICNS_SIZES,
        # а не max запрошенных PNG-размеров (апскейл из базы допустим). Кадры — через
        # resize_to, как у PNG.
        try:
            result.artifacts.append(
                ExportArtifact(f"{bn}.icns", _icns_bytes(base, list(ICNS_SIZES), rcfg), "icns")
            )
        except Exception as exc:  # noqa: BLE001 — .icns капризен к версиям Pillow
            meta.setdefault("warnings", []).append(f".icns не создан: {exc}")

    # непропорциональное лого (square=False): .ico/.icns невозможны — предупреждаем,
    # чтобы запрошенный формат не пропадал молча
    if not square:
        skipped = [f.upper() for f in ("ico", "icns") if f in formats]
        if skipped:
            meta.setdefault("warnings", []).append(
                f"{'/'.join(skipped)} требуют квадрат — пропущены для fit=width (square=False)."
            )

    # --- прямоугольные таргеты W×H (соцсети/стор/печать/email/баннеры) ---
    if ecfg.targets:
        result.artifacts.extend(_render_targets(base, ecfg, rcfg, meta))

    # --- проактивный QA: предупреждаем о потенциальной потере качества ---
    _qa_warnings(base, sizes, ecfg, meta)

    if ecfg.make_contact_sheet and rendered:
        sheet = build_contact_sheet(rendered, meta)
        result.artifacts.append(
            ExportArtifact("contact-sheet.png", io_utils.to_png_bytes(sheet), "sheet")
        )

    return result


# --- прямоугольные таргеты W×H ---------------------------------------------

def _apply_effects(base: Image.Image, effects_cfg: list) -> Image.Image:
    """Применить эффекты подложки к объекту по порядку (контур/тень/скругление/рамка/фон)."""
    from . import effects as fx
    im = base
    for e in effects_cfg:
        t = (e.get("type") or "").lower()
        try:
            if t == "outline":
                im = fx.add_outline(im, e.get("width_pct", 3.0), tuple(e.get("color", [255, 255, 255, 255])))
            elif t == "shadow":
                im = fx.drop_shadow(im, e.get("dx", 0), e.get("dy", 6), e.get("blur", 10),
                                    tuple(e.get("color", [0, 0, 0, 150])), e.get("grow", 0))
            elif t == "rounded":
                im = fx.rounded_corners(im, e.get("radius_pct", 18.0))
            elif t == "border":
                im = fx.add_border(im, e.get("width_pct", 4.0), tuple(e.get("color", [255, 255, 255, 255])))
            elif t == "background":
                im = fx.add_background(im, e.get("bg", [255, 255, 255]))
        except Exception:  # noqa: BLE001 — эффект не должен ронять экспорт
            continue
    return im


def _as_target(t):
    from .config import NamedTarget
    if isinstance(t, NamedTarget):
        return t
    return NamedTarget(name=str(t.get("name", "target")), w=int(t["w"]), h=int(t["h"]),
                       fit=t.get("fit", "contain"), bg=t.get("bg", None), format=t.get("format", "png"))


def _focus_center(base: Image.Image):
    """Центр значимости (saliency) для cover-кропа; graceful-фолбэк к центру."""
    try:
        from .saliency import saliency_center
        return saliency_center(base)
    except Exception:  # noqa: BLE001 — модуль опционален / любой сбой → центр
        return None


def _render_targets(base: Image.Image, ecfg: ExportConfig, rcfg: ResizeConfig, meta: dict):
    from .resize import render_target
    arts: list[ExportArtifact] = []
    focus = _focus_center(base)
    bw, bh = base.size
    for raw in ecfg.targets:
        t = _as_target(raw)
        variants = [(t.w, t.h, "")]
        if ecfg.retina:
            variants.append((t.w * 2, t.h * 2, "@2x"))
        for tw, th, suf in variants:
            img = render_target(base, tw, th, fit=t.fit, bg=t.bg, cfg=rcfg, focus=focus)
            fmt = (t.format or "png").lower()
            data, kind, ext = _encode(img, fmt, ecfg)
            arts.append(ExportArtifact(f"targets/{t.name}{suf}.{ext}", data, kind))
            if tw > bw * 1.3 or th > bh * 1.3:
                meta.setdefault("warnings", []).append(
                    f"Таргет {t.name} {tw}×{th} крупнее исходника {bw}×{bh} — возможна мыльность (апскейл).")
    return arts


def _encode(img: Image.Image, fmt: str, ecfg: ExportConfig):
    """Закодировать изображение в нужный формат → (bytes, kind, ext)."""
    if fmt in ("jpg", "jpeg"):
        return _jpg_bytes(img, ecfg.jpg_bg, int(ecfg.jpg_quality)), "jpg", "jpg"
    if fmt == "webp":
        return _save_bytes(img, "WEBP", lossless=ecfg.webp_lossless, quality=int(ecfg.webp_quality)), "webp", "webp"
    if fmt == "avif":
        data, ok = _avif_bytes(img, int(ecfg.webp_quality))
        return (data, "avif", "avif") if ok else (data, "webp", "webp")
    return io_utils.to_png_bytes(img, optimize=ecfg.png_optimize), "png", "png"


def _jpg_bytes(im: Image.Image, bg, quality: int) -> bytes:
    c = (list(bg) + [255, 255, 255])[:3]
    base = Image.new("RGB", im.size, (int(c[0]), int(c[1]), int(c[2])))
    base.paste(im.convert("RGBA"), mask=im.convert("RGBA").getchannel("A"))
    return _save_bytes(base, "JPEG", quality=int(quality), optimize=True)


def _avif_bytes(im: Image.Image, quality: int):
    """(bytes, ok). Если AVIF-кодек недоступен — graceful-фолбэк на WebP (ok=False)."""
    try:
        from PIL import features
        if features.check("avif"):
            return _save_bytes(im, "AVIF", quality=int(quality)), True
    except Exception:  # noqa: BLE001
        pass
    return _save_bytes(im, "WEBP", quality=int(quality)), False


def _qa_warnings(base: Image.Image, sizes: list[int], ecfg: ExportConfig, meta: dict) -> None:
    """Проактивные предупреждения о качестве (в meta['warnings'])."""
    bw, bh = base.size
    w = meta.setdefault("warnings", [])
    if sizes and max(sizes) > max(bw, bh) * 1.3:
        w.append(f"Размер {max(sizes)}px больше исходника {max(bw, bh)}px — иконка будет мылиться (апскейл).")
    # контент почти во весь кадр без полей — обрежется впритык
    bb = base.getbbox()
    if bb:
        cov = ((bb[2] - bb[0]) * (bb[3] - bb[1])) / float(bw * bh)
        if cov > 0.98:
            w.append("Контент занимает весь кадр без полей — на квадратных иконках края могут обрезаться.")
    if not w:
        meta.pop("warnings", None)


def package_zip(result: ExportResult) -> bytes:
    """Упаковать все артефакты в ZIP (со структурой папок из имён артефактов)."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for a in result.artifacts:
            zf.writestr(a.name, a.data)
        if result.meta:
            zf.writestr("manifest.txt", _manifest_text(result))
    return buf.getvalue()


def write_to_dir(result: ExportResult, out_dir: Path) -> list[Path]:
    """Разложить артефакты по папке на диске. Возвращает список путей."""
    written: list[Path] = []
    for a in result.artifacts:
        p = out_dir / a.name
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(a.data)
        written.append(p)
    return written


# --- contact-sheet с подписями --------------------------------------------

def build_contact_sheet(rendered: list[RenderedSize], meta: dict | None = None) -> Image.Image:
    """Лист со всеми размерами на шахматке + подписи для контроля качества.

    Подписи внизу: preset, bg mode, кол-во объектов. Под каждой иконкой:
    размер, alpha yes/no, bbox.
    """
    meta = meta or {}
    cell = 150
    label_h = 46
    pad = 14
    cols = min(len(rendered), 5) or 1
    rows = (len(rendered) + cols - 1) // cols
    header_h = 30
    W = cols * (cell + pad) + pad
    H = header_h + rows * (cell + label_h + pad) + pad + 28

    sheet = Image.new("RGBA", (W, H), (32, 34, 40, 255))
    draw = ImageDraw.Draw(sheet)
    font = _font(13)
    small = _font(11)
    title = _font(15)

    # заголовок
    head = "AssetForge contact-sheet"
    sub = " · ".join(
        f"{k}={meta[k]}" for k in ("preset", "bg_mode", "objects", "source") if k in meta
    )
    draw.text((pad, 8), head, font=title, fill=(235, 235, 245, 255))
    if sub:
        tw = draw.textlength(head, font=title)
        draw.text((pad + tw + 16, 11), sub, font=small, fill=(150, 200, 255, 255))

    for i, r in enumerate(rendered):
        c = i % cols
        rrow = i // cols
        x = pad + c * (cell + pad)
        y = header_h + pad + rrow * (cell + label_h + pad)
        # шахматный фон ячейки
        _draw_checker(sheet, x, y, cell, cell)
        # вписать иконку по центру ячейки (не растягиваем выше натурального размера)
        disp = min(r.size, cell - 8)
        thumb = r.image if r.size == disp else r.image.resize((disp, disp), Image.LANCZOS)
        sheet.alpha_composite(thumb, (x + (cell - disp) // 2, y + (cell - disp) // 2))
        # рамка
        draw.rectangle([x, y, x + cell - 1, y + cell - 1], outline=(70, 74, 84, 255))
        # подписи
        ly = y + cell + 3
        draw.text((x + 2, ly), f"{r.size}×{r.size}", font=font, fill=(230, 230, 240, 255))
        a_txt = "alpha:yes" if r.has_alpha else "alpha:no"
        a_col = (120, 220, 140, 255) if r.has_alpha else (230, 160, 120, 255)
        draw.text((x + 2, ly + 16), a_txt, font=small, fill=a_col)
        bb = r.bbox
        bb_txt = f"bbox:{bb[2]-bb[0]}×{bb[3]-bb[1]}" if bb else "bbox:—"
        draw.text((x + 70, ly + 16), bb_txt, font=small, fill=(160, 165, 180, 255))

    foot = "alpha:yes = есть прозрачность · клетка = шахматка для проверки краёв"
    draw.text((pad, H - 22), foot, font=small, fill=(130, 135, 150, 255))
    return sheet


# --- низкоуровневые помощники ----------------------------------------------

def _save_bytes(im: Image.Image, fmt: str, **kw) -> bytes:
    buf = io.BytesIO()
    im.save(buf, format=fmt, **kw)
    return buf.getvalue()


def _ico_bytes(base: Image.Image, sizes: list[int], rcfg: ResizeConfig) -> bytes:
    """Мультиразмерный .ico из готовых кадров.

    Каждый кадр строится ``resize_to(base, s, rcfg, square=True)`` — тот же
    одношаговый Lanczos + unsharp на мелких, что и у PNG. Готовые кадры отдаются
    Pillow через ``append_images``, чтобы кодер не пересчитывал их своим
    даунскейлом без резкости (раньше кадры мылились из-за двойного ресайза).
    """
    sizes = sorted({s for s in sizes if s <= 256}) or [256]
    frames = [resize_to(base, s, rcfg, square=True) for s in sizes]
    buf = io.BytesIO()
    # самый крупный кадр — основной, остальные передаём как append_images;
    # для каждого размера Pillow найдёт точное совпадение и возьмёт готовый кадр.
    frames[-1].save(buf, format="ICO",
                    sizes=[(s, s) for s in sizes],
                    append_images=frames[:-1])
    return buf.getvalue()


def _icns_bytes(base: Image.Image, sizes: list[int], rcfg: ResizeConfig) -> bytes:
    """Мультиразмерный .icns из готовых кадров (как PNG, через resize_to).

    Кодер .icns в Pillow пишет фиксированный набор {32,64,128,256,512,1024};
    передаём ему уже отресайзенные кадры через ``append_images`` (он матчит их по
    ширине), чтобы они были резкими, а не пересчитанными из одного квадрата.
    """
    sizes = sorted({s for s in sizes if 16 <= s <= 1024}) or [512]
    frames = [resize_to(base, s, rcfg, square=True) for s in sizes]
    buf = io.BytesIO()
    # append_images у .icns матчится по ширине и НЕ включает основной im,
    # поэтому передаём все кадры (включая крупнейший) в append_images.
    frames[-1].save(buf, format="ICNS",
                    sizes=[(s, s) for s in sizes],
                    append_images=frames)
    return buf.getvalue()


def _svg_wrap_bytes(im: Image.Image) -> bytes:
    import base64
    w, h = im.size
    b64 = base64.b64encode(io_utils.to_png_bytes(im)).decode("ascii")
    svg = (
        f'<svg xmlns="http://www.w3.org/2000/svg" '
        f'xmlns:xlink="http://www.w3.org/1999/xlink" '
        f'width="{w}" height="{h}" viewBox="0 0 {w} {h}">\n'
        f'  <image width="{w}" height="{h}" xlink:href="data:image/png;base64,{b64}"/>\n'
        f"</svg>\n"
    )
    return svg.encode("utf-8")


def _manifest_text(result: ExportResult) -> str:
    lines = ["AssetForge export manifest", "=" * 28]
    for k, v in result.meta.items():
        lines.append(f"{k}: {v}")
    lines.append("")
    lines.append("files:")
    for a in result.artifacts:
        lines.append(f"  {a.name} ({len(a.data)} bytes)")
    return "\n".join(lines) + "\n"


def _has_alpha(im: Image.Image) -> bool:
    if im.mode not in ("RGBA", "LA"):
        return False
    a = im.getchannel("A")
    lo, hi = a.getextrema()
    return lo < 255


def _draw_checker(sheet: Image.Image, x: int, y: int, w: int, h: int, s: int = 10) -> None:
    light, dark = (90, 92, 100, 255), (66, 68, 76, 255)
    tile = Image.new("RGBA", (w, h), light)
    d = ImageDraw.Draw(tile)
    for ty in range(0, h, s):
        for tx in range(0, w, s):
            if (tx // s + ty // s) % 2:
                d.rectangle([tx, ty, tx + s - 1, ty + s - 1], fill=dark)
    sheet.alpha_composite(tile, (x, y))


_FONT_CACHE: dict[int, ImageFont.FreeTypeFont] = {}


def _font(size: int):
    if size in _FONT_CACHE:
        return _FONT_CACHE[size]
    for name in ("segoeui.ttf", "arial.ttf", "DejaVuSans.ttf"):
        try:
            f = ImageFont.truetype(name, size)
            _FONT_CACHE[size] = f
            return f
        except OSError:
            continue
    f = ImageFont.load_default()
    _FONT_CACHE[size] = f
    return f
