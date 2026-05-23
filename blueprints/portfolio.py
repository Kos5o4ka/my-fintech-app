import hashlib
import io
import csv
import json
import logging
import math
from datetime import datetime, date, timedelta
from typing import Optional

import requests
import openpyxl
from openpyxl.styles import Font, PatternFill, Alignment
from io import StringIO
from pydantic import ValidationError

from flask import Blueprint, request, jsonify, render_template, abort, make_response
from flask_login import login_required, current_user

from extensions import db, cache
from models import BondPortfolio, Watchlist, Transaction
from moex import (
    get_moex_bond, get_bond_history_all,
    search_bonds, _fetch_json, get_rgbi_history, get_screener_bonds,
)
from services.moex_service import get_bond_cached, get_bond_preview, get_coupon_calendar_cached
from services.portfolio_service import (
    build_portfolio_list, calc_portfolio_ytm,
    build_trade_entry, calc_coupon_income,
    calc_monthly_profit, calc_tax_report, calc_sharpe_ratio,
)
from schemas.portfolio import AddBondRequest, SellBondRequest, ScreenerRequest
from constants import (
    INCOME_TTL, CHART_RANGE_TTL, CHART_ALL_TTL,
    BENCHMARK_TTL, SCREENER_TTL, MAX_CHART_POINTS, STATS_TTL,
    DEFAULT_PAGE_SIZE, MAX_PAGE_SIZE,
)

logger = logging.getLogger(__name__)
portfolio_bp = Blueprint("portfolio", __name__)


# ── Утилиты ───────────────────────────────────────────────────────────────────

def _etag(payload: dict) -> str:
    """Быстрый ETag из MD5 тела ответа (первые 16 символов)."""
    raw = json.dumps(payload, ensure_ascii=False, sort_keys=True)
    return hashlib.md5(raw.encode()).hexdigest()[:16]


def _bust_user_cache(user_id: int) -> None:
    """Инвалидирует кэши, зависящие от состава портфеля пользователя."""
    for key in [
        f"portfolio_income:{user_id}",
        f"portfolio_stats:{user_id}",
    ]:
        try:
            cache.delete(key)
        except Exception:
            pass


# ── Страница ──────────────────────────────────────────────────────────────────

@portfolio_bp.route("/portfolio")
@login_required
def portfolio_page() -> str:
    return render_template("portfolio.html")


# ── Активный портфель ─────────────────────────────────────────────────────────

@portfolio_bp.route("/api/portfolio", methods=["GET"])
@login_required
def get_portfolio():
    page = max(request.args.get("page", 1, type=int), 1)
    per_page = min(request.args.get("per_page", DEFAULT_PAGE_SIZE, type=int), MAX_PAGE_SIZE)

    q = BondPortfolio.query.filter_by(user_id=current_user.id, is_sold=False)
    total_count = q.count()
    active = q.order_by(BondPortfolio.id).offset((page - 1) * per_page).limit(per_page).all()

    bonds, total_val = build_portfolio_list(active)
    ytm = calc_portfolio_ytm(bonds, total_val)

    payload = {
        "status": "success",
        "total_value": total_val,
        "portfolio_ytm": ytm,
        "bonds": bonds,
        "pagination": {
            "page": page,
            "per_page": per_page,
            "total": total_count,
            "pages": math.ceil(total_count / per_page) if per_page else 1,
        },
    }

    # ETag — клиент может прислать If-None-Match и получить 304
    tag = _etag(payload)
    if request.headers.get("If-None-Match") == tag:
        return "", 304

    resp = make_response(jsonify(payload))
    resp.headers["ETag"] = tag
    resp.headers["Cache-Control"] = "private, max-age=60"
    return resp


# ── Заметки к позиции ────────────────────────────────────────────────────────

@portfolio_bp.route("/api/portfolio/<int:bond_id>/notes", methods=["PATCH"])
@login_required
def update_bond_notes(bond_id: int):
    """Обновляет заметку к позиции портфеля (Stage 4)."""
    bond = BondPortfolio.query.filter_by(id=bond_id, user_id=current_user.id).first_or_404()
    data = request.get_json() or {}
    raw = (data.get("notes") or "").strip()
    bond.notes = raw if raw else None
    db.session.commit()
    return jsonify({"status": "success", "notes": bond.notes or ""})


def build_transaction_entry(t: Transaction) -> dict:
    buy_p = float(t.price)
    sell_p = float(t.price)
    commission = float(t.commission) if t.commission else 0.0
    pnl = 0.0
    pnl_pct = 0.0
    sell_date = None
    purchase_date = None

    if t.tx_type == "sell":
        sell_date = t.tx_date.strftime("%Y-%m-%d")
        # Try to find corresponding BondPortfolio record to get buy_price
        bond = BondPortfolio.query.filter_by(
            user_id=t.user_id,
            isin=t.isin,
            is_sold=True,
            amount=t.amount,
            sell_date=t.tx_date
        ).first()
        if bond:
            buy_p = float(bond.buy_price)
            sell_p = float(bond.sell_price) if bond.sell_price else float(t.price)
            commission = float(bond.broker_commission) if bond.broker_commission else commission
            pnl = (sell_p - buy_p) * t.amount - commission
            pnl_pct = (pnl / (buy_p * t.amount) * 100) if buy_p else 0.0
            if bond.purchase_date:
                purchase_date = bond.purchase_date.strftime("%Y-%m-%d")
    else:
        purchase_date = t.tx_date.strftime("%Y-%m-%d")

    return {
        "id": t.id,
        "isin": t.isin,
        "name": t.name or "Облигация",
        "tx_type": t.tx_type,
        "amount": t.amount,
        "buy_price": buy_p,
        "sell_price": round(sell_p, 2),
        "commission": round(commission, 2),
        "pnl": round(pnl, 2),
        "pnl_pct": round(pnl_pct, 2),
        "purchase_date": purchase_date,
        "sell_date": sell_date,
        "date": t.tx_date.strftime("%Y-%m-%d"),
        "currency": t.currency or "RUB",
    }


# ── История сделок ────────────────────────────────────────────────────────────

@portfolio_bp.route("/api/portfolio/history", methods=["GET"])
@login_required
def portfolio_history():
    page = max(request.args.get("page", 1, type=int), 1)
    per_page = min(request.args.get("per_page", DEFAULT_PAGE_SIZE, type=int), MAX_PAGE_SIZE)
    date_from_str = request.args.get("date_from", "").strip()
    date_to_str = request.args.get("date_to", "").strip()
    tx_type = request.args.get("tx_type")

    # Dynamic self-healing synthesis from BondPortfolio if Transactions are empty
    tx_count = Transaction.query.filter_by(user_id=current_user.id).count()
    if tx_count == 0:
        bonds = BondPortfolio.query.filter_by(user_id=current_user.id).all()
        for b in bonds:
            buy_tx = Transaction(
                user_id=current_user.id,
                isin=b.isin,
                name=b.name,
                tx_type="buy",
                amount=b.amount,
                price=b.buy_price,
                tx_date=b.purchase_date,
                commission=0.0
            )
            db.session.add(buy_tx)
            if b.is_sold:
                sell_tx = Transaction(
                    user_id=current_user.id,
                    isin=b.isin,
                    name=b.name,
                    tx_type="sell",
                    amount=b.amount,
                    price=b.sell_price if b.sell_price is not None else b.buy_price,
                    tx_date=b.sell_date if b.sell_date is not None else b.purchase_date,
                    commission=b.broker_commission
                )
                db.session.add(sell_tx)
        db.session.commit()

    if tx_type is None:
        tx_type = "sell"

    query = Transaction.query.filter_by(user_id=current_user.id)
    if tx_type in ("buy", "sell"):
        query = query.filter_by(tx_type=tx_type)
    
    if date_from_str:
        try:
            query = query.filter(
                Transaction.tx_date >= datetime.strptime(date_from_str, "%Y-%m-%d").date()
            )
        except ValueError:
            pass
    if date_to_str:
        try:
            query = query.filter(
                Transaction.tx_date <= datetime.strptime(date_to_str, "%Y-%m-%d").date()
            )
        except ValueError:
            pass

    total_count = query.count()
    tx_list = query.order_by(Transaction.tx_date.desc(), Transaction.id.desc()).offset((page - 1) * per_page).limit(per_page).all()
    return jsonify({
        "status": "success",
        "trades": [build_transaction_entry(t) for t in tx_list],
        "pagination": {
            "page": page,
            "per_page": per_page,
            "total": total_count,
            "pages": math.ceil(total_count / per_page) if per_page else 1,
        },
    })


# ── Поиск облигаций ───────────────────────────────────────────────────────────

@portfolio_bp.route("/api/search_bond", methods=["GET"])
@login_required
def search_bond():
    q = request.args.get("q", "").strip()
    if len(q) < 2:
        return jsonify([])
    return jsonify(search_bonds(q, limit=8))


# ── Превью облигации ──────────────────────────────────────────────────────────

@portfolio_bp.route("/api/bond_preview/<isin>", methods=["GET"])
@login_required
def bond_preview(isin: str):
    isin = isin.upper().strip()
    result = get_bond_preview(isin)
    if not result:
        return jsonify({"status": "error", "message": "Облигация не найдена на Московской Бирже"}), 404
    return jsonify(result)


# ── Добавить облигацию ────────────────────────────────────────────────────────

@portfolio_bp.route("/api/add_bond", methods=["POST"])
@login_required
def add_bond():
    try:
        req = AddBondRequest.model_validate(request.get_json() or {})
    except ValidationError as e:
        first_error = e.errors()[0]["msg"].replace("Value error, ", "")
        return jsonify({"status": "error", "message": first_error}), 400

    isin = req.isin
    purchase_date = (
        datetime.strptime(req.purchase_date, "%Y-%m-%d").date()
        if req.purchase_date
        else date.today()
    )

    moex_data = get_moex_bond(isin)
    if not moex_data:
        return jsonify({"status": "error", "message": f"Облигация {isin} не найдена на Московской Бирже."}), 404

    secid = moex_data["secid"]
    bond_title = moex_data.get("name", "Облигация")

    # Проверка дат размещения и погашения
    try:
        res = _fetch_json(f"https://iss.moex.com/iss/securities/{secid}.json")
        if res.get("description") and res["description"].get("data"):
            issue_date: Optional[date] = None
            mat_date: Optional[date] = None
            for row in res["description"]["data"]:
                if row[0] == "ISSUEDATE" and row[2]:
                    issue_date = datetime.strptime(row[2], "%Y-%m-%d").date()
                if row[0] == "MATDATE" and row[2]:
                    mat_date = datetime.strptime(row[2], "%Y-%m-%d").date()
            if issue_date and purchase_date < issue_date:
                return jsonify({
                    "status": "error",
                    "message": f"Ошибка валидации: облигация выпущена {issue_date}. Нельзя купить бумагу до эмиссии.",
                }), 400
            if mat_date and purchase_date > mat_date:
                return jsonify({
                    "status": "error",
                    "message": f"Ошибка валидации: облигация погашена {mat_date}. Торги закрыты.",
                }), 400
    except Exception as exc:
        logger.warning("Date spec validation error for %s: %s", secid, exc)

    existing = BondPortfolio.query.filter_by(user_id=current_user.id, isin=isin, is_sold=False).first()
    existing_amount = existing.amount if existing else 0

    live_price = moex_data.get("price", float(req.buy_price))
    currency = moex_data.get("currency", "RUB")
    new_bond = BondPortfolio(
        user_id=current_user.id,
        isin=isin,
        secid=secid,
        name=bond_title,
        amount=int(req.amount),
        buy_price=float(req.buy_price),
        last_price=live_price,
        purchase_date=purchase_date,
        is_sold=False,
        currency=currency,
        notes=req.notes.strip() if req.notes else None,
    )
    db.session.add(new_bond)
    db.session.add(Transaction(
        user_id=current_user.id,
        isin=isin,
        name=bond_title,
        tx_type="buy",
        amount=int(req.amount),
        price=float(req.buy_price),
        currency=currency,
        tx_date=purchase_date,
    ))
    db.session.commit()
    _bust_user_cache(current_user.id)
    return jsonify({
        "status": "success",
        "message": f"Бумага {bond_title} успешно добавлена!",
        "duplicate_warning": existing_amount > 0,
        "existing_amount": existing_amount,
    }), 201


# ── Продать облигацию ─────────────────────────────────────────────────────────

@portfolio_bp.route("/api/sell_bond/<int:bond_id>", methods=["POST"])
@login_required
def sell_bond(bond_id: int):
    bond = db.session.get(BondPortfolio, bond_id)
    if bond is None:
        abort(404)
    if bond.user_id != current_user.id:
        abort(403)

    try:
        req = SellBondRequest.model_validate(request.get_json() or {})
    except ValidationError as e:
        first_error = e.errors()[0]["msg"].replace("Value error, ", "")
        return jsonify({"status": "error", "message": first_error}), 400

    if req.amount and req.amount > bond.amount:
        return jsonify({"status": "error", "message": f"Нельзя продать больше, чем есть в наличии ({bond.amount} шт.)."}), 400

    sell_price = (
        req.sell_price
        if req.sell_price
        else (float(bond.last_price) if bond.last_price else float(bond.buy_price))
    )

    if req.amount and req.amount < bond.amount:
        sell_qty = req.amount
        bond.amount -= sell_qty
        sold_bond = BondPortfolio(
            user_id=bond.user_id,
            isin=bond.isin,
            secid=bond.secid,
            name=bond.name,
            amount=sell_qty,
            buy_price=bond.buy_price,
            last_price=bond.last_price,
            purchase_date=bond.purchase_date,
            is_sold=True,
            sell_date=date.today(),
            sell_price=sell_price,
            broker_commission=req.broker_commission,
            notes=bond.notes,
        )
        db.session.add(sold_bond)
        message = f"Частично продано {sell_qty} шт. облигации {bond.name}."
    else:
        sell_qty = bond.amount
        bond.is_sold = True
        bond.sell_date = date.today()
        bond.sell_price = sell_price
        if req.broker_commission is not None:
            bond.broker_commission = req.broker_commission
        sold_bond = bond
        message = f"Облигация {bond.name} полностью продана и переведена в архив."

    db.session.add(Transaction(
        user_id=current_user.id,
        isin=bond.isin,
        name=bond.name,
        tx_type="sell",
        amount=sell_qty,
        price=sell_price,
        commission=req.broker_commission,
        tx_date=sold_bond.sell_date,
        currency=bond.currency or 'RUB',
    ))
    db.session.commit()
    _bust_user_cache(current_user.id)
    return jsonify({"status": "success", "message": message})



# ── График цены облигации ─────────────────────────────────────────────────────

@portfolio_bp.route("/api/bond_chart/<isin>", methods=["GET"])
@login_required
def get_bond_chart_data(isin: str):
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
        combined = [
            (lbl, p, n, y)
            for lbl, p, n, y in zip(labels, prices, nkd_hist, ytm_hist)
            if _parse_date(lbl) and _parse_date(lbl) >= cutoff
        ]
        if not combined:
            take = min(100, len(labels))
            combined = list(zip(labels[-take:], prices[-take:], nkd_hist[-take:], ytm_hist[-take:]))
    else:
        combined = list(zip(labels, prices, nkd_hist, ytm_hist))

    if len(combined) > MAX_CHART_POINTS:
        step = math.ceil(len(combined) / MAX_CHART_POINTS)
        combined = [combined[i] for i in range(0, len(combined), step)]

    if combined:
        labels_out, prices_out, nkd_out, ytm_out = zip(*combined)
        result = {"labels": list(labels_out), "data": list(prices_out), "nkd": list(nkd_out), "ytm": list(ytm_out)}
    else:
        result = {"labels": [], "data": [], "nkd": [], "ytm": []}

    ttl = CHART_RANGE_TTL if range_param != "all" else CHART_ALL_TTL
    try:
        cache.set(cache_key, result, timeout=ttl)
    except Exception:
        pass
    return jsonify(result)


def _parse_date(lbl: str) -> date | None:
    try:
        return datetime.strptime(lbl, "%Y-%m-%d").date()
    except Exception:
        return None


# ── Купонный календарь ────────────────────────────────────────────────────────

@portfolio_bp.route("/api/portfolio/calendar", methods=["GET"])
@login_required
def get_portfolio_calendar():
    active = BondPortfolio.query.filter_by(user_id=current_user.id, is_sold=False).all()
    events = []
    for bond in active:
        target = bond.secid or bond.isin
        for c in get_coupon_calendar_cached(target):
            events.append({
                "name": bond.name or bond.isin,
                "isin": bond.isin,
                "date": c["date"],
                "total_payout": round(c["value"] * bond.amount, 2),
            })
    events.sort(key=lambda x: x["date"])
    return jsonify(events[:10])


# ── Прогноз купонного дохода ──────────────────────────────────────────────────

@portfolio_bp.route("/api/portfolio/income", methods=["GET"])
@login_required
def portfolio_income():
    cache_key = f"portfolio_income:{current_user.id}"
    cached = cache.get(cache_key)
    if cached:
        return jsonify(cached)
    active = BondPortfolio.query.filter_by(user_id=current_user.id, is_sold=False).all()
    result = calc_coupon_income(active)
    cache.set(cache_key, result, timeout=INCOME_TTL)
    return jsonify(result)


# ── Распределение по эмитентам ────────────────────────────────────────────────

@portfolio_bp.route("/api/portfolio/allocation", methods=["GET"])
@login_required
def portfolio_allocation():
    active = BondPortfolio.query.filter_by(user_id=current_user.id, is_sold=False).all()
    slices = [
        {"name": b.name or b.isin, "value": round((float(b.last_price) if b.last_price else float(b.buy_price)) * b.amount, 2)}
        for b in active
    ]
    slices.sort(key=lambda x: x["value"], reverse=True)
    return jsonify(slices)


# ── Экспорт CSV ───────────────────────────────────────────────────────────────

@portfolio_bp.route("/api/portfolio/export", methods=["GET"])
@login_required
def export_portfolio_csv():
    active = BondPortfolio.query.filter_by(user_id=current_user.id, is_sold=False).all()
    si = StringIO()
    cw = csv.writer(si)
    cw.writerow(["Название бумаги", "ISIN код", "Количество (шт)", "Цена покупки (руб)", "Дата сделки"])
    for bond in active:
        cw.writerow([bond.name, bond.isin, bond.amount, bond.buy_price, bond.purchase_date])
    response = make_response('﻿' + si.getvalue())
    response.headers["Content-Disposition"] = "attachment; filename=portfolio_report.csv"
    response.headers["Content-Type"] = "text/csv; charset=utf-8-sig"
    return response


# ── Экспорт XLSX ──────────────────────────────────────────────────────────────

@portfolio_bp.route("/api/portfolio/export/xlsx", methods=["GET"])
@login_required
def export_portfolio_xlsx():
    active = BondPortfolio.query.filter_by(user_id=current_user.id, is_sold=False).all()
    sold = BondPortfolio.query.filter_by(user_id=current_user.id, is_sold=True).order_by(BondPortfolio.sell_date.desc()).all()

    wb = openpyxl.Workbook()
    header_font = Font(bold=True, color="FFFFFF")
    center = Alignment(horizontal="center")

    ws1 = wb.active
    ws1.title = "Портфель"
    headers1 = ["Название", "ISIN", "Кол-во", "Цена покупки (₽)", "Посл. цена (₽)", "P&L (₽)", "Дата покупки"]
    for col, h in enumerate(headers1, 1):
        cell = ws1.cell(row=1, column=col, value=h)
        cell.font = header_font
        cell.fill = PatternFill("solid", fgColor="1E7E34")
        cell.alignment = center
    for bond in active:
        last_p = float(bond.last_price) if bond.last_price else float(bond.buy_price)
        pnl = round((last_p - float(bond.buy_price)) * bond.amount, 2)
        ws1.append([bond.name, bond.isin, bond.amount, float(bond.buy_price), round(last_p, 2), pnl,
                    bond.purchase_date.strftime("%Y-%m-%d") if bond.purchase_date else ""])
    for col in ws1.columns:
        ws1.column_dimensions[col[0].column_letter].width = max(len(str(cell.value or "")) for cell in col) + 4

    ws2 = wb.create_sheet("История сделок")
    headers2 = ["Название", "ISIN", "Кол-во", "Цена покупки (₽)", "Цена продажи (₽)", "Комиссия (₽)", "P&L (₽)", "P&L %", "Дата продажи"]
    for col, h in enumerate(headers2, 1):
        cell = ws2.cell(row=1, column=col, value=h)
        cell.font = header_font
        cell.fill = PatternFill("solid", fgColor="155724")
        cell.alignment = center
    for bond in sold:
        buy_p = float(bond.buy_price)
        sell_p = float(bond.sell_price) if bond.sell_price else buy_p
        comm = float(bond.broker_commission) if bond.broker_commission else 0.0
        pnl = round((sell_p - buy_p) * bond.amount - comm, 2)
        pnl_pct = round(pnl / (buy_p * bond.amount) * 100, 2) if buy_p else 0.0
        ws2.append([bond.name, bond.isin, bond.amount, round(buy_p, 2), round(sell_p, 2), round(comm, 2), pnl, pnl_pct,
                    bond.sell_date.strftime("%Y-%m-%d") if bond.sell_date else ""])
    for col in ws2.columns:
        ws2.column_dimensions[col[0].column_letter].width = max(len(str(cell.value or "")) for cell in col) + 4

    buf = io.BytesIO()
    wb.save(buf)
    buf.seek(0)
    response = make_response(buf.read())
    response.headers["Content-Disposition"] = "attachment; filename=portfolio_report.xlsx"
    response.headers["Content-Type"] = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    return response


# ── Вотчлист ──────────────────────────────────────────────────────────────────

@portfolio_bp.route("/api/watchlist", methods=["GET"])
@login_required
def get_watchlist():
    items = Watchlist.query.filter_by(user_id=current_user.id).order_by(Watchlist.added_at.desc()).all()
    result = []
    for item in items:
        moex_data = get_bond_cached(item.isin) or {}
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
    entry = Watchlist(user_id=current_user.id, isin=isin, secid=moex_data.get("secid"), name=moex_data.get("name", isin))
    db.session.add(entry)
    db.session.commit()
    return jsonify({"status": "success", "message": f"{entry.name} добавлена в избранное."}), 201


@portfolio_bp.route("/api/watchlist/<isin>", methods=["DELETE"])
@login_required
def remove_from_watchlist(isin: str):
    entry = Watchlist.query.filter_by(user_id=current_user.id, isin=isin.upper()).first()
    if not entry:
        return jsonify({"status": "error", "message": "Не найдено."}), 404
    db.session.delete(entry)
    db.session.commit()
    return jsonify({"status": "success", "message": "Удалено из избранного."})


# ── Скринер ───────────────────────────────────────────────────────────────────

@portfolio_bp.route("/api/screener", methods=["GET"])
@login_required
def screener():
    try:
        req = ScreenerRequest(
            min_ytm=request.args.get("min_ytm") or None,
            max_ytm=request.args.get("max_ytm") or None,
            maturity_from=request.args.get("maturity_from") or None,
            maturity_to=request.args.get("maturity_to") or None,
            issuer_type=request.args.get("issuer_type") or None,
            min_duration=request.args.get("min_duration") or None,
            max_duration=request.args.get("max_duration") or None,
        )
    except ValidationError:
        return jsonify([])

    cache_key = f"screener:{req.min_ytm}:{req.max_ytm}:{req.maturity_from}:{req.maturity_to}"
    cached = cache.get(cache_key)
    if not cached:
        cached = get_screener_bonds(req.min_ytm, req.max_ytm, req.maturity_from, req.maturity_to, limit=200)
        cache.set(cache_key, cached, timeout=SCREENER_TTL)

    results = cached

    # Stage 4: post-filter by issuer type (client-side semantic)
    if req.issuer_type:
        itype = req.issuer_type.lower()
        def _matches_type(b: dict) -> bool:
            name = (b.get("name") or b.get("secid") or "").upper()
            if itype == "ofz":
                return "ОФЗ" in name or name.startswith("SU") or name.startswith("RU000A0")
            if itype == "muni":
                return any(k in name for k in ("МУН", "МУНИЦИПАЛ", "ОБЛИГАЦ", "РЕГИОН", "ОБЛАСТЬ", "КРАЙ", "ГОРОД"))
            if itype == "corp":
                return "ОФЗ" not in name and not any(
                    k in name for k in ("МУН", "РЕГИОН", "ОБЛАСТЬ", "КРАЙ", "ГОРОД")
                )
            return True
        results = [b for b in results if _matches_type(b)]

    # Stage 4: post-filter by approximate duration (years to maturity)
    if req.min_duration is not None or req.max_duration is not None:
        today_ord = date.today().toordinal()
        filtered = []
        for b in results:
            mat = b.get("maturity_date") or b.get("matdate") or ""
            if not mat:
                filtered.append(b)
                continue
            try:
                dur = (date.fromisoformat(mat[:10]).toordinal() - today_ord) / 365.25
            except ValueError:
                filtered.append(b)
                continue
            if req.min_duration is not None and dur < req.min_duration:
                continue
            if req.max_duration is not None and dur > req.max_duration:
                continue
            filtered.append(b)
        results = filtered

    return jsonify(results)


# ── Налоговый отчёт ───────────────────────────────────────────────────────────

@portfolio_bp.route("/api/portfolio/tax", methods=["GET"])
@login_required
def portfolio_tax():
    """Налоговый отчёт за год — сделки + купоны + НДФЛ (Stage 4 UI)."""
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
    active = BondPortfolio.query.filter_by(user_id=current_user.id, is_sold=False).all()
    summary = calc_tax_report(sold, active, year)

    # Build enriched response for Stage 4 Tax UI
    trades_list = []
    gross_profit = 0.0
    total_commission = 0.0
    for bond in sold:
        buy_p = float(bond.buy_price)
        sell_p = float(bond.sell_price) if bond.sell_price else buy_p
        comm = float(bond.broker_commission) if bond.broker_commission else 0.0
        pnl = (sell_p - buy_p) * bond.amount - comm
        gross_profit += pnl
        total_commission += comm
        trades_list.append({
            "id": bond.id,
            "name": bond.name or bond.isin,
            "isin": bond.isin,
            "amount": bond.amount,
            "buy_price": round(buy_p, 2),
            "sell_price": round(sell_p, 2),
            "commission": round(comm, 2),
            "pnl": round(pnl, 2),
            "sell_date": bond.sell_date.strftime("%Y-%m-%d") if bond.sell_date else None,
        })

    taxable_base = max(0.0, round(gross_profit, 2))
    tax_amount = round(taxable_base * 0.13, 2)

    return jsonify({
        **summary,
        "gross_profit": round(gross_profit, 2),
        "total_commission": round(total_commission, 2),
        "taxable_base": taxable_base,
        "tax_amount": tax_amount,
        "trades": trades_list,
    })


# ── Бенчмарк RGBI ─────────────────────────────────────────────────────────────

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
    cache.set(cache_key, result, timeout=BENCHMARK_TTL)
    return jsonify(result)


# ── Sharpe Ratio ─────────────────────────────────────────────────────────────

@portfolio_bp.route("/api/portfolio/sharpe", methods=["GET"])
@login_required
def portfolio_sharpe():
    """Коэффициент Шарпа по закрытым позициям портфеля (Stage 4)."""
    sold = BondPortfolio.query.filter_by(user_id=current_user.id, is_sold=True).all()
    result = calc_sharpe_ratio(sold)
    if result is None:
        return jsonify({
            "sharpe": None,
            "reason": f"Недостаточно данных (закрытых позиций: {len(sold)}, нужно ≥ 3)",
        })
    return jsonify(result)


# ── Сравнение двух облигаций ──────────────────────────────────────────────────

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
        days_map = {"day": 1, "week": 7, "month": 31}
        cutoff = datetime.utcnow().date() - timedelta(days=days_map[range_param])
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
        result = {"labels": list(lbl_out), "data": list(price_out), "name": moex_data.get("name", isin)}
    else:
        result = {"labels": [], "data": [], "name": moex_data.get("name", isin)}

    cache.set(cache_key, result, timeout=CHART_RANGE_TTL)
    return result


@portfolio_bp.route("/api/portfolio/compare", methods=["GET"])
@login_required
def compare_bonds():
    """Сравнение динамики цен двух облигаций (нормировано к 100).

    ?isin1=RU000A…&isin2=RU000A…&range=month|week|3m|year|all
    """
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


# ── Отчёт (print-to-PDF) ──────────────────────────────────────────────────────

@portfolio_bp.route("/portfolio/report")
@login_required
def portfolio_report_page():
    """Страница отчёта, оптимизированная для печати / сохранения как PDF."""
    active = BondPortfolio.query.filter_by(user_id=current_user.id, is_sold=False).all()
    bonds, total_val = build_portfolio_list(active)
    ytm = calc_portfolio_ytm(bonds, total_val)

    year = date.today().year
    sold_all = BondPortfolio.query.filter_by(user_id=current_user.id, is_sold=True).all()
    sold_year = [b for b in sold_all if b.sell_date and b.sell_date.year == year]
    tax = calc_tax_report(sold_year, active, year)

    sharpe_data = calc_sharpe_ratio(sold_all)

    return render_template(
        "pdf_report.html",
        bonds=bonds,
        total_value=round(total_val, 2),
        portfolio_ytm=ytm,
        tax=tax,
        sharpe=sharpe_data,
        year=year,
        username=current_user.username,
        generated_at=datetime.now().strftime("%d.%m.%Y %H:%M"),
        bond_count=len(active),
        sold_count=len(sold_all),
    )


# ── Dashboard: P&L chart data ─────────────────────────────────────────────────

@portfolio_bp.route("/api/dashboard/pnl_chart", methods=["GET"])
@login_required
def dashboard_pnl_chart():
    """Возвращает данные для area-чарта P&L на дашборде.

    ?period=7d   — последние 7 дней (дневные точки)
    ?period=30d  — последние 30 дней (дневные точки, по 5 подписей)
    ?period=ytd  — с начала года (месячные точки)
    """
    period = request.args.get("period", "30d")
    today = date.today()

    if period == "7d":
        start = today - timedelta(days=6)
        date_range = [start + timedelta(days=i) for i in range(7)]
        label_fmt = "%d.%m"
        # Показываем каждую дату
        tick_every = 1
    elif period == "ytd":
        # Месячные точки с 1 января до сегодня
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
        tick_every = 5  # подпись каждые 5 дней

    # Собираем P&L по дням из закрытых позиций (только DB, без MOEX)
    sold = BondPortfolio.query.filter_by(user_id=current_user.id, is_sold=True).all()
    daily_pnl: dict[date, float] = {}
    for bond in sold:
        if not bond.sell_date:
            continue
        sell_p = float(bond.sell_price) if bond.sell_price else float(bond.buy_price)
        commission = float(bond.broker_commission) if bond.broker_commission else 0.0
        pnl = (sell_p - float(bond.buy_price)) * bond.amount - commission
        daily_pnl[bond.sell_date] = daily_pnl.get(bond.sell_date, 0.0) + pnl

    # Строим кумулятивный P&L внутри периода (старт = 0 в начале периода)
    if period == "ytd":
        # Накапливаем помесячно
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
            # Показываем подпись не для каждой точки — chart.js разберётся
            labels.append(d.strftime(label_fmt) if i % tick_every == 0 or i == len(date_range) - 1 else "")
            data.append(round(running, 2))

    # Текущий нереализованный P&L (для отображения в тултипе / в заголовке)
    active = BondPortfolio.query.filter_by(user_id=current_user.id, is_sold=False).all()
    unrealized = round(sum(
        (float(b.last_price or b.buy_price) - float(b.buy_price)) * b.amount
        for b in active
    ), 2)

    return jsonify({"labels": labels, "data": data, "unrealized": unrealized, "period": period})


# ── Уведомления: ближайшие купоны ────────────────────────────────────────────

@portfolio_bp.route("/api/notifications/upcoming", methods=["GET"])
@login_required
def upcoming_notifications():
    """Возвращает купонные выплаты в ближайшие N дней (для колокольчика).

    ?days=7  — горизонт (по умолчанию 7)
    """
    try:
        days = max(1, min(int(request.args.get("days", 7)), 90))
    except (ValueError, TypeError):
        days = 7

    today = date.today()
    horizon = today + timedelta(days=days)

    active_bonds = BondPortfolio.query.filter_by(
        user_id=current_user.id, is_sold=False
    ).all()

    events: list[dict] = []
    for bond in active_bonds:
        try:
            coupons = get_coupon_calendar_cached(bond.isin) or []
        except Exception:
            continue
        for c in coupons:
            coupon_date_str = c.get("coupondate") or c.get("date") or ""
            if not coupon_date_str:
                continue
            try:
                coupon_date = date.fromisoformat(coupon_date_str[:10])
            except ValueError:
                continue
            if today <= coupon_date <= horizon:
                events.append({
                    "isin": bond.isin,
                    "name": bond.name or bond.isin,
                    "coupon_date": coupon_date_str[:10],
                    "coupon_value": c.get("value") or c.get("couponvalue"),
                    "amount": bond.amount,
                    "days_left": (coupon_date - today).days,
                })

    events.sort(key=lambda x: x["coupon_date"])
    return jsonify({"count": len(events), "events": events})


# ── Статистика (P&L по месяцам) ───────────────────────────────────────────────

@portfolio_bp.route("/api/portfolio_stats", methods=["GET"])
@login_required
def portfolio_stats():
    cache_key = f"portfolio_stats:{current_user.id}"
    cached = cache.get(cache_key)
    if cached:
        return jsonify(cached)

    closed = BondPortfolio.query.filter_by(user_id=current_user.id, is_sold=True).all()
    monthly = calc_monthly_profit(closed)
    sorted_months = sorted(monthly.keys())
    result = {
        "labels": sorted_months,
        "datasets": [{
            "label": "Чистая зафиксированная прибыль (₽)",
            "data": [monthly[m] for m in sorted_months],
            "backgroundColor": "rgba(40, 167, 69, 0.2)",
            "borderColor": "rgba(40, 167, 69, 1)",
            "borderWidth": 2,
            "fill": True,
        }],
    }
    cache.set(cache_key, result, timeout=STATS_TTL)
    return jsonify(result)


@portfolio_bp.route("/api/portfolio/import", methods=["POST"])
@login_required
def import_portfolio():
    """Импортирует сделки из файла брокерского отчета (CSV/Excel) или JSON-массива (Stage 10)."""
    import csv
    import io
    import openpyxl
    
    deals = []
    if "file" in request.files:
        f = request.files["file"]
        filename = f.filename.lower()
        if filename.endswith(".csv"):
            try:
                stream = io.StringIO(f.read().decode("utf-8-sig"), newline=None)
                reader = csv.DictReader(stream)
                for row in reader:
                    isin = row.get("ISIN") or row.get("isin") or row.get("Код бумаги") or row.get("Код")
                    amount_str = row.get("Amount") or row.get("amount") or row.get("Количество") or row.get("Кол-во")
                    price_str = row.get("Price") or row.get("price") or row.get("Цена") or row.get("Цена сделки")
                    date_str = row.get("Date") or row.get("date") or row.get("Дата") or row.get("Дата сделки")
                    notes = row.get("Notes") or row.get("notes") or row.get("Комментарий") or ""
                    
                    if not isin or not amount_str or not price_str:
                        continue
                    deals.append({
                        "isin": isin.strip().upper(),
                        "amount": amount_str,
                        "price": price_str,
                        "date": date_str,
                        "notes": notes
                    })
            except Exception as e:
                logger.error("Failed to parse CSV import report: %s", e)
                return jsonify({"status": "error", "message": f"Ошибка обработки CSV: {str(e)}"}), 400
        elif filename.endswith(".xlsx"):
            try:
                wb = openpyxl.load_workbook(io.BytesIO(f.read()), data_only=True)
                sheet = wb.active
                headers = [str(cell.value).strip().lower() if cell.value is not None else "" for cell in sheet[1]]
                
                def find_col_idx(names):
                    for name in names:
                        if name.lower() in headers:
                            return headers.index(name.lower()) + 1
                    return None
                
                isin_col = find_col_idx(["isin", "код бумаги", "isin код", "код"])
                amount_col = find_col_idx(["amount", "количество", "кол-во", "колво"])
                price_col = find_col_idx(["price", "цена", "цена сделки"])
                date_col = find_col_idx(["date", "дата", "дата сделки", "день"])
                notes_col = find_col_idx(["notes", "комментарий", "заметка", "примечание"])
                
                if isin_col and amount_col and price_col:
                    for row_idx in range(2, sheet.max_row + 1):
                        isin_val = sheet.cell(row=row_idx, column=isin_col).value
                        amount_val = sheet.cell(row=row_idx, column=amount_col).value
                        price_val = sheet.cell(row=row_idx, column=price_col).value
                        date_val = sheet.cell(row=row_idx, column=date_col).value if date_col else None
                        notes_val = sheet.cell(row=row_idx, column=notes_col).value if notes_col else None
                        
                        if isin_val is None or amount_val is None or price_val is None:
                            continue
                        
                        if isinstance(date_val, (datetime, date)):
                            date_str = date_val.strftime("%Y-%m-%d")
                        else:
                            date_str = str(date_val) if date_val else None
                            
                        deals.append({
                            "isin": str(isin_val).strip().upper(),
                            "amount": str(amount_val),
                            "price": str(price_val),
                            "date": date_str,
                            "notes": str(notes_val).strip() if notes_val else ""
                        })
            except Exception as e:
                logger.error("Failed to parse Excel import report: %s", e)
                return jsonify({"status": "error", "message": f"Ошибка обработки Excel: {str(e)}"}), 400
        else:
            return jsonify({"status": "error", "message": "Поддерживаются только форматы .csv и .xlsx"}), 400
    else:
        data = request.get_json() or {}
        deals = data.get("deals", [])

    if not deals:
        return jsonify({"status": "error", "message": "Не найдено ни одной сделки для импорта."}), 400

    imported_count = 0
    errors = []

    for deal in deals:
        isin = deal.get("isin", "").strip().upper()
        amount_str = deal.get("amount")
        price_str = deal.get("price")
        date_val = deal.get("date")
        notes = deal.get("notes", "")

        if not isin or not amount_str or not price_str:
            errors.append(f"Пропущено: неполные данные сделки для ISIN: {isin or 'не указан'}")
            continue

        try:
            amount = int(float(amount_str))
            price = float(price_str)
            if amount <= 0 or price <= 0:
                errors.append(f"Пропущено {isin}: некорректное кол-во ({amount}) или цена ({price})")
                continue
        except (ValueError, TypeError):
            errors.append(f"Пропущено {isin}: кол-во или цена не являются числами")
            continue

        purchase_date = date.today()
        if date_val:
            try:
                if isinstance(date_val, str):
                    date_val_clean = date_val.split(" ")[0].split("T")[0]
                    purchase_date = datetime.strptime(date_val_clean, "%Y-%m-%d").date()
                elif isinstance(date_val, (date, datetime)):
                    purchase_date = date_val
            except Exception:
                pass

        moex_data = get_moex_bond(isin)
        if not moex_data:
            errors.append(f"Пропущено {isin}: не найдена на Мосбирже")
            continue

        secid = moex_data["secid"]
        bond_title = moex_data.get("name", "Облигация")
        live_price = moex_data.get("price", price)
        currency = moex_data.get("currency", "RUB")

        new_bond = BondPortfolio(
            user_id=current_user.id,
            isin=isin,
            secid=secid,
            name=bond_title,
            amount=amount,
            buy_price=price,
            last_price=live_price,
            purchase_date=purchase_date,
            is_sold=False,
            currency=currency,
            notes=notes if notes else None,
        )
        db.session.add(new_bond)
        db.session.add(Transaction(
            user_id=current_user.id,
            isin=isin,
            name=bond_title,
            tx_type="buy",
            amount=amount,
            price=price,
            currency=currency,
            tx_date=purchase_date,
        ))
        imported_count += 1

    db.session.commit()
    _bust_user_cache(current_user.id)

    return jsonify({
        "status": "success",
        "message": f"Успешно импортировано {imported_count} сделок.",
        "imported_count": imported_count,
        "errors": errors
    }), 200
