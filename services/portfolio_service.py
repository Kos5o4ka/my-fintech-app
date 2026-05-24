"""Сервис портфеля — P&L, доходность, купонный доход, налоги, Sharpe Ratio."""
import logging
import math
from collections import defaultdict
from datetime import datetime, date
from typing import Optional

from models import BondPortfolio
from services.moex_service import get_bond_cached, get_coupon_calendar_cached
from constants import NDFL_RATE
from moex import get_currency_rates

logger = logging.getLogger(__name__)


def build_portfolio_entry(bond: BondPortfolio) -> dict:
    """Строит словарь с данными одной активной позиции, включая P&L и MOEX-данные."""
    rates = get_currency_rates()
    currency = bond.currency or 'RUB'
    
    last_p = float(bond.last_price) if bond.last_price is not None else float(bond.buy_price)
    buy_p = float(bond.buy_price)
    
    current_value = bond.amount * last_p
    pnl = (last_p - buy_p) * bond.amount
    pnl_pct = ((last_p - buy_p) / buy_p * 100) if buy_p else 0.0
    
    # Расчет рублевого эквивалента
    rate = 1.0 if currency in ['RUB', 'GLD'] else rates.get(currency, 1.0)
    current_value_rub = current_value * rate
    pnl_rub = pnl * rate
    
    moex_data: dict = get_bond_cached(bond.isin) or {}
    
    return {
        "id": bond.id,
        "isin": bond.isin,
        "name": bond.name or "Облигация",
        "amount": bond.amount,
        "buy_price": buy_p,
        "last_price": last_p if bond.last_price is not None else None,
        "current_value": round(current_value, 2),
        "current_value_rub": round(current_value_rub, 2),
        "purchase_date": bond.purchase_date.strftime("%Y-%m-%d"),
        "nkd": moex_data.get("nkd", 0.0),
        "ytm": moex_data.get("ytm", 0.0),
        "pnl": round(pnl, 2),
        "pnl_rub": round(pnl_rub, 2),
        "pnl_pct": round(pnl_pct, 2),
        "currency": currency,
        "notes": bond.notes or "",
    }


def build_portfolio_list(active_bonds: list[BondPortfolio]) -> tuple[list[dict], float]:
    """Возвращает (список позиций, суммарная стоимость портфеля в RUB)."""
    portfolio_list: list[dict] = []
    total_value = 0.0
    for bond in active_bonds:
        entry = build_portfolio_entry(bond)
        total_value += entry["current_value_rub"]
        portfolio_list.append(entry)
    return portfolio_list, total_value


def calc_portfolio_ytm(portfolio_list: list[dict], total_value: float) -> float:
    """Средневзвешенная YTM портфеля (веса только по бумагам с валидным YTM).

    Поддерживает как 'current_value_rub' (multi-currency), так и устаревший
    'current_value' ключ для обратной совместимости с unit/property-тестами.
    """
    valid_bonds = [b for b in portfolio_list if b.get("ytm")]
    if not valid_bonds:
        return 0.0
    def _val(b: dict) -> float:
        return b.get("current_value_rub") or b.get("current_value") or 0.0
    ytm_weight_sum = sum(b["ytm"] * _val(b) for b in valid_bonds)
    total_valid_value = sum(_val(b) for b in valid_bonds)
    return round(ytm_weight_sum / total_valid_value, 2) if total_valid_value else 0.0


def build_trade_entry(bond) -> dict:
    """Строит словарь с итогами закрытой сделки (P&L, комиссии).

    Принимает как объекты BondPortfolio, так и SimpleNamespace (property-тесты).
    """
    buy_p = float(bond.buy_price)
    sell_p = float(bond.sell_price) if bond.sell_price else buy_p
    commission = float(bond.broker_commission) if bond.broker_commission else 0.0
    pnl = (sell_p - buy_p) * bond.amount - commission
    pnl_pct = (pnl / (buy_p * bond.amount) * 100) if buy_p else 0.0
    return {
        "id": bond.id,
        "isin": bond.isin,
        "name": getattr(bond, 'name', None) or "Облигация",
        "amount": bond.amount,
        "buy_price": buy_p,
        "sell_price": round(sell_p, 2),
        "commission": round(commission, 2),
        "pnl": round(pnl, 2),
        "pnl_pct": round(pnl_pct, 2),
        "currency": getattr(bond, 'currency', None) or 'RUB',
        "purchase_date": bond.purchase_date.strftime("%Y-%m-%d") if bond.purchase_date else None,
        "sell_date": bond.sell_date.strftime("%Y-%m-%d") if bond.sell_date else None,
    }


def calc_coupon_income(active_bonds: list[BondPortfolio]) -> dict[str, float]:
    """Прогноз купонного дохода в разрезах 30/90/365 дней в пересчете на RUB."""
    rates = get_currency_rates()
    today = date.today()
    windows: dict[str, int] = {"30d": 30, "90d": 90, "365d": 365}
    totals: dict[str, float] = {k: 0.0 for k in windows}
    for bond in active_bonds:
        target = bond.secid or bond.isin
        currency = bond.currency or 'RUB'
        rate = 1.0 if currency in ['RUB', 'GLD'] else rates.get(currency, 1.0)
        for c in get_coupon_calendar_cached(target):
            if not c["date"] or not c["value"]:
                continue
            try:
                coupon_date = datetime.strptime(c["date"], "%Y-%m-%d").date()
            except ValueError:
                continue
            delta = (coupon_date - today).days
            if delta < 0:
                continue
            payout = float(c["value"]) * bond.amount * rate
            for key, days in windows.items():
                if delta <= days:
                    totals[key] += payout
    return {k: round(v, 2) for k, v in totals.items()}


def calc_monthly_profit(closed_bonds: list[BondPortfolio]) -> dict[str, float]:
    """Ежемесячная зафиксированная прибыль по закрытым позициям в пересчете на RUB."""
    rates = get_currency_rates()
    monthly: dict[str, float] = defaultdict(float)
    for bond in closed_bonds:
        sell_p = (
            float(bond.sell_price)
            if bond.sell_price
            else (float(bond.last_price) if bond.last_price else float(bond.buy_price))
        )
        group_date = bond.sell_date or bond.purchase_date
        currency = bond.currency or 'RUB'
        rate = 1.0 if currency in ['RUB', 'GLD'] else rates.get(currency, 1.0)
        monthly[group_date.strftime("%Y-%m")] += (sell_p - float(bond.buy_price)) * bond.amount * rate
    return dict(monthly)


def calc_tax_report(
    sold_bonds: list[BondPortfolio],
    active_bonds: list[BondPortfolio],
    year: int,
) -> dict:
    """Расчёт НДФЛ 13% с дохода от сделок и купонных выплат за год в пересчете на RUB."""
    rates = get_currency_rates()
    year_start = date(year, 1, 1)
    year_end = date(year, 12, 31)
    sales_income = 0.0
    for bond in sold_bonds:
        buy_p = float(bond.buy_price)
        sell_p = float(bond.sell_price) if bond.sell_price else buy_p
        comm = float(bond.broker_commission) if bond.broker_commission else 0.0
        pnl = (sell_p - buy_p) * bond.amount - comm
        currency = bond.currency or 'RUB'
        rate = 1.0 if currency in ['RUB', 'GLD'] else rates.get(currency, 1.0)
        pnl_rub = pnl * rate
        if pnl_rub > 0:
            sales_income += pnl_rub

    coupon_income = 0.0
    all_bonds = list(active_bonds) + list(sold_bonds)
    for bond in all_bonds:
        target = bond.secid or bond.isin
        currency = bond.currency or 'RUB'
        rate = 1.0 if currency in ['RUB', 'GLD'] else rates.get(currency, 1.0)
        for c in get_coupon_calendar_cached(target):
            if not c["date"] or not c["value"]:
                continue
            try:
                cd = datetime.strptime(c["date"], "%Y-%m-%d").date()
            except ValueError:
                continue
            owned_from = bond.purchase_date
            owned_to = bond.sell_date  # None for active positions
            if (
                year_start <= cd <= year_end
                and cd >= owned_from
                and (owned_to is None or cd <= owned_to)
            ):
                coupon_income += float(c["value"]) * bond.amount * rate

    total_income = round(sales_income + coupon_income, 2)
    return {
        "year": year,
        "sales_income": round(sales_income, 2),
        "coupon_income": round(coupon_income, 2),
        "total_income": total_income,
        "tax_13pct": round(total_income * NDFL_RATE, 2),
    }


def calc_sharpe_ratio(sold_bonds: list) -> Optional[dict]:
    """Коэффициент Шарпа на основе доходностей закрытых позиций (Stage 4).

    Использует доходность каждой сделки как отдельное наблюдение.
    Безрисковая ставка ≈ 16%/12 в месяц (ставка ЦБ РФ, упрощённо).
    Требует ≥ 3 закрытых позиций.
    """
    returns: list[float] = []
    for bond in sold_bonds:
        buy_p = float(bond.buy_price)
        sell_p = float(bond.sell_price or bond.buy_price)
        if buy_p <= 0:
            continue
        returns.append(sell_p / buy_p - 1.0)

    n = len(returns)
    if n < 3:
        return None

    mean_r = sum(returns) / n
    variance = sum((r - mean_r) ** 2 for r in returns) / n
    std_r = math.sqrt(variance) if variance > 0 else 0.0

    if std_r == 0.0:
        return {
            "sharpe": None,
            "mean_return_pct": round(mean_r * 100, 2),
            "volatility_pct": 0.0,
            "sample_size": n,
            "note": "Нулевая волатильность — все сделки дали одинаковый результат",
        }

    # Безрисковая ставка: 16% годовых ÷ 12 = 1.33% в месяц (приблизительно)
    risk_free_per_trade = 0.16 / 12
    sharpe = (mean_r - risk_free_per_trade) / std_r

    return {
        "sharpe": round(sharpe, 2),
        "mean_return_pct": round(mean_r * 100, 2),
        "volatility_pct": round(std_r * 100, 2),
        "sample_size": n,
    }
