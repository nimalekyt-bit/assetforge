// AssetForge — фронтенд SPA. Реактивная связка: смена настроек -> analyze/preview (с дебаунсом).
"use strict";

const $ = (id) => document.getElementById(id);
const state = {
  sessionId: null,
  objects: [],
  activeObject: 0,
  batch: [],          // File[] для пакетной обработки
  presets: [],
};

// Человеческие подписи режимов фона для #bgBadge (вместо сырого data.bg_mode).
const BG_MODE_RU = {
  auto: "Авто", alpha: "Только alpha", white: "Белый фон", solid: "Однотонный",
  checker: "Шахматка", chroma: "Хромакей", ai: "AI (rembg)", none: "Без обработки",
};

// Маппинг HTTP-кодов в понятные русские сообщения.
function httpErrorRu(status) {
  if (status === 413) return "Файл слишком большой.";
  if (status === 415 || status === 422) return "Неподдерживаемый формат. Загрузите PNG, JPG или WebP.";
  if (status === 429) return "Слишком много запросов, подождите немного.";
  return "Что-то пошло не так при обработке. Попробуйте ещё раз или другой файл.";
}

// Разбор ответа-ошибки: достаёт detail (JSON) и решает, апселл это или нет.
// Возвращает { status, detail, upsell }.
async function readError(r) {
  let detail = "";
  try { detail = (await r.json().catch(() => ({}))).detail || ""; } catch (e) { /* нет тела */ }
  const upsell = r.status === 402 || /\/pricing/.test(detail || "");
  return { status: r.status, detail: detail || "", upsell };
}

// Показ ошибки в #status: для апселла — заметный баннер с кликабельной ссылкой,
// иначе — человеческое сообщение (русский detail сервера приоритетнее кода).
function showError(err) {
  if (err && err.upsell) {
    showUpsell(err.detail);
    return;
  }
  const status = err && err.status;
  const detail = err && err.detail;
  // русский detail от сервера показываем как есть (кроме «технических» английских)
  const useDetail = detail && /[а-яё]/i.test(detail);
  setStatus(escapeHtml(useDetail ? detail : httpErrorRu(status)), "err");
}

function showUpsell(detail) {
  const txt = (detail && /[а-яё]/i.test(detail)) ? detail : "Достигнут лимит тарифа.";
  const el = $("status");
  el.className = "status err upsell";
  const st = account.desktop;
  if (st) {
    // desktop: гость → предложить вход; вошедший free → тарифы (в браузере)
    const guest = !st.logged_in;
    const label = guest ? "Войти →" : "Перейти на Pro →";
    el.innerHTML = `<span class="upsell-text">${escapeHtml(txt)}</span>` +
      `<a class="upsell-cta" href="#" id="upsellCta">${label}</a>`;
    const cta = $("upsellCta");
    if (cta) cta.onclick = (e) => {
      e.preventDefault();
      if (guest) { $("loginErr").textContent = ""; $("loginModal").classList.remove("hidden"); $("loginEmail").focus(); }
      else { openUrl(st.pricing_url); }
    };
    toast(guest ? "Войдите, чтобы снять ограничения" : "Оформите Pro для полного доступа");
    return;
  }
  el.innerHTML = `<span class="upsell-text">${escapeHtml(txt)}</span>` +
    `<a class="upsell-cta" href="/pricing">Перейти на Pro →</a>`;
  toast("Достигнут лимит тарифа — перейдите на Pro");
}

function escapeHtml(s) {
  return String(s == null ? "" : s)
    .replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}

// ---- утилиты -------------------------------------------------------------
function setStatus(msg, cls = "") {
  const el = $("status");
  el.className = "status " + cls;
  el.innerHTML = cls === "busy" ? `<span class="spin"></span>${msg}` : msg;
}
function toast(msg, ms = 2200) {
  const t = $("toast");
  t.textContent = msg; t.classList.remove("hidden");
  clearTimeout(toast._t); toast._t = setTimeout(() => t.classList.add("hidden"), ms);
}
function debounce(fn, ms) {
  let h; return (...a) => { clearTimeout(h); h = setTimeout(() => fn(...a), ms); };
}
function hexToRgb(hex) {
  const m = /^#?([a-f\d]{2})([a-f\d]{2})([a-f\d]{2})$/i.exec(hex);
  return m ? [parseInt(m[1], 16), parseInt(m[2], 16), parseInt(m[3], 16)] : null;
}
function rgbToHex(rgb) {
  return "#" + rgb.map((c) => Math.max(0, Math.min(255, c | 0)).toString(16).padStart(2, "0")).join("");
}

// ---- сбор конфига из UI --------------------------------------------------
function selectedSizes() {
  return [...document.querySelectorAll('#sizes input:checked')].map((c) => +c.value);
}
function selectedFormats() {
  return [...document.querySelectorAll('#formats input:checked')].map((c) => c.value);
}
function buildConfig() {
  const useKey = $("keyAuto").dataset.auto !== "1";  // если не «Авто» — берём цвет из пикера
  return {
    background: {
      mode: $("bgMode").value,
      key_color: useKey ? hexToRgb($("keyColor").value) : null,
      tolerance: +$("tolerance").value,
      softness: +$("softness").value,
      despill_strength: +$("despill").value / 100,
      trim_alpha_threshold: +$("trim").value,
    },
    crop: {
      split: $("split").value,
      fit: $("fit").value,
      align: $("align").value,
      padding_pct: +$("padding").value,
      square: $("fit").value !== "width",
      merge_distance: +$("merge").value,
      grid_rows: +$("gridRows").value,
      grid_cols: +$("gridCols").value,
    },
    export: { sizes: selectedSizes(), formats: selectedFormats() },
  };
}
function payload(extra = {}) {
  return { session_id: state.sessionId, preset: null, config: buildConfig(), ...extra };
}

// ---- API -----------------------------------------------------------------
async function api(path, body) {
  const r = await fetch(path, {
    method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body),
  });
  if (!r.ok) throw await readError(r);
  return r.json();
}

// ---- загрузка ------------------------------------------------------------
async function uploadFile(file) {
  setStatus("Загрузка…", "busy");
  const fd = new FormData(); fd.append("file", file);
  const r = await fetch("/api/upload", { method: "POST", body: fd });
  if (!r.ok) { showError(await readError(r)); return; }
  const data = await r.json();
  state.sessionId = data.session_id;
  $("srcThumb").src = data.thumb;
  $("srcThumb").alt = data.filename || "Загруженное изображение";
  $("srcName").textContent = data.filename;
  $("srcDims").textContent = `${data.width}×${data.height}`;
  $("srcInfo").classList.remove("hidden");
  await analyze();
}

// ---- анализ (стадия фон + объекты) --------------------------------------
async function analyze() {
  if (!state.sessionId) return;
  setStatus("Анализ фона…", "busy");
  try {
    const data = await api("/api/analyze", payload());
    state.objects = data.objects;
    state.activeObject = 0;
    $("bgBadge").textContent = BG_MODE_RU[data.bg_mode] || data.bg_mode || "—";
    if (data.key_color && $("keyAuto").dataset.auto === "1")
      $("keyColor").value = rgbToHex(data.key_color);
    $("fgPreview").src = data.foreground;
    $("fgPreview").alt = "Превью: фон удалён";
    $("fgPreview").classList.add("has-img");
    $("bgNotes").textContent = (data.notes || []).join("\n");
    $("objCount").textContent = data.objects.length;
    renderObjects(data.object_thumbs);
    showSuggestion(data);
    setStatus("");
    await preview();
  } catch (e) { showError(e); }
}

const KIND_RU = {
  icon: "иконка", logo: "логотип", wordmark: "вордмарк/надпись",
  photo: "фото", illustration: "иллюстрация", "sprite-sheet": "спрайт-лист",
};
function showSuggestion(data) {
  const el = $("assetHint");
  if (!el) return;
  if (!data.suggested_preset) { el.classList.add("hidden"); return; }
  const kind = KIND_RU[data.asset_kind] || data.asset_kind || "ассет";
  const preset = data.suggested_preset;
  el.classList.remove("hidden");
  el.innerHTML = `<b>Похоже на:</b> ${kind} · рекомендуем пресет ` +
    `<a href="#" id="applyPreset">«${preset}»</a>`;
  const a = $("applyPreset");
  if (a) a.onclick = (e) => {
    e.preventDefault();
    const sel = $("preset");
    if ([...sel.options].some((o) => o.value === preset)) {
      sel.value = preset; applyPreset(preset); schedulePreview();
      el.classList.add("hidden");
    }
  };
}

function renderObjects(thumbs) {
  const box = $("objects"); box.innerHTML = "";
  (thumbs || []).forEach((url, i) => {
    const d = document.createElement("div");
    d.className = "obj" + (i === state.activeObject ? " active" : "");
    d.innerHTML = `<span class="num">${i + 1}</span><img src="${url}" alt="Объект ${i + 1}">`;
    d.onclick = () => { state.activeObject = i; renderObjects(thumbs); preview(); };
    box.appendChild(d);
  });
}

// ---- превью (стадия обрезка + реальные размеры) -------------------------
async function preview() {
  if (!state.sessionId || !state.objects.length) return;
  setStatus("Превью…", "busy");
  try {
    const data = await api("/api/preview", payload({ object_index: state.activeObject }));
    $("cropLight").src = data.cropped.light;
    $("cropLight").alt = "Обрезка на светлом фоне";
    $("cropDark").src = data.cropped.dark;
    $("cropDark").alt = "Обрезка на тёмном фоне";
    $("cropChecker").src = data.cropped.checker;
    $("cropChecker").alt = "Обрезка на прозрачном фоне (шахматка)";
    ["cropLight", "cropDark", "cropChecker"].forEach((id) => $(id).classList.add("has-img"));
    const [w, h] = [data.bbox[2] - data.bbox[0], data.bbox[3] - data.bbox[1]];
    $("cropBbox").textContent = `bbox ${w}×${h}`;
    renderSamples(data.samples);
    setStatus("");
  } catch (e) { showError(e); }
}

function renderSamples(samples) {
  const html = (samples || []).map((s) => {
    const side = Math.min(s.size, 128);
    return `<div class="sample"><div class="box" style="width:${side + 8}px;height:${side + 8}px">
      <img src="${s.url}" alt="Превью ${s.size}×${s.size} px" style="width:${side}px;height:${side}px"></div>
      <div class="lbl">${s.size}px</div></div>`;
  }).join("");
  $("samples").innerHTML = html || '<div class="muted tiny" style="padding:8px">Выберите хотя бы один размер.</div>';
}

// ---- экспорт -------------------------------------------------------------
async function exportZip(which) {
  if (!state.sessionId) { toast("Сначала загрузите файл"); return; }
  setStatus("Экспорт…", "busy");
  try {
    const r = await fetch("/api/export", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload({ object_index: which })),
    });
    if (!r.ok) throw await readError(r);
    downloadBlob(await r.blob(), "assetforge.zip");
    setStatus("Готово ✓", "ok");
    refreshUsage();           // обновить счётчик в шапке после успешного экспорта
  } catch (e) { showError(e); }
}

async function exportBatch() {
  if (!state.batch.length) { toast("Очередь batch пуста — перетащите несколько файлов/папку"); return; }
  setStatus(`Batch (${state.batch.length})…`, "busy");
  const fd = new FormData();
  state.batch.forEach((f) => fd.append("files", f));
  fd.append("preset_name", $("preset").value || "icon-set");
  fd.append("config", JSON.stringify(buildConfig()));
  try {
    const r = await fetch("/api/batch", { method: "POST", body: fd });
    if (!r.ok) throw await readError(r);
    downloadBlob(await r.blob(), "assetforge_batch.zip");
    setStatus("Batch готов ✓", "ok");
    refreshUsage();           // обновить счётчик в шапке после успешного batch
  } catch (e) { showError(e); }
}

function downloadBlob(blob, name) {
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a"); a.href = url; a.download = name; a.click();
  setTimeout(() => URL.revokeObjectURL(url), 4000);
}

// ---- пресеты -------------------------------------------------------------
async function loadPresets() {
  const r = await fetch("/api/presets"); const data = await r.json();
  state.presets = data.presets;
  const sel = $("preset"); sel.innerHTML = "";
  data.presets.forEach((p) => {
    const o = document.createElement("option");
    o.value = p.name; o.textContent = p.title; sel.appendChild(o);
  });
  sel.value = "icon-set";
  applyPreset("icon-set");
}
function applyPreset(name) {
  const p = state.presets.find((x) => x.name === name); if (!p) return;
  renderSizes(p.sizes);
  document.querySelectorAll('#formats input').forEach((c) => { c.checked = p.formats.includes(c.value); });
  // фит из пресета не приходит явно — оставляем текущее значение UI
}
function renderSizes(sizes) {
  const all = [...new Set([16, 24, 32, 44, 48, 64, 72, 96, 128, 144, 180, 192, 256, 310, 512, 1024, 2048])]
    .sort((a, b) => a - b);
  const active = new Set(sizes && sizes.length ? sizes : [16, 32, 48, 64, 128, 256, 512]);
  // объединяем стандартные + размеры пресета
  sizes.forEach((s) => { if (!all.includes(s)) all.push(s); });
  all.sort((a, b) => a - b);
  const box = $("sizes"); box.innerHTML = "";
  all.forEach((s) => {
    box.innerHTML += `<label class="chip"><input type="checkbox" value="${s}" ${active.has(s) ? "checked" : ""}> ${s}</label>`;
  });
  box.querySelectorAll("input").forEach((c) => c.addEventListener("change", schedulePreview));
  applyGating();
}

// ---- реактивность --------------------------------------------------------
const scheduleAnalyze = debounce(analyze, 280);   // меняет фон/детект -> пересчёт
const schedulePreview = debounce(preview, 200);   // меняет кадр/экспорт -> дёшево (кэш)

function bindControls() {
  // ползунки с подписями
  const sliders = [["tolerance", "vTol", (v) => v], ["softness", "vSoft", (v) => v],
    ["despill", "vDespill", (v) => (v / 100).toFixed(2)], ["trim", "vTrim", (v) => v],
    ["padding", "vPad", (v) => v], ["merge", "vMerge", (v) => v]];
  sliders.forEach(([id, lbl, fmt]) => {
    $(id).addEventListener("input", () => { $(lbl).textContent = fmt($(id).value); });
  });
  // влияют на стадию ФОН/ДЕТЕКТ -> analyze
  ["bgMode", "keyColor", "tolerance", "softness", "despill", "trim", "split", "merge", "gridRows", "gridCols"]
    .forEach((id) => $(id).addEventListener("input", () => {
      if (id === "keyColor") $("keyAuto").dataset.auto = "0";
      scheduleAnalyze();
    }));
  // влияют только на КАДР/ЭКСПОРТ -> preview
  ["fit", "align", "padding"].forEach((id) => $(id).addEventListener("input", schedulePreview));

  $("keyAuto").dataset.auto = "1";
  $("keyAuto").onclick = () => { $("keyAuto").dataset.auto = "1"; scheduleAnalyze(); };
  $("preset").onchange = () => { applyPreset($("preset").value); schedulePreview(); };
  // показ/скрытие настроек разделения под выбранный режим
  const updateSplitUI = () => {
    const m = $("split").value;
    $("gridRow").classList.toggle("hidden", m !== "grid");
    $("mergeRow").classList.toggle("hidden", !(m === "auto" || m === "objects"));
  };
  $("split").addEventListener("change", updateSplitUI);
  updateSplitUI();
  $("btnExportOne").onclick = () => exportZip(state.activeObject);
  $("btnExportAll").onclick = () => exportZip("all");
  $("btnBatch").onclick = exportBatch;
}

// ---- drag&drop + выбор файлов -------------------------------------------
function collectFiles(fileList) {
  return [...fileList].filter((f) => /\.(png|jpe?g|webp|bmp|gif|tiff?)$/i.test(f.name));
}
function addBatch(files) {
  state.batch = files;
  const box = $("batchItems"); box.innerHTML = "";
  files.forEach((f) => { box.innerHTML += `<div class="bi"><span class="ellipsis">${f.name}</span></div>`; });
  $("batchCount").textContent = files.length;
  $("batchList").classList.toggle("hidden", files.length === 0);
}
function handleFiles(fileList) {
  const files = collectFiles(fileList);
  if (!files.length) { toast("Не найдено картинок"); return; }
  if (files.length > 1) { addBatch(files); toast(`В очередь batch: ${files.length}. Превью — по первому.`); }
  uploadFile(files[0]);   // первый — в интерактивный предпросмотр
}

function bindDropzone() {
  const dz = $("drop");
  dz.onclick = (e) => { if (e.target.tagName !== "BUTTON") $("file").click(); };
  $("pickFiles").onclick = (e) => { e.stopPropagation(); $("file").click(); };
  $("pickFolder").onclick = (e) => { e.stopPropagation(); $("folder").click(); };
  $("file").onchange = (e) => handleFiles(e.target.files);
  $("folder").onchange = (e) => handleFiles(e.target.files);
  ["dragover", "dragenter"].forEach((ev) => dz.addEventListener(ev, (e) => { e.preventDefault(); dz.classList.add("drag"); }));
  ["dragleave", "drop"].forEach((ev) => dz.addEventListener(ev, (e) => { e.preventDefault(); dz.classList.remove("drag"); }));
  dz.addEventListener("drop", (e) => handleFiles(e.dataTransfer.files));
  window.addEventListener("dragover", (e) => e.preventDefault());
  window.addEventListener("drop", (e) => e.preventDefault());
}

// ---- аккаунт: desktop (вход в облако) ИЛИ облачный SaaS --------------------
const account = { desktop: null, plan: null, limits: null };   // текущие права для гейтинга

// Заблокировать/разблокировать контрол (чекбокс размера/формата) по правам тарифа.
function gateControl(input, ok) {
  const label = input.closest("label") || input.parentElement;
  if (!label) return;
  if (ok) {
    input.disabled = false; label.classList.remove("locked"); label.removeAttribute("title");
  } else {
    input.checked = false; input.disabled = true; label.classList.add("locked");
    label.title = "Доступно на платном тарифе";
  }
}

// Применить ограничения тарифа к UI: форматы, размеры, AI-фон.
function applyGating() {
  const lim = account.limits;
  if (!lim) return;
  const allowed = new Set((lim.formats || []).map((f) => String(f).toLowerCase()));
  document.querySelectorAll('#formats input').forEach((c) => gateControl(c, allowed.has(c.value.toLowerCase())));
  const maxDim = lim.max_dimension || 999999;
  document.querySelectorAll('#sizes input').forEach((c) => gateControl(c, (+c.value) <= maxDim));
  const aiOpt = document.querySelector('#bgMode option[value="ai"]');
  if (aiOpt) aiOpt.disabled = !lim.ai_background;
}

function bindGatingUpsell() {
  ["formats", "sizes"].forEach((id) => {
    const box = $(id);
    if (box) box.addEventListener("click", (e) => {
      if (e.target.closest("label.locked")) showUpsell("Эта опция доступна на платном тарифе.");
    });
  });
}

function openUrl(url) {
  // в нативном окне — открыть в системном браузере через мост pywebview
  try {
    if (window.pywebview && window.pywebview.api && window.pywebview.api.open_external) {
      window.pywebview.api.open_external(url); return;
    }
  } catch (e) { /* ignore */ }
  window.open(url, "_blank");
}

async function initAccount() {
  try {
    const r = await fetch("/api/desktop/status");
    if (r.ok) {
      const st = await r.json();
      if (st && st.desktop) { account.desktop = st; renderDesktopBar(st); bindDesktopAuth(); return; }
    }
  } catch (e) { /* не desktop */ }
  initSaas();                          // обычный облачный режим (сайт)
}

const PLAN_RU = { guest: "Гость", free: "Free", pro: "Pro", business: "Business" };

function renderDesktopBar(st) {
  $("deskInfo").classList.remove("hidden");
  $("deskPlan").textContent = PLAN_RU[st.plan] || (st.plan || "").toUpperCase();
  account.plan = st.plan; account.limits = st.limits; applyGating();
  const loggedIn = st.logged_in;
  $("deskEmail").textContent = loggedIn ? (st.email || "") : "";
  $("deskLoginBtn").classList.toggle("hidden", loggedIn);
  $("deskLogoutBtn").classList.toggle("hidden", !loggedIn);
  // «Pro» показываем гостю и free — это апселл; на pro/business прячем
  const showUpgrade = st.plan === "guest" || st.plan === "free";
  $("deskUpgrade").classList.toggle("hidden", !showUpgrade);
  if (st.offline_expired) toast("Pro не подтверждён офлайн — войдите при интернете");
}

function bindDesktopAuth() {
  const modal = $("loginModal");
  const open = () => { $("loginErr").textContent = ""; modal.classList.remove("hidden"); $("loginEmail").focus(); };
  const close = () => modal.classList.add("hidden");
  $("deskLoginBtn").onclick = open;
  $("loginCancel").onclick = close;
  modal.addEventListener("click", (e) => { if (e.target === modal) close(); });
  $("deskUpgrade").onclick = (e) => { e.preventDefault(); openUrl(account.desktop.pricing_url); };
  $("registerLink").onclick = (e) => { e.preventDefault(); openUrl(account.desktop.register_url); };
  $("deskLogoutBtn").onclick = desktopLogout;
  $("loginSubmit").onclick = desktopLogin;
  $("loginPass").addEventListener("keydown", (e) => { if (e.key === "Enter") desktopLogin(); });
}

async function desktopLogin() {
  const email = $("loginEmail").value.trim();
  const password = $("loginPass").value;
  $("loginErr").textContent = "";
  $("loginSubmit").disabled = true;
  try {
    const r = await fetch("/api/desktop/login", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ email, password }),
    });
    const data = await r.json();
    if (!data.ok) { $("loginErr").textContent = data.error || "Не удалось войти."; return; }
    account.desktop = data; renderDesktopBar(data);
    $("loginModal").classList.add("hidden");
    $("loginPass").value = "";
    toast(`Вход выполнен · тариф ${PLAN_RU[data.plan] || data.plan}`);
  } catch (e) {
    $("loginErr").textContent = "Ошибка сети. Попробуйте ещё раз.";
  } finally {
    $("loginSubmit").disabled = false;
  }
}

async function desktopLogout() {
  try {
    const r = await fetch("/api/desktop/logout", { method: "POST" });
    const data = await r.json();
    account.desktop = data; renderDesktopBar(data);
    toast("Вы вышли из аккаунта");
  } catch (e) { /* ignore */ }
}

// ---- SaaS-режим: показать тариф/использование, если есть /api/me ----------
// Запрос /api/me и обновление шапки. silent=true — не показывать блок заново.
async function refreshUsage(silent) {
  try {
    const r = await fetch("/api/me");
    if (!r.ok) return;                  // free/desktop — эндпоинта нет, тихо выходим
    const me = await r.json();
    account.plan = me.plan; account.limits = me.limits; applyGating();
    $("saasPlan").textContent = (me.plan || "free").toUpperCase();
    const u = me.usage || {};
    $("saasUsage").textContent = `экспортов: ${u.exports_used}/${u.exports_limit}`;
    if (!silent) $("saasInfo").classList.remove("hidden");
  } catch (e) { /* не SaaS — игнор */ }
}
async function initSaas() {
  await refreshUsage(false);
}

// ---- старт ---------------------------------------------------------------
bindControls();
bindDropzone();
bindGatingUpsell();
loadPresets();
initAccount();
setStatus("Перетащите изображение, чтобы начать.");
