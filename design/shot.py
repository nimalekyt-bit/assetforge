"""Скриншоты страниц/файлов через Playwright (dev-инструмент).

Использование:
  python design/shot.py <url-или-путь.html> <output.png> [width] [height] [full|view] [reveal]

reveal — прокрутить страницу и принудительно показать scroll-reveal элементы
(IntersectionObserver), чтобы full-page скрин не был пустым ниже hero.
"""
import sys
from pathlib import Path

from playwright.sync_api import sync_playwright


REVEAL_JS = """
() => new Promise(resolve => {
  const step = Math.max(200, Math.floor(window.innerHeight * 0.8));
  let y = 0;
  const max = document.body.scrollHeight;
  const tick = () => {
    window.scrollTo(0, y);
    y += step;
    if (y < max + step) { setTimeout(tick, 60); }
    else {
      window.scrollTo(0, 0);
      setTimeout(resolve, 250);
    }
  };
  tick();
});
"""

# Фолбэк: всё, что осталось скрытым reveal-анимацией, делаем видимым.
FORCE_VISIBLE_CSS = """
*{animation-duration:0s !important;animation-delay:0s !important;
  transition:none !important}
[class*="reveal"],[class*="fade"],[data-reveal],[class*="appear"],
[class*="inview"],[class*="hidden"],.hide,.is-hidden{
  opacity:1 !important;transform:none !important;visibility:visible !important;
  filter:none !important;clip-path:none !important}
"""


def shot(target, out, width=1440, height=900, full=True, reveal=False):
    if not target.startswith("http"):
        target = Path(target).resolve().as_uri()
    with sync_playwright() as p:
        b = p.chromium.launch()
        page = b.new_page(viewport={"width": width, "height": height},
                          device_scale_factor=2)
        page.goto(target, wait_until="networkidle", timeout=30000)
        page.wait_for_timeout(1000)
        if reveal:
            page.evaluate(REVEAL_JS)
            page.add_style_tag(content=FORCE_VISIBLE_CSS)
            page.wait_for_timeout(600)
        else:
            page.wait_for_timeout(1000)
        page.screenshot(path=out, full_page=full)
        b.close()
    print("saved", out)


if __name__ == "__main__":
    a = sys.argv
    mode = a[5].lower() if len(a) > 5 else "full"
    shot(a[1], a[2],
         int(a[3]) if len(a) > 3 else 1440,
         int(a[4]) if len(a) > 4 else 900,
         full=(mode in ("full", "reveal")),
         reveal=("reveal" in [x.lower() for x in a[5:]]))
