import csv
import io
import logging
import math
import requests
from collections import defaultdict
from datetime import datetime, date, timedelta
from io import StringIO

import openpyxl
from openpyxl.styles import Font, PatternFill, Alignment

from flask import Blueprint, request, jsonify, render_template, abort, make_response
from flask_login import login_required, current_user

from extensions import db, cache
from models import BondPortfolio, Watchlist, Transaction
from moex import (
    get_moex_bond, get_bond_history_all, get_coupon_calendar,
    search_bonds, get_bond_details, _fetch_json,
    get_rgbi_history, get_screener_bonds,
)

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

    # Weighted average YTM (weight = current position value)
    ytm_weight_sum = sum(
        b["ytm"] * b["current_value"] for b in portfolio_list if b["ytm"]
    )
    portfolio_ytm = round(ytm_weight_sum / total_portfolio_value, 2) if total_portfolio_value else 0.0

    return jsonify({
        "status": "success",
        "total_value": total_portfolio_value,
        "portfolio_ytm": portfolio_ytm,
        "bonds": portfolio_list,
    })


# ── Trade history (FEAT-3) ─────────────────────────────────────────────────────

@portfolio_bp.route("/api/portfolio/history", methods=["GET"])
@login_required
def portfolio_history():
    date_from_str = request.args.get("date_from", "").strip()
    date_to_str = request.args.get("date_to", "").strip()

    query = BondPortfolio.query.filter_by(user_id=current_user.id, is_sold=True)
    if date_from_str:
        try:
            query = query.filter(
                BondPortfolio.sell_date >= datetime.strptime(date_from_str, "%Y-%m-%d").date()
            )
        except ValueError:
            pass
    if date_to_str:
        try:
            query = query.filter(
                BondPortfolio.sell_date <= datetime.strptime(date_to_str, "%Y-%m-%d").date()
            )
        except ValueError:
            pass
    closed = query.order_by(BondPortfolio.sell_date.desc()).all()
    trades = []
    for bond in closed:
        buy_p = float(bond.buy_price)
        sell_p = float(bond.sell_price) if bond.sell_price else buy_p
        commission = float(bond.broker_commission) if bond.broker_commission else 0.0
        pnl = (sell_p - buy_p) * bond.amount - commission
        pnl_pct = (pnl / (buy_p * bond.amount) * 100) if buy_p else 0.0
        trades.append({
            "id": bond.id,
            "isin": bond.isin,
            "name": bond.name or "Облигация",
            "amount": bond.amount,
            "buy_price": buy_p,
            "sell_price": round(sell_p, 2),
            "commission": round(commission, 2),
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


# ── Bond preview (live data before adding) ────────────────────────────────────

@portfolio_bp.route("/api/bond_preview/<isin>", methods=["GET"])
@login_required
def bond_preview(isin):
    isin = isin.upper().strip()
    cache_key = f"bond_preview:{isin}"
    cached = cache.get(cache_key)
    if cached:
        return jsonify(cached)

    moex_data = get_moex_bond(isin)
    if not moex_data:
        return jsonify({"status": "error", "message": "Облигация не найдена на Московской Бирже"}), 404

    details = get_bond_details(moex_data["secid"])
    result = {
        "status": "ok",
        "name": moex_data.get("name"),
        "price": moex_data.get("price"),
        "ytm": moex_data.get("ytm"),
        "nkd": moex_data.get("nkd"),
        "facevalue": moex_data.get("facevalue"),
        **details,
    }
    cache.set(cache_key, result, timeout=300)
    return jsonify(result)


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
        res = _fetch_json(f"https://iss.moex.com/iss/securities/{secid}.json")
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

    existing = BondPortfolio.query.filter_by(
        user_id=current_user.id, isin=isin, is_sold=False
    ).first()
    existing_amount = existing.amount if existing else 0

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
    db.session.add(Transaction(
        user_id=current_user.id,
        isin=isin,
        name=bond_title,
        tx_type="buy",
        amount=int(amount),
        price=float(buy_price),
        tx_date=purchase_date,
    ))
    db.session.commit()

    message = f"Бумага {bond_title} успешно добавлена!"
    return (
        jsonify({
            "status": "success",
            "message": message,
            "duplicate_warning": existing_amount > 0,
            "existing_amount": existing_amount,
        }),
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
    commission_raw = data.get("broker_commission")
    bond.is_sold = True
    bond.sell_date = date.today()
    bond.sell_price = (
        float(sell_price_raw)
        if sell_price_raw
        else (float(bond.last_price) if bond.last_price else float(bond.buy_price))
    )
    commission_val = None
    if commission_raw is not None:
        try:
            commission_val = float(commission_raw)
            bond.broker_commission = commission_val
        except (ValueError, TypeError):
            pass
    db.session.add(Transaction(
        user_id=current_user.id,
        isin=bond.isin,
        name=bond.name,
        tx_type="sell",
        amount=bond.amount,
        price=bond.sell_price,
        commission=commission_val,
        tx_date=bond.sell_date,
    ))
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


# ── Coupon income forecast ────────────────────────────────────────────────────

@portfolio_bp.route("/api/portfolio/income", methods=["GET"])
@login_required
def portfolio_income():
    cache_key = f"portfolio_income:{current_user.id}"
    cached = cache.get(cache_key)
    if cached:
        return jsonify(cached)

    active_bonds = BondPortfolio.query.filter_by(
        user_id=current_user.id, is_sold=False
    ).all()
    today = date.today()
    windows = {"30d": 30, "90d": 90, "365d": 365}
    totals: dict[str, float] = {k: 0.0 for k in windows}

    for bond in active_bonds:
        target = bond.secid or bond.isin
        coupons = get_coupon_calendar(target)
        for c in coupons:
            if not c["date"] or not c["value"]:
                continue
            try:
                coupon_date = datetime.strptime(c["date"], "%Y-%m-%d").date()
            except ValueError:
                continue
            delta = (coupon_date - today).days
            if delta < 0:
                continue
            payout = float(c["value"]) * bond.amount
            for key, days in windows.items():
                if delta <= days:
                    totals[key] += payout

    result = {k: round(v, 2) for k, v in totals.items()}
    cache.set(cache_key, result, timeout=900)
    return jsonify(result)


# ── Portfolio allocation (per-bond breakdown) ─────────────────────────────────

@portfolio_bp.route("/api/portfolio/allocation", methods=["GET"])
@login_required
def portfolio_allocation():
    active_bonds = BondPortfolio.query.filter_by(
        user_id=current_user.id, is_sold=False
    ).all()
    slices = []
    for bond in active_bonds:
        last_p = float(bond.last_price) if bond.last_price is not None else float(bond.buy_price)
        slices.append({
            "name": bond.name or bond.isin,
            "value": round(last_p * bond.amount, 2),
        })
    slices.sort(key=lambda x: x["value"], reverse=True)
    return jsonify(slices)


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


# ── Watchlist ─────────────────────────────────────────────────────────────────

@portfolio_bp.route("/api/watchlist", methods=["GET"])
@login_required
def get_watchlist():
    items = Watchlist.query.filter_by(user_id=current_user.id).order_by(Watchlist.added_at.desc()).all()
    result = []
    for item in items:
        moex_data = _get_moex_cached(item.isin) or {}
        result.append({
            "isin": item.isin,
            "name": item.name or item.isin,
            "added_at": item.added_at.strftime("%Y-%m-%d"),
            "price": moex_data.get("price"),
            "ytm": moex_data.get("ytm"),
            "nkd": moex_data.get("nkd"),
        })
    return jsonify(result)


@portfolio_bp.route("/api/watchlist", methods=["POST"])
@login_required
def add_to_watchlist():
    data = request.get_json() or {}
    isin = data.get("isin", "").upper().strip()
    if not isin:
        return jsonify({"status": "error", "message": "ISIN обязателен."}), 400
    if Watchlist.query.filter_by(user_id=current_user.id, isin=isin).first():
        return jsonify({"status": "error", "message": "Облигация уже в избранном."}), 409
    moex_data = get_moex_bond(isin)
    if not moex_data:
        return jsonify({"status": "error", "message": f"Облигация {isin} не найдена на MOEX."}), 404
    entry = Watchlist(
        user_id=current_user.id,
        isin=isin,
        secid=moex_data.get("secid"),
        name=moex_data.get("name", isin),
    )
    db.session.add(entry)
    db.session.commit()
    return jsonify({"status": "success", "message": f"{entry.name} добавлена в избранное."}), 201


@portfolio_bp.route("/api/watchlist/<isin>", methods=["DELETE"])
@login_required
def remove_from_watchlist(isin):
    entry = Watchlist.query.filter_by(user_id=current_user.id, isin=isin.upper()).first()
    if not entry:
        return jsonify({"status": "error", "message": "Не найдено."}), 404
    db.session.delete(entry)
    db.session.commit()
    return jsonify({"status": "success", "message": "Удалено из избранного."})


# ── Screener ──────────────────────────────────────────────────────────────────

@portfolio_bp.route("/api/screener", methods=["GET"])
@login_required
def screener():
    def _float_or_none(val):
        try:
            return float(val) if val else None
        except (ValueError, TypeError):
            return None

    min_ytm = _float_or_none(request.args.get("min_ytm"))
    max_ytm = _float_or_none(request.args.get("max_ytm"))
    maturity_from = request.args.get("maturity_from", "").strip() or None
    maturity_to = request.args.get("maturity_to", "").strip() or None

    cache_key = f"screener:{min_ytm}:{max_ytm}:{maturity_from}:{maturity_to}"
    cached = cache.get(cache_key)
    if cached:
        return jsonify(cached)

    results = get_screener_bonds(min_ytm, max_ytm, maturity_from, maturity_to, limit=100)
    cache.set(cache_key, results, timeout=300)
    return jsonify(results)


# ── Excel export ──────────────────────────────────────────────────────────────

@portfolio_bp.route("/api/portfolio/export/xlsx", methods=["GET"])
@login_required
def export_portfolio_xlsx():
    active_bonds = BondPortfolio.query.filter_by(user_id=current_user.id, is_sold=False).all()
    sold_bonds = BondPortfolio.query.filter_by(user_id=current_user.id, is_sold=True).order_by(
        BondPortfolio.sell_date.desc()
    ).all()

    wb = openpyxl.Workbook()

    header_font = Font(bold=True, color="FFFFFF")
    header_fill = PatternFill("solid", fgColor="1E7E34")
    center = Alignment(horizontal="center")

    # ── Sheet 1: active positions
    ws1 = wb.active
    ws1.title = "Портфель"
    headers1 = ["Название", "ISIN", "Кол-во", "Цена покупки (₽)", "Посл. цена (₽)", "P&L (₽)", "Дата покупки"]
    for col, h in enumerate(headers1, 1):
        cell = ws1.cell(row=1, column=col, value=h)
        cell.font = header_font
        cell.fill = header_fill
        cell.alignment = center
    for row_idx, bond in enumerate(active_bonds, 2):
        last_p = float(bond.last_price) if bond.last_price else float(bond.buy_price)
        pnl = round((last_p - float(bond.buy_price)) * bond.amount, 2)
        ws1.append([
            bond.name, bond.isin, bond.amount,
            float(bond.buy_price), round(last_p, 2), pnl,
            bond.purchase_date.strftime("%Y-%m-%d") if bond.purchase_date else "",
        ])
    for col in ws1.columns:
        ws1.column_dimensions[col[0].column_letter].width = max(len(str(cell.value or "")) for cell in col) + 4

    # ── Sheet 2: trade history
    ws2 = wb.create_sheet("История сделок")
    header_fill2 = PatternFill("solid", fgColor="155724")
    headers2 = ["Название", "ISIN", "Кол-во", "Цена покупки (₽)", "Цена продажи (₽)", "Комиссия (₽)", "P&L (₽)", "P&L %", "Дата продажи"]
    for col, h in enumerate(headers2, 1):
        cell = ws2.cell(row=1, column=col, value=h)
        cell.font = header_font
        cell.fill = header_fill2
        cell.alignment = center
    for bond in sold_bonds:
        buy_p = float(bond.buy_price)
        sell_p = float(bond.sell_price) if bond.sell_price else buy_p
        comm = float(bond.broker_commission) if bond.broker_commission else 0.0
        pnl = round((sell_p - buy_p) * bond.amount - comm, 2)
        pnl_pct = round(pnl / (buy_p * bond.amount) * 100, 2) if buy_p else 0.0
        ws2.append([
            bond.name, bond.isin, bond.amount,
            round(buy_p, 2), round(sell_p, 2), round(comm, 2),
            pnl, pnl_pct,
            bond.sell_date.strftime("%Y-%m-%d") if bond.sell_date else "",
        ])
    for col in ws2.columns:
        ws2.column_dimensions[col[0].column_letter].width = max(len(str(cell.value or "")) for cell in col) + 4

    buf = io.BytesIO()
    wb.save(buf)
    buf.seek(0)
    response = make_response(buf.read())
    response.headers["Content-Disposition"] = "attachment; filename=portfolio_report.xlsx"
    response.headers["Content-Type"] = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    return response


# ── Tax report ────────────────────────────────────────────────────────────────

@portfolio_bp.route("/api/portfolio/tax", methods=["GET"])
@login_required
def portfolio_tax():
    try:
        year = int(request.args.get("year", date.today().year))
    except (ValueError, TypeError):
        year = date.today().year

    year_start = date(year, 1, 1)
    year_end = date(year, 12, 31)

    sold = BondPortfolio.query.filter(
        BondPortfolio.user_id == current_user.id,
        BondPortfolio.is_sold == True,
        BondPortfolio.sell_date >= year_start,
        BondPortfolio.sell_date <= year_end,
    ).all()

    sales_income = 0.0
    for bond in sold:
        buy_p = float(bond.buy_price)
        sell_p = float(bond.sell_price) if bond.sell_price else buy_p
        comm = float(bond.broker_commission) if bond.broker_commission else 0.0
        pnl = (sell_p - buy_p) * bond.amount - comm
        if pnl > 0:
            sales_income += pnl

    # Coupon income: sum coupon payouts for active + sold bonds during this year
    # Approximate from coupon calendar (future coupons)
    active = BondPortfolio.query.filter_by(user_id=current_user.id, is_sold=False).all()
    coupon_income = 0.0
    for bond in active:
        target = bond.secid or bond.isin
        for c in get_coupon_calendar(target):
            if not c["date"] or not c["value"]:
                continue
            try:
                cd = datetime.strptime(c["date"], "%Y-%m-%d").date()
            except ValueError:
                continue
            if year_start <= cd <= year_end:
                coupon_income += float(c["value"]) * bond.amount

    tax_rate = 0.13
    total_income = round(sales_income + coupon_income, 2)
    return jsonify({
        "year": year,
        "sales_income": round(sales_income, 2),
        "coupon_income": round(coupon_income, 2),
        "total_income": total_income,
        "tax_13pct": round(total_income * tax_rate, 2),
    })


# ── RGBI benchmark ────────────────────────────────────────────────────────────

@portfolio_bp.route("/api/portfolio/benchmark", methods=["GET"])
@login_required
def portfolio_benchmark():
    range_param = request.args.get("range", "month")
    cache_key = f"benchmark:{range_param}"
    cached = cache.get(cache_key)
    if cached:
        return jsonify(cached)

    days_map = {"week": 7, "month": 31, "3m": 91, "year": 365, "all": 9999}
    days = days_map.get(range_param, 31)
    from_date = (date.today() - timedelta(days=days)).strftime("%Y-%m-%d") if days < 9999 else None

    rgbi = get_rgbi_history(from_date=from_date, to_date=date.today().strftime("%Y-%m-%d"))
    result = {"range": range_param, "rgbi": rgbi}
    cache.set(cache_key, result, timeout=3600)
    return jsonify(result)


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
