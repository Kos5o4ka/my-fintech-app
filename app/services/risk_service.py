"""Сервис риск-метрик: Sharpe, YTM, дюрация Маколея/модифицированная, HHI-диверсификация.

Только финансовая математика. Внешние данные подтягиваются через ``moex_service`` / ``moex``.
"""

from __future__ import annotations

import datetime
import math
from collections import defaultdict
from typing import Optional

from app.extensions import cache
from app.moex import get_currency_rates, get_gcurve_rate
from app.services.moex_service import get_bond_preview, get_coupon_calendar_cached

# TTL для расчётных метрик (1 час). Метрики зависят от купонного календаря
# и цены/YTM с MOEX, которые сами кэшируются 15 мин — 12 часов.
_METRICS_TTL = 3600


def calc_sharpe_ratio(
    sold_bonds: list,
    rf_annual: Optional[float] = None,
) -> Optional[dict]:
    """Sharpe Ratio по выборке закрытых позиций (формула Бесселя для дисперсии).

    Требует ≥ 3 закрытых позиций. ``rf_annual`` — годовая безрисковая ставка
    (по умолчанию берётся с G-curve MOEX).
    """
    returns: list[float] = []
    days_list: list[int] = []
    for bond in sold_bonds:
        buy_p = float(bond.buy_price)
        sell_p = float(bond.sell_price or bond.buy_price)
        if buy_p <= 0:
            continue
        returns.append(sell_p / buy_p - 1.0)
        try:
            if bond.sell_date and bond.purchase_date:
                days_list.append((bond.sell_date - bond.purchase_date).days)
        except (TypeError, AttributeError):
            pass

    n = len(returns)
    if n < 3:
        return None

    mean_r = sum(returns) / n
    variance = sum((r - mean_r) ** 2 for r in returns) / (n - 1)
    std_r = math.sqrt(variance) if variance > 0 else 0.0

    if std_r == 0.0:
        return {
            "sharpe": None,
            "mean_return_pct": round(mean_r * 100, 2),
            "volatility_pct": 0.0,
            "sample_size": n,
            "note": "Нулевая волатильность — все сделки дали одинаковый результат",
        }

    avg_days = sum(days_list) / len(days_list) if days_list else 180
    avg_years = max(avg_days / 365, 0.25)

    if rf_annual is None:
        try:
            rf_annual = get_gcurve_rate(maturity_years=avg_years)
        except Exception:
            rf_annual = 0.155

    risk_free_per_trade = rf_annual * (avg_days / 365)
    sharpe = (mean_r - risk_free_per_trade) / std_r

    return {
        "sharpe": round(sharpe, 2),
        "mean_return_pct": round(mean_r * 100, 2),
        "volatility_pct": round(std_r * 100, 2),
        "sample_size": n,
        "rf_annual_pct": round(rf_annual * 100, 2),
        "rf_source": "MOEX КБД",
        "rf_maturity_yrs": round(avg_years, 1),
    }


def calc_bond_ytm(
    isin: str, buy_price_rub: float, facevalue: float, nkd: float, purchase_date
) -> float | None:
    """YTM (%) методом Ньютона по будущим купонам и погашению."""
    if buy_price_rub <= 0:
        return None

    # Cache key — детерминирован от входов; результат меняется только при изменении
    # купонного календаря (он кэширован 12ч) или цены покупки.
    pd_key = (
        purchase_date.isoformat()
        if hasattr(purchase_date, "isoformat")
        else str(purchase_date)
    )
    cache_key = f"ytm:{isin}:{round(buy_price_rub, 2)}:{round(facevalue, 2)}:{round(nkd, 4)}:{pd_key}"
    cached = cache.get(cache_key)
    if cached is not None:
        return cached if cached != "__none__" else None

    coupons = get_coupon_calendar_cached(isin)
    if not coupons:
        cache.set(cache_key, "__none__", timeout=_METRICS_TTL)
        return None

    if isinstance(purchase_date, datetime.datetime):
        purchase_date = purchase_date.date()

    dirty_price = buy_price_rub + nkd
    cfs = []
    coupons_sorted = sorted(coupons, key=lambda x: x["date"])

    for i, c in enumerate(coupons_sorted):
        c_date_str = c.get("date") or c.get("coupondate") or ""
        if not c_date_str:
            continue
        try:
            c_date = datetime.datetime.strptime(c_date_str[:10], "%Y-%m-%d").date()
        except ValueError:
            continue

        t = (c_date - purchase_date).days / 365.25
        if t <= 0:
            continue

        val = float(c.get("value") or 0.0)
        if i == len(coupons_sorted) - 1:
            val += facevalue
        cfs.append((t, val))

    if not cfs:
        cache.set(cache_key, "__none__", timeout=_METRICS_TTL)
        return None

    def f(y):
        return sum(cf / ((1 + y) ** t) for t, cf in cfs) - dirty_price

    def df(y):
        return sum(-t * cf / ((1 + y) ** (t + 1)) for t, cf in cfs)

    y = 0.10
    try:
        for _ in range(100):
            # Защита: (1+y)**t уходит в комплексы при y <= -1; ограничиваем.
            if y <= -0.99 or y > 10.0:
                cache.set(cache_key, "__none__", timeout=_METRICS_TTL)
                return None
            val = f(y)
            der = df(y)
            if abs(val) < 1e-4:
                result = round(y * 100, 2)
                cache.set(cache_key, result, timeout=_METRICS_TTL)
                return result
            if der == 0:
                break
            y = y - val / der
    except (OverflowError, ValueError, ZeroDivisionError):
        cache.set(cache_key, "__none__", timeout=_METRICS_TTL)
        return None

    if y <= -0.99 or y > 10.0:
        cache.set(cache_key, "__none__", timeout=_METRICS_TTL)
        return None
    result = round(y * 100, 2)
    cache.set(cache_key, result, timeout=_METRICS_TTL)
    return result


def calc_bond_duration(
    isin: str, last_price: float, facevalue: float, ytm_pct: float, amount: int  # noqa: ARG001
) -> dict:
    """Дюрация Маколея и модифицированная (в годах)."""
    today = datetime.date.today()

    # Cache key — дюрация зависит только от ISIN, facevalue, YTM и сегодняшней даты
    # (купонный календарь сам кэшируется). Last_price и amount не влияют на расчёт.
    cache_key = f"dur:{isin}:{round(facevalue, 2)}:{round(ytm_pct, 2)}:{today.isoformat()}"
    cached = cache.get(cache_key)
    if cached is not None:
        return cached

    coupons = get_coupon_calendar_cached(isin)
    ytm = ytm_pct / 100.0 if ytm_pct and ytm_pct > 0 else 0.15  # fallback 15%

    if not coupons:
        details = get_bond_preview(isin) or {}
        matdate_str = details.get("matdate")
        if matdate_str:
            try:
                matdate = datetime.datetime.strptime(matdate_str[:10], "%Y-%m-%d").date()
                years = max((matdate - today).days / 365.25, 0.1)
                result = {
                    "macaulay_duration": round(years, 2),
                    "modified_duration": round(years / (1 + ytm), 2),
                }
                cache.set(cache_key, result, timeout=_METRICS_TTL)
                return result
            except Exception:
                pass
        result = {"macaulay_duration": 0.0, "modified_duration": 0.0}
        cache.set(cache_key, result, timeout=_METRICS_TTL)
        return result

    pv_sum = 0.0
    weighted_t_sum = 0.0
    coupons_sorted = sorted(coupons, key=lambda x: x["date"])

    # Защита от комплексного возведения в степень при ytm <= -1.
    if ytm <= -0.99:
        ytm = 0.15

    try:
        for i, c in enumerate(coupons_sorted):
            c_date_str = c.get("date") or c.get("coupondate") or ""
            if not c_date_str:
                continue
            try:
                c_date = datetime.datetime.strptime(c_date_str[:10], "%Y-%m-%d").date()
            except ValueError:
                continue

            t = (c_date - today).days / 365.25
            if t <= 0:
                continue

            val = float(c.get("value") or 0.0)
            if i == len(coupons_sorted) - 1:
                val += facevalue

            pv_cf = val / ((1 + ytm) ** t)
            pv_sum += pv_cf
            weighted_t_sum += t * pv_cf
    except (OverflowError, ValueError, ZeroDivisionError):
        result = {"macaulay_duration": 0.0, "modified_duration": 0.0}
        cache.set(cache_key, result, timeout=_METRICS_TTL)
        return result

    if pv_sum <= 0:
        result = {"macaulay_duration": 0.0, "modified_duration": 0.0}
        cache.set(cache_key, result, timeout=_METRICS_TTL)
        return result

    macaulay_dur = weighted_t_sum / pv_sum
    modified_dur = macaulay_dur / (1 + ytm)

    result = {
        "macaulay_duration": round(macaulay_dur, 2),
        "modified_duration": round(modified_dur, 2),
    }
    cache.set(cache_key, result, timeout=_METRICS_TTL)
    return result


def calc_portfolio_diversification(active_bonds: list) -> dict:
    """HHI-диверсификация в 3-х разрезах: активы, валюты, эмитенты (ОФЗ / корпорат.)."""
    if not active_bonds:
        empty = {"hhi": 0.0, "status": "Нет данных", "weights": []}
        return {"assets": empty, "currencies": empty, "issuers": empty}

    rates = get_currency_rates()
    total_val_rub = 0.0
    asset_vals: dict[str, float] = {}
    currency_vals: dict[str, float] = defaultdict(float)
    issuer_vals: dict[str, float] = defaultdict(float)

    for bond in active_bonds:
        currency = bond.currency or "RUB"
        rate = 1.0 if currency in ("RUB", "GLD") else rates.get(currency, 1.0)
        price = (
            float(bond.last_price)
            if bond.last_price is not None
            else float(bond.buy_price)
        )
        val_rub = price * bond.amount * rate

        total_val_rub += val_rub
        key_name = bond.name or bond.isin
        asset_vals[key_name] = asset_vals.get(key_name, 0.0) + val_rub
        currency_vals[currency] += val_rub

        isin = bond.isin.upper().strip()
        if (
            isin.startswith("SU")
            or isin.startswith("RU000A0J")
            or "ОФЗ" in (bond.name or "").upper()
        ):
            issuer_type = "Гос. облигации (ОФЗ)"
        else:
            issuer_type = "Корпоративные облигации"
        issuer_vals[issuer_type] += val_rub

    if total_val_rub <= 0:
        empty = {"hhi": 0.0, "status": "Нет данных", "weights": []}
        return {"assets": empty, "currencies": empty, "issuers": empty}

    def _calc_hhi_metrics(vals_dict: dict) -> dict:
        weights = []
        hhi = 0.0
        for name, val in vals_dict.items():
            w = (val / total_val_rub) * 100.0
            weights.append(
                {"name": name, "weight": round(w, 2), "value_rub": round(val, 2)}
            )
            hhi += w**2

        weights.sort(key=lambda x: x["weight"], reverse=True)

        if hhi < 1500:
            status, color = "Отличная диверсификация", "success"
        elif hhi <= 2500:
            status, color = "Умеренная концентрация", "warning"
        else:
            status, color = "Высокая концентрация (высокий риск)", "danger"

        return {
            "hhi": round(hhi, 2),
            "status": status,
            "color": color,
            "weights": weights,
        }

    return {
        "assets": _calc_hhi_metrics(asset_vals),
        "currencies": _calc_hhi_metrics(currency_vals),
        "issuers": _calc_hhi_metrics(issuer_vals),
    }
