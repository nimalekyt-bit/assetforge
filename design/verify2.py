"""Проверка после фиксов: safe_next, og.png, скриншоты страниц + smoke инструмента."""
import glob
from pathlib import Path
from playwright.sync_api import sync_playwright

# --- 1. safe_next (open-redirect) — прямая проверка функции ---
from assetforge.saas.security import safe_next
checks = {
    "https://evil.com": safe_next("https://evil.com"),
    "//evil.com": safe_next("//evil.com"),
    "/\\evil": safe_next("/\\evil"),
    "/account": safe_next("/account"),
    "/app?x=1": safe_next("/app?x=1"),
}
print("safe_next:", checks)
assert checks["https://evil.com"] == "/app" and checks["//evil.com"] == "/app" and checks["/account"] == "/account"
print("safe_next OK")

B = "http://127.0.0.1:8000"
OUT = Path("design/site"); OUT.mkdir(parents=True, exist_ok=True)
ADMIN, PW = "master@forge.dev", "forge12345"

def reveal(pg):
    pg.evaluate("""()=>new Promise(r=>{let y=0,m=document.body.scrollHeight,s=Math.max(250,innerHeight*0.7);(function t(){scrollTo(0,y);y+=s;if(y<m+s)setTimeout(t,60);else{scrollTo(0,0);setTimeout(r,200)}})();})""")
    pg.evaluate("()=>document.querySelectorAll('.reveal').forEach(e=>e.classList.add('in'))")

with sync_playwright() as p:
    b = p.chromium.launch()

    # --- 2. og.png баннер 1200x630 ---
    ogp = b.new_page(viewport={"width":1200,"height":630}, device_scale_factor=1)
    ogp.goto(B + "/", wait_until="networkidle"); ogp.wait_for_timeout(800)
    ogp.evaluate("""()=>{document.querySelector('header').style.display='none';
      const h=document.querySelector('.hero');if(h){h.style.padding='40px 0'}}""")
    ogp.screenshot(path="assetforge/web/og.png")
    print("og.png saved")
    ogp.close()

    ctx = b.new_context(viewport={"width":1440,"height":900}, device_scale_factor=2)
    pg = ctx.new_page()
    errs=[]; pg.on("pageerror", lambda e: errs.append(str(e)))

    # login (register if needed)
    pg.goto(B+"/register", wait_until="networkidle")
    pg.fill('input[name=email]', ADMIN); pg.fill('input[name=password]', PW); pg.fill('input[name=name]',"Мастер")
    pg.click('button[type=submit]'); pg.wait_for_timeout(1200)
    if "/app" not in pg.url and "/account" not in pg.url:
        pg.goto(B+"/login", wait_until="networkidle")
        pg.fill('input[name=email]', ADMIN); pg.fill('input[name=password]', PW)
        pg.click('button[type=submit]'); pg.wait_for_timeout(1200)

    for path,name,full in [("/","v_landing",True),("/pricing","v_pricing",True),
                            ("/faq","v_faq",True),("/account","v_account",True),
                            ("/contacts","v_contacts",True)]:
        pg.goto(B+path, wait_until="networkidle"); pg.wait_for_timeout(700)
        if full: reveal(pg)
        pg.wait_for_timeout(300)
        pg.screenshot(path=str(OUT/(name+".png")), full_page=full)
        print("shot", name)

    # tool smoke
    img = sorted(glob.glob("*.png"))[0]
    pg.goto(B+"/app", wait_until="networkidle"); pg.wait_for_timeout(700)
    pg.set_input_files('#file', img); pg.wait_for_timeout(3500)
    st = pg.evaluate("""()=>({fg:(document.getElementById('fgPreview').src||'').slice(0,16),
      bg:document.getElementById('bgBadge').textContent,obj:document.getElementById('objCount').textContent,
      samples:document.getElementById('samples').children.length})""")
    print("TOOL:", st, "| pageerrors:", errs[:3])
    pg.screenshot(path=str(OUT/"v_tool.png"))
    ctx.close(); b.close()
print("DONE")
