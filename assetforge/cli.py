"""Пакетная нарезка ассетов из командной строки.

Примеры:
  python -m assetforge.cli logo.png -o out --preset icon-set
  python -m assetforge.cli assets/ -o out --preset all --split auto --bg auto
  python -m assetforge.cli a.png b.png -o out --sizes 16,32,64,128 --formats png,ico
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from .core import pipeline
from .core.config import PipelineConfig, preset, preset_names
from .core.export import package_zip, write_to_dir

IMAGE_EXT = {".png", ".jpg", ".jpeg", ".webp", ".bmp", ".gif", ".tif", ".tiff"}


def _gather_inputs(paths: list[str]) -> list[Path]:
    files: list[Path] = []
    for p in paths:
        pp = Path(p)
        if pp.is_dir():
            files += [f for f in sorted(pp.rglob("*")) if f.suffix.lower() in IMAGE_EXT]
        elif pp.is_file():
            files.append(pp)
        else:
            print(f"! пропуск (не найдено): {p}", file=sys.stderr)
    return files


def _build_config(args) -> PipelineConfig:
    cfg = preset(args.preset) if args.preset else PipelineConfig()
    if args.sizes:
        try:
            sizes = [int(s.strip()) for s in args.sizes.split(",") if s.strip()]
        except ValueError:
            raise SystemExit(f"Ошибка: --sizes должны быть числами через запятую, получено: {args.sizes!r}")
        if not sizes:
            raise SystemExit("Ошибка: --sizes не содержит ни одного размера.")
        cfg.export.sizes = sizes
    if args.formats:
        cfg.export.formats = [f.strip().lower() for f in args.formats.split(",") if f.strip()]
    if args.bg:
        cfg.background.mode = args.bg
    if args.split:
        cfg.crop.split = args.split
    if args.padding is not None:
        cfg.crop.padding_pct = args.padding
    if args.fit:
        cfg.crop.fit = args.fit
        cfg.crop.square = args.fit != "width"
    if args.no_contact_sheet:
        cfg.export.make_contact_sheet = False
    return cfg


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        prog="assetforge", description="Нарезка и подготовка ассетов (иконки/лого).")
    ap.add_argument("inputs", nargs="+", help="файлы и/или папки с картинками")
    ap.add_argument("-o", "--out", default="out", help="папка вывода (по умолчанию: out)")
    ap.add_argument("--preset", help=f"пресет: {', '.join(preset_names())}")
    ap.add_argument("--sizes", help="свои размеры через запятую, напр. 16,32,64,128,256")
    ap.add_argument("--formats", help="форматы через запятую: png,ico,icns,webp,svg")
    ap.add_argument("--bg", help="режим фона: auto|alpha|white|solid|chroma|ai|none")
    ap.add_argument("--split", help="объекты: single|split|auto")
    ap.add_argument("--padding", type=float, help="паддинг вокруг контента, %%")
    ap.add_argument("--fit", help="вписывание: contain|width|none")
    ap.add_argument("--no-contact-sheet", action="store_true", help="не делать contact-sheet")
    ap.add_argument("--zip", action="store_true", help="дополнительно собрать bundle.zip на каждый объект")
    args = ap.parse_args(argv)

    cfg = _build_config(args)
    files = _gather_inputs(args.inputs)
    if not files:
        print("Нет входных изображений.", file=sys.stderr)
        return 2

    out_root = Path(args.out)
    total_files = 0
    print(f"Пресет: {args.preset or 'custom'} | размеры: {cfg.export.sizes} | "
          f"форматы: {cfg.export.formats} | bg: {cfg.background.mode} | split: {cfg.crop.split}")

    for f in files:
        try:
            results = pipeline.run(str(f), cfg, extra_meta={"preset": args.preset or "custom",
                                                            "source": f.name})
        except Exception as exc:  # noqa: BLE001 — отчёт по каждому файлу, не падаем целиком
            print(f"  ✗ {f.name}: {exc}", file=sys.stderr)
            continue

        for i, res in enumerate(results):
            suffix = f"_{i+1}" if len(results) > 1 else ""
            dest = out_root / (f.stem + suffix)
            written = write_to_dir(res, dest)
            total_files += len(written)
            if args.zip:
                (out_root / (f.stem + suffix + ".zip")).write_bytes(package_zip(res))
            print(f"  ✓ {f.name}{suffix}: {len(written)} файлов → {dest}")

    print(f"Готово. Всего файлов: {total_files} в {out_root}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
