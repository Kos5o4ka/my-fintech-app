import logging
import math
from datetime import datetime, date, timedelta
from typing import Optional

from flask import Blueprint, request, jsonify, render_template
from flask_login import login_required, current_user

from app.extensions import db, cache
from app.models import BondPortfolio
from app.services.moex_service import get_bond_cached
from app.services.portfolio_service import (
    build_portfolio_list,
    calc_portfolio_ytm,
    calc_tax_report,
    calc_sharpe_ratio,
    calc_monthly_profit,
    calc_portfolio_diversification,
)
from app.constants import TIMEFRAME_DAYS, MAX_CHART_POINTS, CHART_RANGE_TTL, STATS_TTL, BENCHMARK_TTL
from app.moex import get_moex_bond, get_rgbi_history, get_bond_history_all

logger = logging.getLogger(__name__)
analytics_bp = Blueprint("analytics", __name__)


@analytics_bp.route("/analytics")
@login_required
def analytics_page():
    """Страница аналитики портфеля."""
    return render_template("analytics.html", active_page="analytics")


@analytics_bp.route("/api/portfolio/tax", methods=["GET"])
@login_required
def portfolio_tax():
    """Налоговый отчёт за год — сделки + купоны + НДФЛ (Stage 4 UI)."""
    try:
        year = int(request.args.get("year", date.today().year))
    except (ValueError, TypeError):
        year = date.today().year

    cache_key = f"portfolio_tax:{current_user.id}:{year}"
    try:
        cached = cache.get(cache_key)
        if cached:
            return jsonify(cached)
    except Exception:
        pass

    year_start = date(year, 1, 1)
    year_end = date(year, 12, 31)
    sold = BondPortfolio.query.filter(
        BondPortfolio.user_id == current_user.id,
        BondPortfolio.is_sold == True,  # noqa: E712
        BondPortfolio.sell_date >= year_start,
        BondPortfolio.sell_date <= year_end,
    ).all()
    active = BondPortfolio.query.filter_by(user_id=current_user.id, is_sold=False).all()
    summary = calc_tax_report(sold, active, year)

    from app.services.moex_service import get_all_coupons_cached
    from datetime import datetime

    def get_bond_coupon_income(bond, end_date):
        if not bond.purchase_date:
            return 0.0
        cals = get_all_coupons_cached(bond.secid or bond.isin)
        inc = 0.0
        start_str = bond.purchase_date.isoformat()
        end_str = end_date.isoformat()
        for c in cals:
            if c.get("date") and start_str <= c["date"] <= end_str:
                val = c.get("value")
                if val is not None:
                    inc += val * bond.amount
        return round(inc, 2)

    # Build enriched response for Stage 4 Tax UI
    trades_list = []
    gross_profit = 0.0
    total_commission = 0.0
    for bond in sold:
        buy_p = float(bond.buy_price)
        sell_p = float(bond.sell_price) if bond.sell_price else buy_p
        comm = float(bond.broker_commission) if bond.broker_commission else 0.0
        coupon_inc = get_bond_coupon_income(bond, bond.sell_date)
        pnl = (sell_p - buy_p) * bond.amount - comm + coupon_inc
        gross_profit += pnl
        total_commission += comm
        trades_list.append(
            {
                "id": bond.id,
                "name": bond.name or bond.isin,
                "isin": bond.isin,
                "amount": bond.amount,
                "buy_price": round(buy_p, 2),
                "sell_price": round(sell_p, 2),
                "commission": round(comm, 2),
                "coupons": coupon_inc,
                "pnl": round(pnl, 2),
                "sell_date": bond.sell_date.strftime("%Y-%m-%d")
                if bond.sell_date
                else None,
            }
        )

    for bond in active:
        # For active bonds, we calculate coupons up to the end of the selected year
        coupon_inc = get_bond_coupon_income(bond, date(year, 12, 31))
        if coupon_inc > 0:
            buy_p = float(bond.buy_price)
            gross_profit += coupon_inc
            trades_list.append(
                {
                    "id": bond.id,
                    "name": bond.name or bond.isin,
                    "isin": bond.isin,
                    "amount": bond.amount,
                    "buy_price": round(buy_p, 2),
                    "sell_price": None,
                    "commission": 0.0,
                    "coupons": coupon_inc,
                    "pnl": round(coupon_inc, 2),
                    "sell_date": None,
                }
            )

    taxable_base = max(0.0, round(gross_profit, 2))
    tax_amount = round(taxable_base * 0.13, 2)

    result = {
        **summary,
        "gross_profit": round(gross_profit, 2),
        "total_commission": round(total_commission, 2),
        "taxable_base": taxable_base,
        "tax_amount": tax_amount,
        "trades": trades_list,
    }
    try:
        cache.set(cache_key, result, timeout=TAX_TTL)
    except Exception:
        pass
    return jsonify(result)


@analytics_bp.route("/api/portfolio/benchmark", methods=["GET"])
@login_required
def portfolio_benchmark():
    """Сравнение доходности портфеля с RGBI."""
    range_param = request.args.get("range", "month")
    cache_key = f"benchmark:{range_param}"
    cached = cache.get(cache_key)
    if cached:
        return jsonify(cached)

    days = TIMEFRAME_DAYS.get(range_param, 31)
    from_date = (
        (date.today() - timedelta(days=days)).strftime("%Y-%m-%d")
        if days < 9999
        else None
    )
    rgbi = get_rgbi_history(
        from_date=from_date, to_date=date.today().strftime("%Y-%m-%d")
    )
    result = {"range": range_param, "rgbi": rgbi}
    cache.set(cache_key, result, timeout=BENCHMARK_TTL)
    return jsonify(result)


@analytics_bp.route("/api/portfolio/sharpe", methods=["GET"])
@login_required
def portfolio_sharpe():
    """Коэффициент Шарпа по закрытым позициям портфеля (Stage 4)."""
    cache_key = f"portfolio_sharpe:{current_user.id}"
    try:
        cached = cache.get(cache_key)
        if cached:
            return jsonify(cached)
    except Exception:
        pass

    sold = BondPortfolio.query.filter_by(user_id=current_user.id, is_sold=True).all()
    result = calc_sharpe_ratio(sold)
    if result is None:
        response_data = {
            "sharpe": None,
            "reason": f"Недостаточно данных (закрытых позиций: {len(sold)}, нужно ≥ 3)",
        }
        return jsonify(response_data)
        
    try:
        cache.set(cache_key, result, timeout=SHARPE_TTL)
    except Exception:
        pass
    return jsonify(result)


def _bond_history_for_compare(isin: str, range_param: str) -> dict:
    """Вспомогательная функция: история цены одной облигации для вкладки Сравнение."""
    cache_key = f"bond_chart:{isin}:{range_param}"
    cached = cache.get(cache_key)
    if cached:
        return cached

    moex_data = get_moex_bond(isin)
    if not moex_data:
        return {"labels": [], "data": [], "name": isin}

    full = get_bond_history_all(moex_data["secid"], moex_data.get("facevalue", 1000))
    labels = full.get("labels", [])
    prices = full.get("data", [])

    if range_param in ("day", "week", "month"):
        cutoff = datetime.utcnow().date() - timedelta(days=TIMEFRAME_DAYS[range_param])
        combined = [
            (lbl, p)
            for lbl, p in zip(labels, prices)
            if _parse_date(lbl) and _parse_date(lbl) >= cutoff
        ]
        if not combined:
            take = min(100, len(labels))
            combined = list(zip(labels[-take:], prices[-take:]))
    else:
        combined = list(zip(labels, prices))

    if len(combined) > MAX_CHART_POINTS:
        step = math.ceil(len(combined) / MAX_CHART_POINTS)
        combined = [combined[i] for i in range(0, len(combined), step)]

    if combined:
        lbl_out, price_out = zip(*combined)
        result = {
            "labels": list(lbl_out),
            "data": list(price_out),
            "name": moex_data.get("name", isin),
        }
    else:
        result = {"labels": [], "data": [], "name": moex_data.get("name", isin)}

    cache.set(cache_key, result, timeout=CHART_RANGE_TTL)
    return result


def _parse_date(val) -> Optional[date]:
    if not val:
        return None
    try:
        return datetime.strptime(str(val)[:10], "%Y-%m-%d").date()
    except ValueError:
        return None


@analytics_bp.route("/api/portfolio/compare", methods=["GET"])
@login_required
def compare_bonds():
    """Сравнение динамики цен двух облигаций (нормировано к 100)."""
    isin1 = request.args.get("isin1", "").upper().strip()
    isin2 = request.args.get("isin2", "").upper().strip()
    range_param = request.args.get("range", "month")

    if not isin1 or not isin2:
        return jsonify({"status": "error", "message": "Оба ISIN обязательны"}), 400
    if isin1 == isin2:
        return jsonify({"status": "error", "message": "ISIN должны быть разными"}), 400

    cache_key = f"compare:{isin1}:{isin2}:{range_param}"
    cached = cache.get(cache_key)
    if cached:
        return jsonify(cached)

    d1 = _bond_history_for_compare(isin1, range_param)
    d2 = _bond_history_for_compare(isin2, range_param)

    def _normalize(prices: list) -> list:
        if not prices:
            return prices
        base = prices[0]
        return [round(p / base * 100, 2) if base else p for p in prices]

    response = {
        "status": "success",
        "labels": d1["labels"] or d2["labels"],
        "bond1": {"isin": isin1, "name": d1["name"], "data": _normalize(d1["data"])},
        "bond2": {"isin": isin2, "name": d2["name"], "data": _normalize(d2["data"])},
    }
    cache.set(cache_key, response, timeout=CHART_RANGE_TTL)
    return jsonify(response)


@analytics_bp.route("/api/portfolio_stats", methods=["GET"])
@login_required
def portfolio_stats():
    """Профит по месяцам."""
    cache_key = f"portfolio_stats:{current_user.id}"
    cached = cache.get(cache_key)
    if cached:
        return jsonify(cached)

    closed = BondPortfolio.query.filter_by(user_id=current_user.id, is_sold=True).all()
    monthly = calc_monthly_profit(closed)
    sorted_months = sorted(monthly.keys())
    result = {
        "labels": sorted_months,
        "datasets": [
            {
                "label": "Чистая зафиксированная прибыль (₽)",
                "data": [monthly[m] for m in sorted_months],
                "backgroundColor": "rgba(40, 167, 69, 0.2)",
                "borderColor": "rgba(40, 167, 69, 1)",
                "borderWidth": 2,
                "fill": True,
            }
        ],
    }
    cache.set(cache_key, result, timeout=STATS_TTL)
    return jsonify(result)


@analytics_bp.route("/api/dashboard/pnl_chart", methods=["GET"])
@login_required
def dashboard_pnl_chart():
    """Возвращает данные для area-чарта P&L на дашборде."""
    period = request.args.get("period", "30d")
    today = date.today()

    if period == "7d":
        start = today - timedelta(days=6)
        date_range = [start + timedelta(days=i) for i in range(7)]
        label_fmt = "%d.%m"
        tick_every = 1
    elif period == "ytd":
        start = date(today.year, 1, 1)
        date_range = []
        m = start
        while m <= today:
            date_range.append(m)
            if m.month == 12:
                m = date(m.year + 1, 1, 1)
            else:
                m = date(m.year, m.month + 1, 1)
        label_fmt = "%b"
        tick_every = 1
    else:  # 30d
        start = today - timedelta(days=29)
        date_range = [start + timedelta(days=i) for i in range(30)]
        label_fmt = "%d.%m"
        tick_every = 5

    sold = BondPortfolio.query.filter_by(user_id=current_user.id, is_sold=True).all()
    daily_pnl: dict[date, float] = {}
    for bond in sold:
        if not bond.sell_date:
            continue
        sell_p = float(bond.sell_price) if bond.sell_price else float(bond.buy_price)
        commission = float(bond.broker_commission) if bond.broker_commission else 0.0
        pnl = (sell_p - float(bond.buy_price)) * bond.amount - commission
        daily_pnl[bond.sell_date] = daily_pnl.get(bond.sell_date, 0.0) + pnl

    if period == "ytd":
        labels, data = [], []
        running = 0.0
        for d in date_range:
            for sell_date, pnl in daily_pnl.items():
                if sell_date.year == d.year and sell_date.month == d.month:
                    running += pnl
            labels.append(d.strftime(label_fmt))
            data.append(round(running, 2))
    else:
        labels, data = [], []
        running = 0.0
        for i, d in enumerate(date_range):
            running += daily_pnl.get(d, 0.0)
            labels.append(
                d.strftime(label_fmt)
                if i % tick_every == 0 or i == len(date_range) - 1
                else ""
            )
            data.append(round(running, 2))

    active = BondPortfolio.query.filter_by(user_id=current_user.id, is_sold=False).all()
    all_bonds, _ = build_portfolio_list(active)
    try:
        db.session.commit()
    except Exception:
        db.session.rollback()

    unrealized = round(
        sum(b.get("pnl_rub", 0.0) for b in all_bonds),
        2,
    )

    return jsonify(
        {"labels": labels, "data": data, "unrealized": unrealized, "period": period}
    )


@analytics_bp.route("/api/portfolio/diversification", methods=["GET"])
@login_required
def portfolio_diversification():
    """Анализ диверсификации портфеля по индексу HHI."""
    active = BondPortfolio.query.filter_by(user_id=current_user.id, is_sold=False).all()
    result = calc_portfolio_diversification(active)
    return jsonify(result)
