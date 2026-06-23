"""Тесты движка по метрикам. Запуск:  python -m tests.test_engine  (или pytest)."""
from __future__ import annotations

from assetforge.core.background import remove_background, detect_background
from assetforge.core.config import (BackgroundConfig, CropConfig, ExportConfig,
                                     ICON_SIZES, PipelineConfig, ResizeConfig)
from assetforge.core.crop import apply_crop
from assetforge.core.detect import content_bbox, split_objects
from assetforge.core.export import build_export
from assetforge.core import pipeline
import numpy as np

from . import fixtures as fx
from . import metrics as M


# --- удаление фона ---------------------------------------------------------

def test_transparent_passthrough():
    im = fx.transparent_png()
    res = remove_background(im, BackgroundConfig(mode="auto"))
    assert res.detected_mode == "alpha"
    # объект сохранён, рамка прозрачна
    assert 0.10 < M.alpha_coverage(res.image) < 0.6
    assert M.border_opaque_fraction(res.image) < 0.01


def test_white_bg_removed():
    im = fx.white_bg()
    res = remove_background(im, BackgroundConfig(mode="auto"))
    assert res.detected_mode in ("white", "solid")
    assert M.border_opaque_fraction(res.image) < 0.02   # фон ушёл
    assert M.alpha_coverage(res.image) > 0.10           # объект остался
    # цвет объекта — синеватый (B заметно больше R)
    r, g, b = M.mean_color_in_mask(res.image)
    assert b > r


def test_green_chroma_removed_and_despilled():
    im = fx.green_chroma()
    res = remove_background(im, BackgroundConfig(mode="auto"))
    assert res.detected_mode == "chroma"
    assert M.border_opaque_fraction(res.image) < 0.02   # фон ушёл
    assert M.alpha_coverage(res.image) > 0.10           # объект остался
    # despill снижает зелёную кайму в краевой зоне (alpha 120..255)
    on = remove_background(im, BackgroundConfig(mode="chroma", despill=True, despill_strength=1.0))
    off = remove_background(im, BackgroundConfig(mode="chroma", despill=False))
    assert M.green_excess(on.image, thr=120) <= M.green_excess(off.image, thr=120) + 0.5


def test_blue_chroma_removed():
    im = fx.blue_chroma()
    res = remove_background(im, BackgroundConfig(mode="auto"))
    assert res.detected_mode == "chroma"
    assert M.border_opaque_fraction(res.image) < 0.02
    assert M.alpha_coverage(res.image) > 0.10


# --- детект/обрезка --------------------------------------------------------

def test_noisy_alpha_bbox_excludes_noise():
    im = fx.noisy_alpha()
    # с порогом мусор (alpha<=12) не должен попасть в bbox -> рамка ~ объекта (60..200)
    bb = content_bbox(im, threshold=16)
    assert bb is not None
    x0, y0, x1, y1 = bb
    assert x0 > 40 and y0 > 40 and x1 < 216 and y1 < 216
    # а с нулевым порогом bbox был бы почти во весь кадр
    bb0 = content_bbox(im, threshold=0)
    assert (bb0[2] - bb0[0]) > (x1 - x0)


def test_multi_object_split():
    im = fx.multi_object()
    boxes = split_objects(im, threshold=16, mode="auto")
    assert len(boxes) == 2
    # объекты разнесены: один сверху-слева, другой снизу-справа
    boxes.sort(key=lambda b: b[1])
    assert boxes[0][1] < 100 and boxes[1][1] > 140


def test_tiny_logo_detected():
    im = fx.tiny_logo()
    boxes = split_objects(im, threshold=16, mode="auto")
    assert len(boxes) == 1
    x0, y0, x1, y1 = boxes[0]
    assert (x1 - x0) < 40 and (y1 - y0) < 40   # объект действительно маленький


# --- экспорт ---------------------------------------------------------------

def test_export_sizes_and_formats():
    im = fx.transparent_png()
    res = remove_background(im, BackgroundConfig(mode="auto"))
    bb = split_objects(res.image, mode="auto")[0]
    cropped = apply_crop(res.image, bb, CropConfig(fit="contain", square=True, padding_pct=6))
    ecfg = ExportConfig(sizes=[16, 32, 64, 128], formats=["png", "ico", "icns", "webp"])
    out = build_export(cropped, ecfg, ResizeConfig(), square=True,
                       meta={"preset": "test", "bg_mode": "alpha"})
    # PNG на каждый размер + контактный лист
    pngs = out.by_kind("png")
    assert len(pngs) == 4
    for r in out.rendered:
        assert r.image.size == (r.size, r.size)
    assert len(out.by_kind("ico")) == 1
    assert len(out.by_kind("icns")) == 1
    assert len(out.by_kind("webp")) == 4
    assert len(out.by_kind("sheet")) == 1
    # ico реально открывается
    import io
    from PIL import Image
    Image.open(io.BytesIO(out.by_kind("ico")[0].data)).verify()


def test_full_pipeline_multi():
    im = fx.multi_object()
    cfg = PipelineConfig()
    cfg.export.sizes = [32, 64, 128]
    cfg.export.formats = ["png"]
    results = pipeline.run(im, cfg)
    assert len(results) == 2                  # два объекта -> два набора
    for res in results:
        assert len(res.by_kind("png")) == 3


def test_soft_edges_present():
    # после удаления белого фона край должен быть мягким (антиалиас), не «лесенкой»
    im = fx.white_bg()
    res = remove_background(im, BackgroundConfig(mode="auto", softness=24))
    assert M.has_soft_edge(res.image)


# --- регрессии на краевые случаи (из ревизии) ------------------------------

def test_key_color_short_list_no_crash():
    # key_color из UI с <3 компонентами не должен ронять broadcast
    im = fx.white_bg()
    res = remove_background(im, BackgroundConfig(mode="solid", key_color=[255, 128]))
    assert res.image.size == im.size


def test_empty_sizes_export_falls_back():
    im = fx.transparent_png()
    res = remove_background(im, BackgroundConfig(mode="auto"))
    bb = split_objects(res.image, mode="auto")[0]
    cropped = apply_crop(res.image, bb, CropConfig(fit="contain", square=True))
    # пустой sizes + форматы, которые раньше падали на max([]) → должен быть фолбэк
    out = build_export(cropped, ExportConfig(sizes=[], formats=["png", "ico", "icns", "svg"]),
                       ResizeConfig(), square=True)
    assert len(out.by_kind("png")) == len(ICON_SIZES)
    assert len(out.by_kind("ico")) == 1
    assert len(out.by_kind("svg")) == 1


def test_run_blank_returns_empty():
    from PIL import Image
    blank = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
    assert pipeline.run(blank, PipelineConfig()) == []


def test_despill_strength_high_valid_image():
    im = fx.green_chroma()
    res = remove_background(im, BackgroundConfig(mode="chroma", despill=True, despill_strength=1.5))
    arr = np.asarray(res.image)
    assert arr.dtype == np.uint8 and arr.shape[2] == 4   # без артефактов переполнения


def test_icns_small_sizes_valid():
    # favicon-подобный мелкий набор: .icns должен корректно собраться и открываться.
    im = fx.transparent_png()
    res = remove_background(im, BackgroundConfig(mode="auto"))
    bb = split_objects(res.image, mode="auto")[0]
    cropped = apply_crop(res.image, bb, CropConfig(fit="contain", square=True))
    out = build_export(cropped, ExportConfig(sizes=[16, 32, 48], formats=["icns"]),
                       ResizeConfig(), square=True)
    import io
    from PIL import Image
    Image.open(io.BytesIO(out.by_kind("icns")[0].data)).verify()


# --- регрессии «умного» фона (из стресс-теста) -----------------------------

def _solid_with_circle(bg, obj, size=200):
    from PIL import Image, ImageDraw
    im = Image.new("RGBA", (size, size), bg + (255,))
    ImageDraw.Draw(im).ellipse([size*0.3, size*0.3, size*0.7, size*0.7], fill=obj + (255,))
    return im


def _alpha(im):
    return np.asarray(im.convert("RGBA"))[:, :, 3]


def test_green_object_on_green_screen_survives():
    # зелёный ОБЪЕКТ (другой оттенок) на зелёном экране не должен выедаться
    im = _solid_with_circle((20, 200, 30), (120, 200, 80))
    res = remove_background(im, BackgroundConfig(mode="auto"))
    a = _alpha(res.image)
    h, w = a.shape
    assert a[h//2-6:h//2+6, w//2-6:w//2+6].mean() > 200   # центр объекта цел
    assert a[:8, :8].mean() < 20                           # фон ушёл


def test_colored_checker_detected_and_removed():
    from PIL import Image, ImageDraw
    W = H = 200
    im = Image.new("RGBA", (W, H))
    px = im.load()
    for y in range(H):
        for x in range(W):
            px[x, y] = (40, 80, 200, 255) if (x//16 + y//16) % 2 == 0 else (120, 160, 240, 255)
    ImageDraw.Draw(im).ellipse([60, 40, 140, 120], fill=(40, 200, 120, 255))
    res = remove_background(im, BackgroundConfig(mode="auto"))
    assert res.detected_mode == "checker"
    a = _alpha(res.image)
    assert a[:8, :8].mean() < 20                            # фон-шахматка ушла
    assert a[80-5:80+5, 100-5:100+5].mean() > 200           # объект цел


def test_gradient_not_detected_as_checker():
    from PIL import Image
    im = Image.new("RGBA", (200, 200))
    px = im.load()
    for y in range(200):
        c = int(230 - (y / 199) * 60)
        for x in range(200):
            px[x, y] = (c, c, c, 255)
    mode, _ = detect_background(np.asarray(im).astype(np.float32))
    assert mode != "checker"                                # плавный градиент ≠ шахматка


def test_near_white_checker_removed_object_kept():
    from PIL import Image, ImageDraw
    W = H = 200
    im = Image.new("RGBA", (W, H))
    px = im.load()
    for y in range(H):
        for x in range(W):
            px[x, y] = (248, 248, 248, 255) if (x//12 + y//12) % 2 == 0 else (240, 240, 240, 255)
    ImageDraw.Draw(im).ellipse([60, 60, 140, 140], fill=(60, 30, 120, 255))
    res = remove_background(im, BackgroundConfig(mode="auto"))
    a = _alpha(res.image)
    assert a[:8, :8].mean() < 30                            # светлая шахматка ушла
    assert a[H//2-5:H//2+5, W//2-5:W//2+5].mean() > 200     # тёмный объект цел


def test_no_white_fringe_on_banner():
    # реальный кейс пользователя: ассеты на сплющенной near-white шахматке.
    # после удаления фона у края НЕ должно оставаться светлой каймы.
    import os
    if not os.path.exists("testkrivo.png"):
        return
    from assetforge.core.io_utils import load_rgba
    im = load_rgba(open("testkrivo.png", "rb").read())
    fg = remove_background(im, BackgroundConfig(mode="auto")).image
    arr = np.asarray(fg)
    a = arr[:, :, 3]
    rgb = arr[:, :, :3].astype(int)
    trans = a < 8
    # полоса ~3px вокруг прозрачного
    band = trans.copy()
    for _ in range(3):
        nb = band.copy()
        nb[1:, :] |= band[:-1, :]; nb[:-1, :] |= band[1:, :]
        nb[:, 1:] |= band[:, :-1]; nb[:, :-1] |= band[:, 1:]
        band = nb
    band = band & ~trans & (a > 40)
    if band.sum() == 0:
        return
    bright = rgb.mean(axis=2) > 195               # светлый
    lowsat = (rgb.max(axis=2) - rgb.min(axis=2)) < 35   # near-white/серый (не фонарь)
    fringe = band & bright & lowsat
    frac = float(fringe.sum()) / float(band.sum())
    assert frac < 0.04, f"светлая кайма на границе: {frac:.1%} (ожидаем <4%)"


def test_rect_targets_and_jpg_retina():
    from assetforge.core.resize import render_target
    from assetforge.core.config import ExportConfig
    import io
    from PIL import Image
    im = fx.transparent_png()
    res = remove_background(im, BackgroundConfig(mode="auto"))
    bb = split_objects(res.image, mode="auto")[0]
    cropped = apply_crop(res.image, bb, CropConfig(fit="contain", square=True))
    # render_target: точные W×H в любом fit
    for fit in ("contain", "cover", "stretch"):
        assert render_target(cropped, 300, 100, fit=fit).size == (300, 100)
    # сплошной/auto фон реально заливается (нет прозрачности у contain с bg)
    solid = render_target(cropped, 200, 80, fit="contain", bg=[10, 20, 30])
    assert solid.getchannel("A").getextrema()[0] == 255
    # build_export с прямоугольными таргетами + retina + jpg
    ecfg = ExportConfig(sizes=[64], formats=["png"], make_contact_sheet=False, retina=True,
                        targets=[{"name": "og", "w": 1200, "h": 630, "fit": "cover", "bg": "auto"},
                                 {"name": "banner", "w": 600, "h": 200, "fit": "contain", "format": "jpg"}])
    out = build_export(cropped, ecfg, ResizeConfig(), square=True)
    names = {a.name for a in out.artifacts}
    assert {"targets/og.png", "targets/og@2x.png", "targets/banner.jpg", "targets/banner@2x.jpg"} <= names
    og2 = next(a for a in out.artifacts if a.name == "targets/og@2x.png")
    assert Image.open(io.BytesIO(og2.data)).size == (2400, 1260)
    # jpg реально открывается
    bj = next(a for a in out.artifacts if a.name == "targets/banner.jpg")
    Image.open(io.BytesIO(bj.data)).verify()


def test_classify_and_analyze_meta():
    from assetforge.core.classify import classify_asset, KIND_TO_PRESET
    from PIL import Image, ImageDraw
    # квадратная иконка
    icon = Image.new("RGBA", (200, 200), (0, 0, 0, 0))
    ImageDraw.Draw(icon).ellipse([30, 30, 170, 170], fill=(60, 140, 230, 255))
    c = classify_asset(icon)
    assert c["kind"] in KIND_TO_PRESET and c["suggested_preset"] in (
        "icon-set", "web-logo", "favicon", "launcher", "all", "android", "ios", "discord", "steam", "windows-store")
    assert 0.0 <= c["confidence"] <= 1.0 and isinstance(c["reasons"], list)
    # широкий вордмарк → wordmark/web-logo
    wm = Image.new("RGBA", (600, 90), (0, 0, 0, 0))
    d = ImageDraw.Draw(wm)
    for i in range(5):
        d.rectangle([20 + i * 115, 25, 20 + i * 115 + 80, 65], fill=(240, 240, 240, 255))
    assert classify_asset(wm)["kind"] == "wordmark"
    # analyze прокидывает классификацию в meta
    a = pipeline.analyze(fx.white_bg(), PipelineConfig())
    assert "asset_kind" in a.meta and "suggested_preset" in a.meta


def test_effects_module():
    from assetforge.core import effects
    from PIL import Image, ImageDraw
    im = Image.new("RGBA", (120, 120), (0, 0, 0, 0))
    ImageDraw.Draw(im).ellipse([20, 20, 100, 100], fill=(80, 160, 255, 255))
    o = effects.add_outline(im, width_pct=5, color=(255, 255, 255, 255))
    assert o.mode == "RGBA" and o.size[0] >= im.size[0]      # контур расширил холст
    s = effects.drop_shadow(im, dy=8, blur=6)
    assert s.mode == "RGBA" and s.size[1] >= im.size[1]
    r = effects.rounded_corners(im, radius_pct=25)
    assert r.size == im.size
    # вырожденные не падают
    effects.add_outline(Image.new("RGBA", (1, 1), (0, 0, 0, 0)))
    # эффекты через пресет sticker в build_export
    from assetforge.core.config import preset
    cfg = preset("sticker")
    out = build_export(im, cfg.export, cfg.resize, square=True)
    assert len(out.by_kind("png")) == 3 and len(out.by_kind("webp")) == 3


def test_saliency_offcenter():
    from assetforge.core.saliency import saliency_center
    from PIL import Image, ImageDraw
    im = Image.new("RGBA", (400, 400), (0, 0, 0, 0))
    ImageDraw.Draw(im).ellipse([60, 60, 180, 180], fill=(255, 100, 40, 255))  # верх-лево
    cx, cy = saliency_center(im)
    assert cx < 0.5 and cy < 0.5      # центр значимости смещён к объекту, не (0.5,0.5)


def test_social_preset_targets():
    from assetforge.core.config import preset
    cfg = preset("social-all")
    assert len(cfg.export.targets) >= 5
    im = fx.transparent_png()
    res = remove_background(im, BackgroundConfig(mode="auto"))
    bb = split_objects(res.image, mode="auto")[0]
    cropped = apply_crop(res.image, bb, CropConfig(fit="contain", square=False))
    out = build_export(cropped, cfg.export, cfg.resize, square=False)
    tg = [a.name for a in out.artifacts if a.name.startswith("targets/")]
    assert any("og-1200x630" in n for n in tg) and len(tg) >= 5
    # taргеты — единственный выход (square-набор не плодится)
    assert len(out.by_kind("png")) == 0 or all("targets/" in a.name for a in out.by_kind("png"))


# --- автономный раннер -----------------------------------------------------

def _run_all():
    import traceback
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    passed = failed = 0
    for t in tests:
        try:
            t(); passed += 1; print(f"  PASS  {t.__name__}")
        except Exception:  # noqa: BLE001
            failed += 1
            print(f"  FAIL  {t.__name__}")
            traceback.print_exc()
    print(f"\n{passed} passed, {failed} failed из {len(tests)}")
    return failed == 0


if __name__ == "__main__":
    import sys
    sys.exit(0 if _run_all() else 1)
