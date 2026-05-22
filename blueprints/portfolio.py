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
    get_moex_bond, get_bond_history_all, get_coupon_calendar,
    search_bonds, _fetch_json, get_rgbi_history, get_screener_bonds,
)
from services.moex_service import get_bond_cached, get_bond_preview
from services.portfolio_service import (
    build_portfolio_list, calc_portfolio_ytm,
    build_trade_entry, calc_coupon_income,
    calc_monthly_profit, calc_tax_report,
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


# ── История сделок ────────────────────────────────────────────────────────────

@portfolio_bp.route("/api/portfolio/history", methods=["GET"])
@login_required
def portfolio_history():
    page = max(request.args.get("page", 1, type=int), 1)
    per_page = min(request.args.get("per_page", DEFAULT_PAGE_SIZE, type=int), MAX_PAGE_SIZE)
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

    total_count = query.count()
    closed = query.order_by(BondPortfolio.sell_date.desc()).offset((page - 1) * per_page).limit(per_page).all()
    return jsonify({
        "status": "success",
        "trades": [build_trade_entry(b) for b in closed],
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
    )
    db.session.add(new_bond)
    db.session.add(Transaction(
        user_id=current_user.id,
        isin=isin,
        name=bond_title,
        tx_type="buy",
        amount=int(req.amount),
        price=float(req.buy_price),
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

    bond.is_sold = True
    bond.sell_date = date.today()
    bond.sell_price = (
        req.sell_price
        if req.sell_price
        else (float(bond.last_price) if bond.last_price else float(bond.buy_price))
    )
    commission_val = req.broker_commission
    if commission_val is not None:
        bond.broker_commission = commission_val

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
    _bust_user_cache(current_user.id)
    return jsonify({"status": "success", "message": f"Облигация {bond.name} переведена в архив продаж."})


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
        for c in get_coupon_calendar(target):
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
                return any(k in name for k in ("МУН", "МУНИЦИN", "ОБЛИГАЦ", "РЕГИОН", "ОБЛАСТЬ", "КРАЙ", "ГОРОД"))
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
            coupons = get_coupon_calendar(bond.isin) or []
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
