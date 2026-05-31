"""Blueprint портфеля — тонкий HTTP-слой: парсинг запроса → вызов сервиса → JSON."""

import hashlib
import logging
import math
from datetime import datetime, date, timedelta
from typing import Optional

from flask import Blueprint, request, jsonify, render_template, abort, make_response
from flask_login import login_required, current_user
from pydantic import ValidationError
from werkzeug.security import check_password_hash

from app.extensions import cache
from app.models import BondPortfolio
from app.moex import (
    get_moex_bond,
    get_bond_history_all,
    get_bond_date_info,
    search_bonds,
    get_screener_bonds,
)
from app.services.moex_service import (
    get_bond_preview,
)
from app.services.audit_service import log_action
from app.services.portfolio_service import (
    build_portfolio_list,
    calc_portfolio_ytm,
    calc_coupon_income,
    calc_coupons_received,
    get_active_bonds,
    get_sold_bonds_in_range,
    get_bond_by_id,
    delete_position,
    reset_portfolio,
    add_bond,
    sell_bond,
    update_bond_notes,
    flush_portfolio_prices,
    ensure_transactions_exist,
    query_transactions,
    get_allocation,
    get_coupon_calendar_events,
    get_upcoming_coupons,
    get_watchlist,
    add_to_watchlist,
    remove_from_watchlist,
    get_price_alerts,
    create_price_alert,
    delete_price_alert,
)
from app.schemas.portfolio import AddBondRequest, SellBondRequest, ScreenerRequest
from app.constants import (
    INCOME_TTL,
    CHART_RANGE_TTL,
    CHART_ALL_TTL,
    SCREENER_TTL,
    MAX_CHART_POINTS,
    DEFAULT_PAGE_SIZE,
    MAX_PAGE_SIZE,
    TIMEFRAME_DAYS,
)

logger = logging.getLogger(__name__)
portfolio_bp = Blueprint("portfolio", __name__)


def _etag(payload: dict) -> str:
    import json

    raw = json.dumps(payload, ensure_ascii=False, sort_keys=True)
    return hashlib.md5(raw.encode(), usedforsecurity=False).hexdigest()[:16]


def _bust_user_cache(user_id: int) -> None:
    current_year = date.today().year
    for key in [
        f"portfolio_full:{user_id}",
        f"portfolio_income:{user_id}",
        f"portfolio_stats:{user_id}",
        f"portfolio_calendar:{user_id}",
        f"portfolio_sharpe:{user_id}",
        f"portfolio_tax:{user_id}:{current_year}",
        f"portfolio_tax:{user_id}:{current_year - 1}",
    ]:
        try:
            cache.delete(key)
        except Exception:
            pass


@portfolio_bp.route("/portfolio")
@login_required
def portfolio_page() -> str:
    return render_template("portfolio.html", active_page="portfolio")


@portfolio_bp.route("/portfolio/report", methods=["GET"])
@login_required
def portfolio_report():
    from app.services.portfolio_service import build_portfolio_list, calc_portfolio_ytm
    from app.services.tax_service import calc_tax_report
    from app.services.risk_service import calc_sharpe_ratio
    
    active_bonds = BondPortfolio.query.filter_by(user_id=current_user.id, is_sold=False).all()
    all_bonds, total_val = build_portfolio_list(active_bonds)
    
    # Add T-Invest synced bonds
    from app.models import BrokerAccount, BrokerPosition
    accounts = BrokerAccount.query.filter_by(user_id=current_user.id).all()
    tinvest_total = 0.0
    for acc in accounts:
        positions = BrokerPosition.query.filter_by(account_id=acc.id).all()
        for p in positions:
            cost = float(p.average_price * p.quantity)
            cur_val = float(p.current_price * p.quantity)
            pnl = cur_val - cost
            pnl_pct = (pnl / cost * 100) if cost > 0 else 0
            
            # Use average_price as ruble value, calculate approximate percentage for buy_price
            fv = 1000.0
            
            all_bonds.append({
                "isin": p.ticker or p.figi,
                "name": p.name or p.ticker or p.figi,
                "amount": float(p.quantity),
                "buy_price": (float(p.average_price) / fv) * 100, # Mock %
                "buy_price_rub_calc": float(p.average_price),
                "last_price": (float(p.current_price) / fv) * 100, # Mock %
                "last_price_rub": float(p.current_price),
                "current_value": cur_val,
                "current_value_rub": cur_val,
                "facevalue": fv,
                "nkd": 0.0,
                "ytm": float(p.expected_yield or 0.0),
                "pnl": pnl,
                "pnl_pct": pnl_pct,
                "currency": p.currency,
                "is_tinvest": True
            })
            tinvest_total += cur_val
            
    total_val += tinvest_total
    
    ytm = calc_portfolio_ytm(all_bonds, total_val)
    
    sold_bonds = BondPortfolio.query.filter_by(user_id=current_user.id, is_sold=True).all()
    sold_count = len(sold_bonds)
    
    year = datetime.now().year
    tax = calc_tax_report(sold_bonds, active_bonds, year)
    sharpe = calc_sharpe_ratio(sold_bonds)
    
    generated_at = datetime.now().strftime("%Y-%m-%d %H:%M")
    
    return render_template(
        "pdf_report.html",
        bonds=all_bonds,
        total_value=total_val,
        portfolio_ytm=ytm,
        bond_count=len(all_bonds),
        sold_count=sold_count,
        tax=tax,
        sharpe=sharpe,
        year=year,
        generated_at=generated_at,
        username=current_user.username
    )


@portfolio_bp.route("/api/portfolio/<int:bond_id>", methods=["DELETE"])
@login_required
def delete_position_route(bond_id):
    bond = get_bond_by_id(bond_id)
    bond_isin = bond.isin if bond else str(bond_id)
    result = delete_position(bond_id, current_user.id)
    if result is None:
        return jsonify({"status": "error", "message": "Позиция не найдена"}), 404
    log_action("bond_delete", user_id=current_user.id, category="portfolio", details=f"Удалена позиция: {bond_isin}")
    _bust_user_cache(current_user.id)
    return jsonify({"status": "success", "message": "Позиция успешно удалена"})


@portfolio_bp.route("/api/portfolio/reset", methods=["DELETE"])
@login_required
def reset_portfolio_route():
    data = request.get_json() or {}
    password = data.get("password")
    if not password or not check_password_hash(current_user.password_hash, password):
        return jsonify({"status": "error", "message": "Неверный пароль"}), 403

    reset_portfolio(current_user.id)
    log_action("portfolio_reset", user_id=current_user.id, category="portfolio", details="Сброс портфеля и истории сделок")
    _bust_user_cache(current_user.id)
    return jsonify({"status": "success", "message": "Портфель успешно сброшен"})


@portfolio_bp.route("/api/portfolio/tinkoff_sync", methods=["POST"])
@login_required
def tinkoff_sync_route():
    from pydantic import ValidationError
    from app.schemas.tinkoff import TinkoffSyncIn
    from app.services.tinkoff_service import sync_tinkoff_portfolio

    data = request.get_json(silent=True) or {}
    try:
        payload = TinkoffSyncIn(**data)
    except ValidationError as exc:
        return jsonify({"status": "error", "message": exc.errors()[0]["msg"]}), 400

    result = sync_tinkoff_portfolio(
        current_user, account_id=payload.account_id, sandbox=payload.sandbox
    )
    if result["status"] == "success":
        log_action(
            "import_ok",
            user_id=current_user.id,
            category="portfolio",
            details={"source": "tinkoff", **result.get("summary", {})},
        )
        _bust_user_cache(current_user.id)
        return jsonify(result)

    log_action(
        "import_fail",
        user_id=current_user.id,
        category="portfolio",
        details={"source": "tinkoff", "error": result.get("message")},
    )
    code = 401 if result.get("code") == "auth" else 400
    return jsonify(result), code


@portfolio_bp.route("/api/portfolio", methods=["GET"])
@login_required
def get_portfolio():
    page = max(request.args.get("page", 1, type=int), 1)
    per_page = min(
        request.args.get("per_page", DEFAULT_PAGE_SIZE, type=int), MAX_PAGE_SIZE
    )

    # Полный список позиций кэшируем единожды на пользователя (TTL 5 мин).
    # Пагинация и ETag считаются поверх кэша, поэтому ключ не зависит от page.
    cache_key = f"portfolio_full:{current_user.id}"
    cached = cache.get(cache_key)
    if cached is not None:
        all_bonds = cached["bonds"]
        total_val = cached["total_value"]
        ytm = cached["portfolio_ytm"]
        portfolio_duration = cached["portfolio_duration"]
    else:
        active = get_active_bonds(current_user.id)
        all_bonds, total_val = build_portfolio_list(active)
        flush_portfolio_prices()

        ytm = calc_portfolio_ytm(all_bonds, total_val)

        valid_dur_bonds = [
            b
            for b in all_bonds
            if b.get("modified_duration") is not None and b["modified_duration"] > 0
        ]
        total_valid_dur_val = sum(b["current_value_rub"] for b in valid_dur_bonds)
        if total_valid_dur_val > 0:
            avg_dur = (
                sum(
                    b["modified_duration"] * b["current_value_rub"]
                    for b in valid_dur_bonds
                )
                / total_valid_dur_val
            )
            portfolio_duration = round(avg_dur, 2)
        else:
            portfolio_duration = 0.0

        cache.set(
            cache_key,
            {
                "bonds": all_bonds,
                "total_value": total_val,
                "portfolio_ytm": ytm,
                "portfolio_duration": portfolio_duration,
            },
            timeout=300,
        )

    total_count = len(all_bonds)
    paginated_bonds = all_bonds[(page - 1) * per_page : page * per_page]

    payload = {
        "status": "success",
        "total_value": round(total_val, 2),
        "portfolio_ytm": ytm,
        "portfolio_duration": portfolio_duration,
        "bonds": paginated_bonds,
        "pagination": {
            "page": page,
            "per_page": per_page,
            "total": total_count,
            "pages": math.ceil(total_count / per_page) if per_page else 1,
        },
    }

    tag = _etag(payload)
    if request.headers.get("If-None-Match") == tag:
        return "", 304

    resp = make_response(jsonify(payload))
    resp.headers["ETag"] = tag
    resp.headers["Cache-Control"] = "private, max-age=60"
    return resp


@portfolio_bp.route("/api/portfolio/<int:bond_id>/notes", methods=["PATCH"])
@login_required
def update_bond_notes_route(bond_id: int):
    data = request.get_json() or {}
    raw = (data.get("notes") or "").strip()
    notes = update_bond_notes(bond_id, current_user.id, raw)
    return jsonify({"status": "success", "notes": notes})


@portfolio_bp.route("/api/portfolio/history", methods=["GET"])
@login_required
def portfolio_history():
    page = max(request.args.get("page", 1, type=int), 1)
    per_page = min(
        request.args.get("per_page", DEFAULT_PAGE_SIZE, type=int), MAX_PAGE_SIZE
    )
    date_from_str = request.args.get("date_from", "").strip()
    date_to_str = request.args.get("date_to", "").strip()
    tx_type = request.args.get("tx_type", "sell")

    ensure_transactions_exist(current_user.id)

    date_from: Optional[date] = None
    date_to: Optional[date] = None
    if date_from_str:
        try:
            date_from = datetime.strptime(date_from_str, "%Y-%m-%d").date()
        except ValueError:
            pass
    if date_to_str:
        try:
            date_to = datetime.strptime(date_to_str, "%Y-%m-%d").date()
        except ValueError:
            pass

    trades, total_count = query_transactions(
        current_user.id, tx_type, date_from, date_to, page, per_page
    )
    return jsonify(
        {
            "status": "success",
            "trades": trades,
            "pagination": {
                "page": page,
                "per_page": per_page,
                "total": total_count,
                "pages": math.ceil(total_count / per_page) if per_page else 1,
            },
        }
    )


@portfolio_bp.route("/api/search_bond", methods=["GET"])
@login_required
def search_bond():
    q = request.args.get("q", "").strip()
    if len(q) < 2:
        return jsonify([])
    return jsonify(search_bonds(q, limit=8))


@portfolio_bp.route("/api/bond_preview/<isin>", methods=["GET"])
@login_required
def bond_preview_route(isin: str):
    isin = isin.upper().strip()
    result = get_bond_preview(isin)
    if not result:
        return jsonify(
            {"status": "error", "message": "Облигация не найдена на Московской Бирже"}
        ), 404
    return jsonify(result)


@portfolio_bp.route("/api/add_bond", methods=["POST"])
@login_required
def add_bond_route():
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
        return jsonify(
            {
                "status": "error",
                "message": f"Облигация {isin} не найдена на Московской Бирже.",
            }
        ), 404

    secid = moex_data["secid"]
    bond_title = moex_data.get("name", "Облигация")

    try:
        date_info = get_bond_date_info(secid)
        issue_date: Optional[date] = None
        mat_date: Optional[date] = None
        if date_info.get("issue_date"):
            issue_date = datetime.strptime(date_info["issue_date"], "%Y-%m-%d").date()
        if date_info.get("mat_date"):
            mat_date = datetime.strptime(date_info["mat_date"], "%Y-%m-%d").date()
        if issue_date and purchase_date < issue_date:
            return jsonify(
                {
                    "status": "error",
                    "message": f"Ошибка валидации: облигация выпущена {issue_date}. Нельзя купить бумагу до эмиссии.",
                }
            ), 400
        if mat_date and purchase_date > mat_date:
            return jsonify(
                {
                    "status": "error",
                    "message": f"Ошибка валидации: облигация погашена {mat_date}. Торги закрыты.",
                }
            ), 400
    except Exception as exc:
        logger.warning("Date spec validation error for %s: %s", secid, exc)

    live_price = moex_data.get("price", float(req.buy_price))
    currency = moex_data.get("currency", "RUB")
    new_bond, existing_amount = add_bond(
        user_id=current_user.id,
        isin=isin,
        secid=secid,
        name=bond_title,
        amount=int(req.amount),
        buy_price=float(req.buy_price),
        last_price=live_price,
        purchase_date=purchase_date,
        currency=currency,
        notes=req.notes.strip() if req.notes else None,
    )
    log_action("bond_add", user_id=current_user.id, category="portfolio", details=f"Добавлена бумага {bond_title} ({isin})")
    _bust_user_cache(current_user.id)
    return jsonify(
        {
            "status": "success",
            "message": f"Бумага {bond_title} успешно добавлена!",
            "duplicate_warning": existing_amount > 0,
            "existing_amount": existing_amount,
        }
    ), 201


@portfolio_bp.route("/api/sell_bond/<int:bond_id>", methods=["POST"])
@login_required
def sell_bond_route(bond_id: int):
    bond = get_bond_by_id(bond_id)
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
        return jsonify(
            {
                "status": "error",
                "message": f"Нельзя продать больше, чем есть в наличии ({bond.amount} шт.).",
            }
        ), 400

    sell_price = (
        req.sell_price
        if req.sell_price
        else (float(bond.last_price) if bond.last_price else float(bond.buy_price))
    )
    sell_qty = req.amount if req.amount else bond.amount

    message = sell_bond(
        bond=bond,
        sell_price=sell_price,
        sell_qty=sell_qty,
        broker_commission=req.broker_commission,
        user_id=current_user.id,
    )
    log_action("bond_sell", user_id=current_user.id, category="portfolio", details=f"Продано {sell_qty} шт. бумаги {bond.isin}")
    _bust_user_cache(current_user.id)
    return jsonify({"status": "success", "message": message})


def _parse_date(lbl: str) -> date | None:
    try:
        return datetime.strptime(lbl, "%Y-%m-%d").date()
    except Exception:
        return None


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
        cutoff = datetime.utcnow().date() - timedelta(days=TIMEFRAME_DAYS[range_param])
        combined = [
            (lbl, p, n, y)
            for lbl, p, n, y in zip(labels, prices, nkd_hist, ytm_hist)
            if _parse_date(lbl) and _parse_date(lbl) >= cutoff
        ]
        if not combined:
            take = min(100, len(labels))
            combined = list(
                zip(labels[-take:], prices[-take:], nkd_hist[-take:], ytm_hist[-take:])
            )
    else:
        combined = list(zip(labels, prices, nkd_hist, ytm_hist))

    if len(combined) > MAX_CHART_POINTS:
        step = math.ceil(len(combined) / MAX_CHART_POINTS)
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

    ttl = CHART_RANGE_TTL if range_param != "all" else CHART_ALL_TTL
    try:
        cache.set(cache_key, result, timeout=ttl)
    except Exception:
        pass
    return jsonify(result)


@portfolio_bp.route("/api/portfolio/calendar", methods=["GET"])
@login_required
def get_portfolio_calendar():
    # limit: сколько максимум выплат отдать (default 10 для обратной совместимости
    # с dashboard, аналитика передаёт 500). days: ограничение по горизонту в днях.
    try:
        limit = max(1, min(int(request.args.get("limit", 10)), 1000))
    except (TypeError, ValueError):
        limit = 10
    days_raw = request.args.get("days")
    days: Optional[int] = None
    if days_raw:
        try:
            d = int(days_raw)
            days = d if d > 0 else None
        except (TypeError, ValueError):
            days = None
    return jsonify(get_coupon_calendar_events(current_user.id, limit=limit, days=days))


@portfolio_bp.route("/api/portfolio/income", methods=["GET"])
@login_required
def portfolio_income():
    cache_key = f"portfolio_income:{current_user.id}"
    cached = cache.get(cache_key)
    if cached:
        return jsonify(cached)
    active = get_active_bonds(current_user.id)
    result = calc_coupon_income(active)
    cache.set(cache_key, result, timeout=INCOME_TTL)
    return jsonify(result)


_YIELD_PERIOD_DAYS = {
    "1w": 7,
    "1m": 30,
    "3m": 90,
    "6m": 180,
    "1y": 365,
    "all": None,
}


@portfolio_bp.route("/api/portfolio/coupons_received", methods=["GET"])
@login_required
def portfolio_coupons_received():
    """Полученные купоны по активным позициям. ?period=1w|1m|3m|6m|1y|all"""
    period = request.args.get("period", "all")
    days = _YIELD_PERIOD_DAYS.get(period)
    period_from = (date.today() - timedelta(days=days)) if days else None
    cache_key = f"portfolio_coupons_received:{current_user.id}:{period}"
    cached = cache.get(cache_key)
    if cached:
        return jsonify(cached)
    active = get_active_bonds(current_user.id)
    result = calc_coupons_received(active, period_from=period_from)
    result["period"] = period
    cache.set(cache_key, result, timeout=1800)
    return jsonify(result)


@portfolio_bp.route("/api/portfolio/yield", methods=["GET"])
@login_required
def portfolio_yield():
    """Доходность портфеля за период.

    ?period=1w|1m|3m|6m|1y|all
    ?mode=all   — купоны + realized PnL (закрытые сделки в периоде) + unrealized
    ?mode=coupons — только полученные купоны за период
    """
    period = request.args.get("period", "1m")
    mode = request.args.get("mode", "all")
    days = _YIELD_PERIOD_DAYS.get(period)
    today = date.today()
    period_from = (today - timedelta(days=days)) if days else None

    active = get_active_bonds(current_user.id)
    coupons_dict = calc_coupons_received(active, period_from=period_from)
    coupons = coupons_dict["total"]

    if mode == "coupons":
        return jsonify({
            "period": period,
            "mode": mode,
            "coupons": coupons,
            "realized_pnl": 0.0,
            "unrealized_pnl": 0.0,
            "total": coupons,
        })

    # mode=all: realized PnL по закрытым в периоде + текущий unrealized
    realized = 0.0
    try:
        if period_from is not None:
            sold = get_sold_bonds_in_range(current_user.id, period_from, today)
        else:
            from app.services.portfolio_service import get_sold_bonds
            sold = get_sold_bonds(current_user.id)
        for b in sold:
            buy_p = float(b.buy_price)
            sell_p = float(b.sell_price) if b.sell_price else buy_p
            comm = float(b.broker_commission) if b.broker_commission else 0.0
            realized += (sell_p - buy_p) * b.amount - comm
    except Exception as exc:
        logger.warning("realized calc failed in yield endpoint: %s", exc)

    # Текущий unrealized PnL — сумма pnl по активным позициям (использует кэш).
    pf_key = f"portfolio_full:{current_user.id}"
    pf_cached = cache.get(pf_key)
    unrealized = 0.0
    if pf_cached and pf_cached.get("bonds"):
        for b in pf_cached["bonds"]:
            try:
                unrealized += float(b.get("pnl_rub") or b.get("pnl") or 0.0)
            except (TypeError, ValueError):
                pass

    return jsonify({
        "period": period,
        "mode": mode,
        "coupons": round(coupons, 2),
        "realized_pnl": round(realized, 2),
        "unrealized_pnl": round(unrealized, 2),
        "total": round(coupons + realized + unrealized, 2),
    })


@portfolio_bp.route("/api/portfolio/allocation", methods=["GET"])
@login_required
def portfolio_allocation():
    return jsonify(get_allocation(current_user.id))


@portfolio_bp.route("/api/dashboard/full", methods=["GET"])
@login_required
def dashboard_full():
    """Объединённый эндпоинт для главной страницы: portfolio + income + calendar + realized PnL.

    Заменяет 4 параллельных fetch на один. Использует уже существующие кэши
    (portfolio_full, portfolio_income, portfolio_calendar) и переиспользует
    данные между шагами (build_portfolio_list вызывается один раз).
    """
    user_id = current_user.id

    # 1) Portfolio (из Redis-кэша или пересчёт через build_portfolio_list)
    pf_key = f"portfolio_full:{user_id}"
    pf_cached = cache.get(pf_key)
    if pf_cached is not None:
        all_bonds = pf_cached["bonds"]
        total_val = pf_cached["total_value"]
        ytm = pf_cached["portfolio_ytm"]
        portfolio_duration = pf_cached["portfolio_duration"]
    else:
        active = get_active_bonds(user_id)
        all_bonds, total_val = build_portfolio_list(active)
        flush_portfolio_prices()
        ytm = calc_portfolio_ytm(all_bonds, total_val)
        valid_dur_bonds = [
            b for b in all_bonds
            if b.get("modified_duration") and b["modified_duration"] > 0
        ]
        total_valid_dur_val = sum(b["current_value_rub"] for b in valid_dur_bonds)
        if total_valid_dur_val > 0:
            avg_dur = sum(
                b["modified_duration"] * b["current_value_rub"] for b in valid_dur_bonds
            ) / total_valid_dur_val
            portfolio_duration = round(avg_dur, 2)
        else:
            portfolio_duration = 0.0
        cache.set(
            pf_key,
            {
                "bonds": all_bonds,
                "total_value": total_val,
                "portfolio_ytm": ytm,
                "portfolio_duration": portfolio_duration,
            },
            timeout=300,
        )

    # 2) Income (Redis-кэш 30 мин)
    inc_key = f"portfolio_income:{user_id}"
    income = cache.get(inc_key)
    if income is None:
        active = get_active_bonds(user_id)
        income = calc_coupon_income(active)
        cache.set(inc_key, income, timeout=INCOME_TTL)

    # 3) Coupon calendar — лёгкий вызов, использует свой in-process кэш.
    coupons = get_coupon_calendar_events(user_id)

    # 4) Realized PnL из истории закрытых сделок (за всё время).
    realized_pnl = 0.0
    try:
        sold = BondPortfolio.query.filter_by(user_id=user_id, is_sold=True).all()
        for b in sold:
            buy_p = float(b.buy_price)
            sell_p = float(b.sell_price) if b.sell_price else buy_p
            comm = float(b.broker_commission) if b.broker_commission else 0.0
            realized_pnl += (sell_p - buy_p) * b.amount - comm
    except Exception as exc:
        logger.warning("realized_pnl calc failed: %s", exc)

    return jsonify({
        "status": "success",
        "portfolio": {
            "bonds": all_bonds,
            "total_value": round(total_val, 2),
            "portfolio_ytm": ytm,
            "portfolio_duration": portfolio_duration,
        },
        "income": income,
        "coupons": coupons,
        "realized_pnl": round(realized_pnl, 2),
    })


@portfolio_bp.route("/api/watchlist", methods=["GET"])
@login_required
def get_watchlist_route():
    return jsonify(get_watchlist(current_user.id))


@portfolio_bp.route("/api/watchlist", methods=["POST"])
@login_required
def add_to_watchlist_route():
    data = request.get_json() or {}
    isin = data.get("isin", "").upper().strip()
    if not isin:
        return jsonify({"status": "error", "message": "ISIN обязателен."}), 400

    moex_data = get_moex_bond(isin)
    if not moex_data:
        return jsonify(
            {"status": "error", "message": "Облигация не найдена на Московской Бирже."}
        ), 404

    error = add_to_watchlist(
        current_user.id, isin, moex_data["secid"], moex_data.get("name", isin)
    )
    if error:
        return jsonify({"status": "error", "message": error}), 400
    return jsonify(
        {"status": "success", "message": "Облигация добавлена в список наблюдения."}
    ), 201


@portfolio_bp.route("/api/watchlist/<isin>", methods=["DELETE"])
@login_required
def remove_from_watchlist_route(isin):
    isin = isin.upper().strip()
    if not remove_from_watchlist(current_user.id, isin):
        return jsonify(
            {"status": "error", "message": "Элемент не найден в списке наблюдения."}
        ), 404
    return jsonify({"status": "success", "message": "Удалено из списка наблюдения."})


@portfolio_bp.route("/api/screener", methods=["POST"])
@login_required
def screener():
    try:
        req = ScreenerRequest.model_validate(request.get_json() or {})
    except ValidationError as e:
        first_error = e.errors()[0]["msg"].replace("Value error, ", "")
        return jsonify({"status": "error", "message": first_error}), 400

    cache_key = (
        f"screener:{hashlib.md5(request.data, usedforsecurity=False).hexdigest()}"
    )
    cached = cache.get(cache_key)
    if cached:
        return jsonify(cached)

    results = get_screener_bonds(
        min_ytm=req.min_ytm,
        max_ytm=req.max_ytm,
        maturity_from=req.maturity_from,
        maturity_to=req.maturity_to,
    )

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

    cache.set(cache_key, results, timeout=SCREENER_TTL)
    return jsonify(results)


@portfolio_bp.route("/api/notifications/upcoming", methods=["GET"])
@login_required
def upcoming_notifications():
    try:
        days = max(1, min(int(request.args.get("days", 7)), 90))
    except (ValueError, TypeError):
        days = 7
    events = get_upcoming_coupons(current_user.id, days)
    return jsonify({"count": len(events), "events": events})


@portfolio_bp.route("/api/portfolio/sparkline/<isin>", methods=["GET"])
@login_required
def get_portfolio_sparkline(isin: str):
    isin = isin.upper().strip()
    cache_key = f"sparkline:{isin}"

    try:
        cached_svg = cache.get(cache_key)
        if cached_svg:
            resp = make_response(cached_svg)
            resp.headers["Content-Type"] = "image/svg+xml"
            resp.headers["Cache-Control"] = "public, max-age=86400"
            return resp
    except Exception:
        pass

    moex_data = get_moex_bond(isin)
    if not moex_data:
        svg = '<svg width="80" height="20" xmlns="http://www.w3.org/2000/svg"><line x1="0" y1="10" x2="80" y2="10" stroke="#94a3b8" stroke-width="1.5"/></svg>'
    else:
        full = get_bond_history_all(
            moex_data["secid"], moex_data.get("facevalue", 1000)
        )
        prices = full.get("data", [])[-30:]

        if not prices or len(prices) < 2:
            svg = '<svg width="80" height="20" xmlns="http://www.w3.org/2000/svg"><line x1="0" y1="10" x2="80" y2="10" stroke="#94a3b8" stroke-width="1.5"/></svg>'
        else:
            min_p, max_p = min(prices), max(prices)
            rng = max_p - min_p if max_p != min_p else 1.0
            points = []
            w, h = 80, 20
            for i, p in enumerate(prices):
                x = (i / (len(prices) - 1)) * w
                y = h - ((p - min_p) / rng) * h
                points.append(f"{x:.1f},{y:.1f}")
            points_str = " ".join(points)
            color = "#10b981" if prices[-1] >= prices[0] else "#ef4444"
            svg = (
                f'<svg width="{w}" height="{h}" viewBox="0 0 {w} {h}" xmlns="http://www.w3.org/2000/svg">'
                f'<polyline fill="none" stroke="{color}" stroke-width="1.5" points="{points_str}"/>'
                f"</svg>"
            )

    try:
        cache.set(cache_key, svg, timeout=86400)
    except Exception:
        pass

    resp = make_response(svg)
    resp.headers["Content-Type"] = "image/svg+xml"
    resp.headers["Cache-Control"] = "public, max-age=86400"
    return resp


@portfolio_bp.route("/api/alerts", methods=["GET"])
@login_required
def get_price_alerts_route():
    return jsonify(get_price_alerts(current_user.id))


@portfolio_bp.route("/api/alerts", methods=["POST"])
@login_required
def create_price_alert_route():
    data = request.get_json() or {}
    isin = str(data.get("isin", "")).strip().upper()
    target_price = data.get("target_price")
    condition = str(data.get("condition", "<=")).strip()

    if not isin or target_price is None or condition not in (">=", "<="):
        return jsonify(
            {"status": "error", "message": "Некорректные параметры алерта."}
        ), 400

    try:
        target_val = float(target_price)
    except (ValueError, TypeError):
        return jsonify({"status": "error", "message": "Цена должна быть числом."}), 400

    moex_data = get_moex_bond(isin)
    bond_name = moex_data.get("name", isin) if moex_data else isin

    alert = create_price_alert(current_user.id, isin, bond_name, target_val, condition)
    return jsonify(
        {
            "status": "success",
            "message": f"Алерт на цену {target_val} ₽ успешно установлен для {bond_name}.",
            "alert": alert,
        }
    ), 201


@portfolio_bp.route("/api/alerts/<int:alert_id>", methods=["DELETE"])
@login_required
def delete_price_alert_route(alert_id: int):
    if not delete_price_alert(alert_id, current_user.id):
        return jsonify({"status": "error", "message": "Алерт не найден."}), 404
    return jsonify({"status": "success", "message": "Алерт успешно удалён."})
