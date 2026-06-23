"""Загрузка тарифов и доступ к лимитам (расширяемо через plans.json)."""
from __future__ import annotations

import copy
import json
from functools import lru_cache
from pathlib import Path
from typing import Any

from .config import settings

_PLANS_FILE = Path(__file__).resolve().parent / "plans.json"

# переопределения тарифов из админки (цена/лимиты), накладываются поверх plans.json
_overrides: dict[str, dict] = {}


def apply_overrides(ovr: dict | None) -> None:
    global _overrides
    _overrides = ovr or {}


@lru_cache(maxsize=1)
def _base_plans() -> dict[str, dict[str, Any]]:
    return json.loads(_PLANS_FILE.read_text(encoding="utf-8"))


def load_plans() -> dict[str, dict[str, Any]]:
    """Тарифы: базовый plans.json + переопределения из админки (deep-merge лимитов)."""
    plans = copy.deepcopy(_base_plans())
    for pid, ov in (_overrides or {}).items():
        if pid not in plans or not isinstance(ov, dict):
            continue
        for k, v in ov.items():
            if k == "limits" and isinstance(v, dict):
                plans[pid].setdefault("limits", {}).update(v)
            else:
                plans[pid][k] = v
    return plans


def display_price(plan: dict[str, Any]) -> float:
    """Цена в текущей валюте отображения (RUB → price_rub, иначе price)."""
    if settings.currency.upper() == "RUB":
        return float(plan.get("price_rub", 0) or 0)
    return float(plan.get("price", 0) or 0)


def all_plans() -> list[dict[str, Any]]:
    """Список тарифов в порядке цены в текущей валюте (для страницы тарифов)."""
    return sorted(load_plans().values(), key=display_price)


def get_plan(plan_id: str) -> dict[str, Any]:
    plans = load_plans()
    return plans.get(plan_id, plans["free"])


def plan_exists(plan_id: str) -> bool:
    return plan_id in load_plans()


def plan_limits(plan_id: str) -> dict[str, Any]:
    return get_plan(plan_id).get("limits", {})


def is_paid_plan(plan_id: str) -> bool:
    plan = get_plan(plan_id)
    return (plan.get("price", 0) or 0) > 0 or (plan.get("price_rub", 0) or 0) > 0
