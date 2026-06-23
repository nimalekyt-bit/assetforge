# -*- coding: utf-8 -*-
"""Генератор папки improvements/ из результата workflow-аудита AssetForge.

Читает JSON-результат прогона и рендерит набор связных markdown-документов.
Также печатает компактный дайджест в stdout для сводки.
"""
from __future__ import annotations

import json
import os
from pathlib import Path

SRC = Path(r"C:\Users\tuz03\AppData\Local\Temp\claude\E--photovirez"
           r"\419c2e32-64cb-4fbd-a45d-503bbbcd313b\tasks\wcp57ijbs.output")
OUT = Path(r"E:\photovirez\improvements")

SEV_ORDER = {"critical": 0, "high": 1, "medium": 2, "low": 3}
SEV_RU = {"critical": "критично", "high": "высокая", "medium": "средняя", "low": "низкая"}
IMP_RU = {"high": "высокий", "medium": "средний", "low": "низкий"}

THEME_RU = {
    "asset-coverage": "Покрытие типов ассетов",
    "smart-engine": "Умный движок обработки",
    "platform-outputs": "Платформенные выгрузки и манифесты",
    "ux-copilot": "UX-помощник (копайлот)",
    "advanced-image": "Продвинутая обработка изображений",
    "growth-saas": "Рост и SaaS",
}


def esc(s):
    return str(s if s is not None else "").replace("|", "\\|").replace("\n", " ").strip()


def block(s):
    return str(s if s is not None else "").strip()


def load():
    return json.loads(SRC.read_text(encoding="utf-8"))


def w(path: Path, text: str):
    path.write_text(text.rstrip() + "\n", encoding="utf-8")


def theme_name(key):
    return THEME_RU.get(key, key)


# --------------------------------------------------------------------------
def doc_readme(d):
    st = d.get("stats", {})
    rm = d.get("roadmap", {})
    L = []
    L.append("# AssetForge — план развития («Умный AssetForge»)")
    L.append("")
    L.append("> Результат многоагентного аудита: 6 областей кода + веб-ресёрч конкурентов и "
             "платформенных требований, генерация фич по 6 темам, приоритезация и "
             "состязательная проверка реальности гэпов по коду.")
    L.append("")
    L.append("## Северная звезда")
    L.append("")
    L.append(block(rm.get("vision", "")))
    L.append("")
    L.append("## Что в этой папке")
    L.append("")
    L.append("| Файл | О чём |")
    L.append("|------|-------|")
    L.append("| `01-аудит.md` | Что уже умеет каждый модуль и где дыры (по severity) |")
    L.append("| `02-покрытие-ассетов.md` | Какие ассеты мы НЕ умеем делать и что добавить |")
    L.append("| `03-умные-фичи.md` | Что именно сделает приложение «умным» |")
    L.append("| `04-платформенные-выгрузки.md` | Корректные бандлы и манифесты под платформы |")
    L.append("| `05-roadmap.md` | Приоритезированный план по тирам (impact/effort) |")
    L.append("| `06-конкуренты.md` | Чем берут конкуренты и чего нам не хватает |")
    L.append("| `07-проверка-гэпов.md` | Состязательная проверка: что реально и выполнимо |")
    L.append("")
    L.append("## Сводка")
    L.append("")
    L.append(f"- Областей аудита: **{st.get('audit_areas', len(d.get('audits', [])))}**")
    L.append(f"- Тем ресёрча: **{st.get('research_topics', len(d.get('research', [])))}**")
    L.append(f"- Предложено фич: **{st.get('features', len(d.get('proposals', [])))}**")
    L.append(f"- Проверено топ-фич по коду: **{st.get('verified', len(d.get('verdicts', [])))}**, "
             f"из них подтверждено реальных гэпов: **{st.get('real_gaps', 0)}**")
    total_gaps = sum(len(a.get("gaps", [])) for a in d.get("audits", []))
    L.append(f"- Всего выявлено гэпов в коде: **{total_gaps}**")
    L.append("")
    bg = rm.get("biggest_gaps", [])
    if bg:
        L.append("## Главные дыры (мешают «делать почти любой ассет»)")
        L.append("")
        for g in bg:
            L.append(f"- {block(g)}")
        L.append("")
    qw = rm.get("quick_wins", [])
    if qw:
        L.append("## Быстрые победы (начать отсюда)")
        L.append("")
        for q in qw:
            L.append(f"- {block(q)}")
        L.append("")
    L.append("---")
    L.append("*Сгенерировано из аудита; правьте свободно. Детали — в файлах рядом.*")
    return "\n".join(L)


def doc_audit(d):
    L = ["# 01 — Аудит текущего функционала", ""]
    L.append("Для каждой области: что уже реализовано в коде и какие гэпы мешают сделать "
             "приложение умным/полным. Гэпы отсортированы по severity.")
    L.append("")
    for a in d.get("audits", []):
        L.append(f"## {a.get('area', '—')}")
        L.append("")
        caps = a.get("current_capabilities", [])
        if caps:
            L.append("**Что уже есть:**")
            L.append("")
            for c in caps:
                L.append(f"- {block(c)}")
            L.append("")
        gaps = sorted(a.get("gaps", []), key=lambda g: SEV_ORDER.get(g.get("severity", "low"), 9))
        if gaps:
            L.append("**Гэпы:**")
            L.append("")
            for g in gaps:
                sev = SEV_RU.get(g.get("severity", ""), g.get("severity", ""))
                L.append(f"### [{sev}] {block(g.get('title', '—'))}")
                L.append("")
                L.append(block(g.get("description", "")))
                L.append("")
                if g.get("user_impact"):
                    L.append(f"- **Что теряет пользователь:** {block(g['user_impact'])}")
                if g.get("evidence"):
                    L.append(f"- **Где видно:** {block(g['evidence'])}")
                L.append("")
        L.append("")
    return "\n".join(L)


def proposals_by_theme(d):
    by = {}
    for p in d.get("proposals", []):
        by.setdefault(p.get("theme", "—"), []).append(p)
    return by


def render_feature_table(feats):
    L = ["| Фича | Польза | Сложность | Эффект |", "|------|--------|:---------:|:------:|"]
    for f in feats:
        L.append(f"| {esc(f.get('title'))} | {esc(f.get('problem'))} | "
                 f"{esc(f.get('effort'))} | {IMP_RU.get(f.get('impact',''), esc(f.get('impact')))} |")
    return "\n".join(L)


def render_feature_details(feats):
    L = []
    for f in feats:
        L.append(f"### {block(f.get('title', '—'))}")
        L.append("")
        if f.get("category"):
            L.append(f"*Категория: {block(f['category'])} · сложность {block(f.get('effort'))} · "
                     f"эффект {IMP_RU.get(f.get('impact',''), block(f.get('impact')))}*")
            L.append("")
        if f.get("problem"):
            L.append(f"- **Проблема:** {block(f['problem'])}")
        if f.get("proposal"):
            L.append(f"- **Решение:** {block(f['proposal'])}")
        if f.get("smart_aspect"):
            L.append(f"- **В чём «ум»:** {block(f['smart_aspect'])}")
        if f.get("touches"):
            L.append(f"- **Затронуть:** {', '.join('`%s`' % t for t in f['touches'])}")
        if f.get("acceptance"):
            L.append(f"- **Готово, когда:** {block(f['acceptance'])}")
        L.append("")
    return "\n".join(L)


def doc_asset_coverage(d):
    by = proposals_by_theme(d)
    L = ["# 02 — Покрытие типов ассетов", ""]
    L.append("Цель владельца: инструмент должен уметь сделать **почти любой** ассет. "
             "Ниже — чего сейчас нет и что добавить.")
    L.append("")
    # из аудита — область покрытия
    for a in d.get("audits", []):
        if "покрыт" in a.get("area", "").lower():
            gaps = sorted(a.get("gaps", []), key=lambda g: SEV_ORDER.get(g.get("severity", "low"), 9))
            if gaps:
                L.append("## Что мы не покрываем (из аудита)")
                L.append("")
                for g in gaps:
                    sev = SEV_RU.get(g.get("severity", ""), "")
                    L.append(f"- **[{sev}] {block(g.get('title'))}** — {block(g.get('user_impact') or g.get('description'))}")
                L.append("")
    # обязательные выходы из ресёрча
    musts = []
    for r in d.get("research", []):
        musts += r.get("must_have_outputs", [])
    if musts:
        L.append("## Что обязан выдавать полный инструмент (из ресёрча)")
        L.append("")
        seen = set()
        for m in musts:
            k = block(m).lower()
            if k and k not in seen:
                seen.add(k)
                L.append(f"- {block(m)}")
        L.append("")
    feats = by.get("asset-coverage", [])
    if feats:
        L.append("## Предлагаемые фичи покрытия")
        L.append("")
        L.append(render_feature_table(feats))
        L.append("")
        L.append(render_feature_details(feats))
    return "\n".join(L)


def doc_smart(d):
    by = proposals_by_theme(d)
    rm = d.get("roadmap", {})
    L = ["# 03 — Умные фичи (что сделает AssetForge «умным»)", ""]
    L.append(block(rm.get("vision", "")))
    L.append("")
    # smart_ideas из ресёрча
    ideas = []
    for r in d.get("research", []):
        for s in r.get("smart_ideas", []):
            ideas.append(s)
    if ideas:
        L.append("## Идеи «ума» из ресёрча")
        L.append("")
        for s in ideas:
            line = f"- **{block(s.get('idea'))}** — {block(s.get('why_smart'))}"
            if s.get("feasibility"):
                line += f" _(реализуемость: {block(s['feasibility'])})_"
            L.append(line)
        L.append("")
    for key in ("smart-engine", "ux-copilot", "advanced-image"):
        feats = by.get(key, [])
        if not feats:
            continue
        L.append(f"## {theme_name(key)}")
        L.append("")
        L.append(render_feature_table(feats))
        L.append("")
        L.append(render_feature_details(feats))
    return "\n".join(L)


def doc_platform(d):
    by = proposals_by_theme(d)
    L = ["# 04 — Платформенные выгрузки и манифесты", ""]
    L.append("Чтобы «делать всё», мало нарезать размеры — нужно отдавать готовые **бандлы** "
             "под платформы с правильной структурой папок, манифестами и именами.")
    L.append("")
    for r in d.get("research", []):
        if "платформ" in r.get("topic", "").lower():
            musts = r.get("must_have_outputs", [])
            if musts:
                L.append("## Обязательные выходы по платформам")
                L.append("")
                for m in musts:
                    L.append(f"- {block(m)}")
                L.append("")
            bms = r.get("benchmarks", [])
            if bms:
                L.append("## Как делают другие")
                L.append("")
                L.append("| Источник/стандарт | Что требует/даёт | Чего нам не хватает |")
                L.append("|---|---|---|")
                for b in bms:
                    L.append(f"| {esc(b.get('name'))} | {esc(b.get('offers'))} | {esc(b.get('we_lack'))} |")
                L.append("")
    feats = by.get("platform-outputs", [])
    if feats:
        L.append("## Предлагаемые фичи")
        L.append("")
        L.append(render_feature_table(feats))
        L.append("")
        L.append(render_feature_details(feats))
    return "\n".join(L)


def doc_roadmap(d):
    rm = d.get("roadmap", {})
    L = ["# 05 — Roadmap", ""]
    L.append(block(rm.get("vision", "")))
    L.append("")
    for t in rm.get("tiers", []):
        L.append(f"## {block(t.get('name', '—'))}")
        L.append("")
        if t.get("rationale"):
            L.append(f"_{block(t['rationale'])}_")
            L.append("")
        items = t.get("items", [])
        if items:
            L.append("| Фича | Сложность | Эффект |")
            L.append("|------|:---------:|:------:|")
            for it in items:
                L.append(f"| {esc(it.get('title'))} | {esc(it.get('effort'))} | "
                         f"{IMP_RU.get(it.get('impact',''), esc(it.get('impact')))} |")
            L.append("")
            for it in items:
                L.append(f"### {block(it.get('title', '—'))}")
                L.append("")
                if it.get("why"):
                    L.append(f"- **Зачем:** {block(it['why'])}")
                if it.get("what"):
                    L.append(f"- **Что сделать:** {block(it['what'])}")
                if it.get("smart_aspect"):
                    L.append(f"- **В чём «ум»:** {block(it['smart_aspect'])}")
                if it.get("touches"):
                    L.append(f"- **Затронуть:** {', '.join('`%s`' % x for x in it['touches'])}")
                L.append(f"- **Оценка:** сложность {block(it.get('effort'))} · "
                         f"эффект {IMP_RU.get(it.get('impact',''), block(it.get('impact')))}")
                L.append("")
        L.append("")
    return "\n".join(L)


def doc_competitors(d):
    L = ["# 06 — Конкуренты и чего нам не хватает", ""]
    for r in d.get("research", []):
        bms = r.get("benchmarks", [])
        if not bms:
            continue
        L.append(f"## {block(r.get('topic', '—'))}")
        L.append("")
        L.append("| Инструмент/стандарт | Что предлагает | Чего нет у нас |")
        L.append("|---|---|---|")
        for b in bms:
            L.append(f"| {esc(b.get('name'))} | {esc(b.get('offers'))} | {esc(b.get('we_lack'))} |")
        L.append("")
    return "\n".join(L)


def doc_verify(d):
    L = ["# 07 — Состязательная проверка гэпов", ""]
    L.append("Топ-фичи roadmap проверены отдельными агентами по реальному коду: "
             "действительно ли гэпа ещё нет и выполнимо ли предложение.")
    L.append("")
    vs = d.get("verdicts", [])
    L.append("| Фича | Гэп реален | Выполнимо | Уточн. сложность |")
    L.append("|------|:----------:|:---------:|:----------------:|")
    for v in vs:
        L.append(f"| {esc(v.get('title'))} | {'да' if v.get('gap_is_real') else 'нет'} | "
                 f"{'да' if v.get('feasible') else 'нет'} | {esc(v.get('refined_effort'))} |")
    L.append("")
    for v in vs:
        L.append(f"### {block(v.get('title', '—'))}")
        L.append("")
        L.append(f"- **Гэп реален:** {'да' if v.get('gap_is_real') else 'нет (уже частично есть)'} · "
                 f"**выполнимо:** {'да' if v.get('feasible') else 'нет/сложно'}")
        if v.get("integration_point"):
            L.append(f"- **Куда встроить:** {block(v['integration_point'])}")
        if v.get("risk"):
            L.append(f"- **Риск:** {block(v['risk'])}")
        if v.get("note"):
            L.append(f"- **Замечание:** {block(v['note'])}")
        L.append("")
    return "\n".join(L)


def digest(d):
    rm = d.get("roadmap", {})
    out = []
    out.append("=== DIGEST ===")
    out.append("VISION: " + block(rm.get("vision", ""))[:600])
    out.append("")
    out.append("BIGGEST GAPS:")
    for g in rm.get("biggest_gaps", []):
        out.append("  - " + block(g))
    out.append("")
    out.append("QUICK WINS:")
    for q in rm.get("quick_wins", []):
        out.append("  - " + block(q))
    out.append("")
    out.append("TIERS:")
    for t in rm.get("tiers", []):
        out.append(f"  # {block(t.get('name'))} ({len(t.get('items', []))})")
        for it in t.get("items", []):
            out.append(f"     - {block(it.get('title'))} [{it.get('effort')}/{it.get('impact')}]")
    out.append("")
    out.append("VERDICT TITLES (real/feasible):")
    for v in d.get("verdicts", []):
        out.append(f"  - {block(v.get('title'))}: real={v.get('gap_is_real')} feasible={v.get('feasible')}")
    return "\n".join(out)


def main():
    d = load()
    OUT.mkdir(parents=True, exist_ok=True)
    files = {
        "README.md": doc_readme(d),
        "01-аудит.md": doc_audit(d),
        "02-покрытие-ассетов.md": doc_asset_coverage(d),
        "03-умные-фичи.md": doc_smart(d),
        "04-платформенные-выгрузки.md": doc_platform(d),
        "05-roadmap.md": doc_roadmap(d),
        "06-конкуренты.md": doc_competitors(d),
        "07-проверка-гэпов.md": doc_verify(d),
    }
    for name, text in files.items():
        w(OUT / name, text)
    print("WROTE", len(files), "files to", OUT)
    for name in files:
        print("  -", name, len((OUT / name).read_text(encoding="utf-8")), "chars")
    print()
    print(digest(d))


if __name__ == "__main__":
    main()
