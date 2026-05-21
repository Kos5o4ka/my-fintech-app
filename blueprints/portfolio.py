import csv
import logging
import math
import requests
from collections import defaultdict
from datetime import datetime, date, timedelta
from io import StringIO

from flask import Blueprint, request, jsonify, render_template, abort, make_response
from flask_login import login_required, current_user

from extensions import db, cache
from models import BondPortfolio
from moex import get_moex_bond, get_bond_history_all, get_coupon_calendar, search_bonds

logger = logging.getLogger(__name__)
portfolio_bp = Blueprint("portfolio", __name__)

_MOEX_CACHE_TTL = 900  # 15 minutes


def _get_moex_cached(isin: str) -> dict | None:
    """Thin wrapper around get_moex_bond() with 15-minute Flask-Cache."""
    key = f"moex_bond:{isin}"
    result = cache.get(key)
    if result is None:
        result = get_moex_bond(isin)
        if result is not None:
            try:
                cache.set(key, result, timeout=_MOEX_CACHE_TTL)
            except Exception:
                pass
    return result


# ── Page ──────────────────────────────────────────────────────────────────────

@portfolio_bp.route("/portfolio")
@login_required
def portfolio_page():
    return render_template("portfolio.html")


# ── Active portfolio ───────────────────────────────────────────────────────────

@portfolio_bp.route("/api/portfolio", methods=["GET"])
@login_required
def get_portfolio():
    active_bonds = BondPortfolio.query.filter_by(
        user_id=current_user.id, is_sold=False
    ).all()
    portfolio_list = []
    total_portfolio_value = 0.0

    for bond in active_bonds:
        last_p = float(bond.last_price) if bond.last_price is not None else float(bond.buy_price)
        buy_p = float(bond.buy_price)
        current_value = bond.amount * last_p
        total_portfolio_value += current_value

        # FEAT-2: P&L per position
        pnl = (last_p - buy_p) * bond.amount
        pnl_pct = ((last_p - buy_p) / buy_p * 100) if buy_p else 0.0

        moex_data = _get_moex_cached(bond.isin) or {}
        portfolio_list.append({
            "id": bond.id,
            "isin": bond.isin,
            "name": bond.name or "Облигация",
            "amount": bond.amount,
            "buy_price": buy_p,
            "last_price": last_p if bond.last_price is not None else None,
            "current_value": round(current_value, 2),
            "purchase_date": bond.purchase_date.strftime("%Y-%m-%d"),
            "nkd": moex_data.get("nkd", 0.0),
            "ytm": moex_data.get("ytm", 0.0),
            "pnl": round(pnl, 2),
            "pnl_pct": round(pnl_pct, 2),
        })

    return jsonify({
        "status": "success",
        "total_value": total_portfolio_value,
        "bonds": portfolio_list,
    })


# ── Trade history (FEAT-3) ─────────────────────────────────────────────────────

@portfolio_bp.route("/api/portfolio/history", methods=["GET"])
@login_required
def portfolio_history():
    closed = (
        BondPortfolio.query
        .filter_by(user_id=current_user.id, is_sold=True)
        .order_by(BondPortfolio.sell_date.desc())
        .all()
    )
    trades = []
    for bond in closed:
        buy_p = float(bond.buy_price)
        sell_p = float(bond.sell_price) if bond.sell_price else buy_p
        pnl = (sell_p - buy_p) * bond.amount
        pnl_pct = ((sell_p - buy_p) / buy_p * 100) if buy_p else 0.0
        trades.append({
            "id": bond.id,
            "isin": bond.isin,
            "name": bond.name or "Облигация",
            "amount": bond.amount,
            "buy_price": buy_p,
            "sell_price": round(sell_p, 2),
            "pnl": round(pnl, 2),
            "pnl_pct": round(pnl_pct, 2),
            "purchase_date": bond.purchase_date.strftime("%Y-%m-%d") if bond.purchase_date else None,
            "sell_date": bond.sell_date.strftime("%Y-%m-%d") if bond.sell_date else None,
        })
    return jsonify({"status": "success", "trades": trades})


# ── Bond search autocomplete (FEAT-4) ─────────────────────────────────────────

@portfolio_bp.route("/api/search_bond", methods=["GET"])
@login_required
def search_bond():
    q = request.args.get("q", "").strip()
    if len(q) < 2:
        return jsonify([])
    results = search_bonds(q, limit=8)
    return jsonify(results)


# ── Add bond ──────────────────────────────────────────────────────────────────

@portfolio_bp.route("/api/add_bond", methods=["POST"])
@login_required
def add_bond():
    data = request.get_json() or {}
    isin = data.get("isin", "").upper().strip()
    amount = data.get("amount")
    buy_price = data.get("buy_price")
    date_str = data.get("purchase_date", "").strip()

    if not all([isin, amount, buy_price]):
        return (
            jsonify({"status": "error", "message": "Все поля формы обязательны к заполнению."}),
            400,
        )

    try:
        purchase_date = (
            datetime.strptime(date_str, "%Y-%m-%d").date() if date_str else date.today()
        )
    except ValueError:
        return (
            jsonify({"status": "error", "message": "Неверный формат даты. Используйте ГГГГ-ММ-ДД."}),
            400,
        )

    moex_data = get_moex_bond(isin)
    if not moex_data:
        return (
            jsonify({"status": "error", "message": f"Облигация {isin} не найдена на Московской Бирже."}),
            404,
        )

    secid = moex_data["secid"]
    bond_title = moex_data.get("name", "Облигация")

    try:
        url = f"https://iss.moex.com/iss/securities/{secid}.json"
        res = requests.get(url, timeout=5).json()
        if res.get("description") and res["description"].get("data"):
            desc_data = res["description"]["data"]
            issue_date, mat_date = None, None
            for row in desc_data:
                if row[0] == "ISSUEDATE" and row[2]:
                    issue_date = datetime.strptime(row[2], "%Y-%m-%d").date()
                if row[0] == "MATDATE" and row[2]:
                    mat_date = datetime.strptime(row[2], "%Y-%m-%d").date()

            if issue_date and purchase_date < issue_date:
                return (
                    jsonify({
                        "status": "error",
                        "message": (
                            f"Ошибка валидации: облигация выпущена {issue_date}. "
                            "Нельзя купить бумагу до эмиссии."
                        ),
                    }),
                    400,
                )
            if mat_date and purchase_date > mat_date:
                return (
                    jsonify({
                        "status": "error",
                        "message": (
                            f"Ошибка валидации: облигация погашена {mat_date}. "
                            "Торги закрыты."
                        ),
                    }),
                    400,
                )
    except Exception as e:
        logger.warning("Date spec validation error for %s: %s", secid, e)

    live_price = moex_data.get("price", float(buy_price))
    new_bond = BondPortfolio(
        user_id=current_user.id,
        isin=isin,
        secid=secid,
        name=bond_title,
        amount=int(amount),
        buy_price=float(buy_price),
        last_price=live_price,
        purchase_date=purchase_date,
        is_sold=False,
    )
    db.session.add(new_bond)
    db.session.commit()
    return (
        jsonify({"status": "success", "message": f"Бумага {bond_title} успешно добавлена!"}),
        201,
    )


# ── Sell bond ─────────────────────────────────────────────────────────────────

@portfolio_bp.route("/api/sell_bond/<int:bond_id>", methods=["POST"])
@login_required
def sell_bond(bond_id):
    bond = db.session.get(BondPortfolio, bond_id)
    if bond is None:
        abort(404)
    if bond.user_id != current_user.id:
        abort(403)

    data = request.get_json() or {}
    sell_price_raw = data.get("sell_price")
    bond.is_sold = True
    bond.sell_date = date.today()
    bond.sell_price = (
        float(sell_price_raw)
        if sell_price_raw
        else (float(bond.last_price) if bond.last_price else float(bond.buy_price))
    )
    db.session.commit()
    return jsonify({
        "status": "success",
        "message": f"Облигация {bond.name} переведена в архив продаж.",
    })


# ── Bond chart ────────────────────────────────────────────────────────────────

@portfolio_bp.route("/api/bond_chart/<isin>", methods=["GET"])
@login_required
def get_bond_chart_data(isin):
    range_param = request.args.get("range", "all")
    cache_key = f"bond_chart:{isin}:{range_param}"
    cached = cache.get(cache_key)
    if cached:
        return jsonify(cached)

    moex_data = get_moex_bond(isin)
    if not moex_data:
        return jsonify({"status": "error", "message": "Бумага не найдена"}), 404

    full = get_bond_history_all(moex_data["secid"], moex_data.get("facevalue", 1000))
    labels = full.get("labels", [])
    prices = full.get("data", [])
    nkd_hist = full.get("nkd", [])
    ytm_hist = full.get("ytm", [])

    if range_param in ("day", "week", "month"):
        days_map = {"day": 1, "week": 7, "month": 31}
        cutoff = datetime.utcnow().date() - timedelta(days=days_map[range_param])
        combined = []
        for lbl, p, n, y in zip(labels, prices, nkd_hist, ytm_hist):
            try:
                d = datetime.strptime(lbl, "%Y-%m-%d").date()
            except Exception:
                continue
            if d >= cutoff:
                combined.append((lbl, p, n, y))
        if not combined:
            take = min(100, len(labels))
            combined = list(zip(labels[-take:], prices[-take:], nkd_hist[-take:], ytm_hist[-take:]))
    else:
        combined = list(zip(labels, prices, nkd_hist, ytm_hist))

    max_points = 800
    if len(combined) > max_points:
        step = math.ceil(len(combined) / max_points)
        combined = [combined[i] for i in range(0, len(combined), step)]

    if combined:
        labels_out, prices_out, nkd_out, ytm_out = zip(*combined)
        result = {
            "labels": list(labels_out),
            "data": list(prices_out),
            "nkd": list(nkd_out),
            "ytm": list(ytm_out),
        }
    else:
        result = {"labels": [], "data": [], "nkd": [], "ytm": []}

    ttl = 300 if range_param != "all" else 1800
    try:
        cache.set(cache_key, result, timeout=ttl)
    except Exception:
        pass

    return jsonify(result)


# ── Coupon calendar ───────────────────────────────────────────────────────────

@portfolio_bp.route("/api/portfolio/calendar", methods=["GET"])
@login_required
def get_portfolio_calendar():
    active_bonds = BondPortfolio.query.filter_by(
        user_id=current_user.id, is_sold=False
    ).all()
    events = []
    for bond in active_bonds:
        target = bond.secid or bond.isin
        coupons = get_coupon_calendar(target)
        for c in coupons:
            events.append({
                "name": bond.name or bond.isin,
                "isin": bond.isin,
                "date": c["date"],
                "total_payout": round(c["value"] * bond.amount, 2),
            })
    events.sort(key=lambda x: x["date"])
    return jsonify(events[:10])


# ── Export CSV ────────────────────────────────────────────────────────────────

@portfolio_bp.route("/api/portfolio/export", methods=["GET"])
@login_required
def export_portfolio_csv():
    active_bonds = BondPortfolio.query.filter_by(
        user_id=current_user.id, is_sold=False
    ).all()
    si = StringIO()
    cw = csv.writer(si)
    cw.writerow(["Название бумаги", "ISIN код", "Количество (шт)", "Цена покупки (руб)", "Дата сделки"])
    for bond in active_bonds:
        cw.writerow([bond.name, bond.isin, bond.amount, bond.buy_price, bond.purchase_date])
    response = make_response('﻿' + si.getvalue())
    response.headers["Content-Disposition"] = "attachment; filename=portfolio_report.csv"
    response.headers["Content-Type"] = "text/csv; charset=utf-8-sig"
    return response


# ── Portfolio stats chart ─────────────────────────────────────────────────────

@portfolio_bp.route("/api/portfolio_stats", methods=["GET"])
@login_required
def portfolio_stats():
    closed_deals = BondPortfolio.query.filter_by(
        user_id=current_user.id, is_sold=True
    ).all()
    monthly_profit = defaultdict(float)
    for bond in closed_deals:
        sell_p = (
            float(bond.sell_price)
            if bond.sell_price
            else (float(bond.last_price) if bond.last_price else float(bond.buy_price))
        )
        group_date = bond.sell_date or bond.purchase_date
        monthly_profit[group_date.strftime("%Y-%m")] += (
            sell_p - float(bond.buy_price)
        ) * bond.amount
    sorted_months = sorted(monthly_profit.keys())
    return jsonify({
        "labels": sorted_months,
        "datasets": [{
            "label": "Чистая зафиксированная прибыль (₽)",
            "data": [monthly_profit[m] for m in sorted_months],
            "backgroundColor": "rgba(40, 167, 69, 0.2)",
            "borderColor": "rgba(40, 167, 69, 1)",
            "borderWidth": 2,
            "fill": True,
        }],
    })
