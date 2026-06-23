"""Брендированный HTML для окон установки / обновления (pywebview).

Самодостаточный: вся стилистика «раскалённой кузницы» инлайном, без внешних
ресурсов (окно живёт в about:blank). Палитра и логотип — как в web/style.css и favicon.
"""
from __future__ import annotations

_LOGO_SVG = (
    '<svg class="mark" viewBox="0 0 32 32" width="64" height="64">'
    '<defs><linearGradient id="g" x1="0" y1="0" x2="1" y2="1">'
    '<stop offset="0" stop-color="#fff1df"/><stop offset=".45" stop-color="#f0cd8f"/>'
    '<stop offset="1" stop-color="#ff3f0d"/></linearGradient></defs>'
    '<path d="M16 1 L19 11 L29 14 L19 17 L16 31 L13 17 L3 14 L13 11 Z" fill="url(#g)"/>'
    '</svg>'
)

_BASE_CSS = """
*{box-sizing:border-box;margin:0;padding:0}
html,body{height:100%}
body{
  font-family:'Segoe UI',system-ui,Arial,sans-serif;color:#c4b4a6;overflow:hidden;
  background:
    radial-gradient(120% 90% at 50% -10%, rgba(255,90,20,.16), transparent 55%),
    radial-gradient(100% 80% at 100% 115%, rgba(214,163,92,.08), transparent 60%),
    linear-gradient(180deg,#0b0907,#080605 65%,#060403);
}
.wrap{height:100vh;display:flex;flex-direction:column;align-items:center;justify-content:center;
  text-align:center;padding:34px 40px;gap:4px;position:relative}
.mark{filter:drop-shadow(0 0 16px rgba(255,106,26,.7));animation:glow 2.6s ease-in-out infinite}
@keyframes glow{0%,100%{filter:drop-shadow(0 0 10px rgba(255,106,26,.5))}
  50%{filter:drop-shadow(0 0 22px rgba(255,106,26,.95))}}
.title{font-size:30px;font-weight:700;letter-spacing:.10em;text-transform:uppercase;color:#f3e8dc;margin-top:14px}
.title i{color:#ff6a1a;font-style:normal}
.tag{font-size:12.5px;color:#8c7d70;letter-spacing:.04em;margin-top:2px}
.stage{font-size:13.5px;color:#c4b4a6;margin-top:26px;min-height:20px}
.bar{width:340px;max-width:78vw;height:8px;border-radius:6px;background:#211a15;
  border:1px solid #2a211c;margin-top:14px;overflow:hidden}
.bar>i{display:block;height:100%;width:0%;border-radius:6px;transition:width .25s ease;
  background:linear-gradient(90deg,#d6a35c,#ff6a1a 60%,#ff3f0d)}
.bar.indet>i{width:35%;animation:slide 1.2s ease-in-out infinite}
@keyframes slide{0%{margin-left:-35%}100%{margin-left:100%}}
.btn{margin-top:28px;font:600 14px 'Segoe UI',sans-serif;color:#1a1109;cursor:pointer;
  padding:12px 34px;border:none;border-radius:11px;letter-spacing:.02em;
  background:linear-gradient(180deg,#ffb066,#ff6a1a);
  box-shadow:0 10px 30px -10px rgba(255,106,26,.7),inset 0 1px 0 rgba(255,255,255,.4)}
.btn:hover{filter:brightness(1.07)}
.btn:active{transform:translateY(1px)}
.hint{font-size:11.5px;color:#5f534a;margin-top:18px;max-width:380px;line-height:1.5}
.notes{font-size:12px;color:#a89a8c;margin-top:8px;max-width:380px;line-height:1.5;white-space:pre-line}
.hidden{display:none!important}
"""

_SCRIPT = """
function setStage(t){var e=document.getElementById('stage');if(e)e.textContent=t;}
function setPct(p){
  var bar=document.getElementById('bar');var fill=document.getElementById('fill');
  if(p<0){bar.classList.add('indet');fill.style.width='35%';}
  else{bar.classList.remove('indet');fill.style.width=Math.max(0,Math.min(100,p))+'%';}
}
function showButton(show){
  var b=document.getElementById('go');if(b)b.classList.toggle('hidden',!show);
  var bar=document.getElementById('bar');if(bar)bar.classList.toggle('hidden',show);
}
function setNotes(t){var e=document.getElementById('notes');if(e){e.textContent=t||'';}}
function onGo(){showButton(false);setStage('Устанавливаю…');window.pywebview.api.begin();}
"""


def _page(stage: str, *, button: bool, hint: str = "", indeterminate: bool = True) -> str:
    bar_cls = "bar indet" if indeterminate else "bar"
    btn_cls = "btn" if button else "btn hidden"
    bar_hidden = " hidden" if button else ""
    return f"""<!DOCTYPE html><html lang="ru"><head><meta charset="utf-8">
<style>{_BASE_CSS}</style></head><body><div class="wrap">
{_LOGO_SVG}
<div class="title">ASSET<i>FORGE</i></div>
<div class="tag">нарезка · фон · иконки</div>
<div id="notes" class="notes"></div>
<div id="stage" class="stage">{stage}</div>
<div id="bar" class="{bar_cls}{bar_hidden}"><i id="fill"></i></div>
<button id="go" class="{btn_cls}" onclick="onGo()">Установить</button>
<div class="hint">{hint}</div>
</div><script>{_SCRIPT}</script></body></html>"""


def install_html() -> str:
    return _page(
        "Готов к установке",
        button=True,
        hint="Приложение установится в ваш профиль пользователя — без прав администратора. "
             "Будут созданы ярлыки в меню Пуск и на рабочем столе.",
        indeterminate=False,
    )


def splash_html() -> str:
    return _page("Проверка обновлений…", button=False,
                 hint="", indeterminate=True)
