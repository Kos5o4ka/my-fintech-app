import hashlib
import logging
import math
from datetime import datetime, date, timedelta
from typing import Optional

from flask import Blueprint, request, jsonify, render_template, abort, make_response
from flask_login import login_required, current_user
from pydantic import ValidationError

from app.extensions import db, cache
from app.models import BondPortfolio, Watchlist, Transaction, PriceAlert
from app.moex import (
    get_moex_bond,
    get_bond_history_all,
    get_bond_date_info,
    search_bonds,
    get_rgbi_history,
    get_screener_bonds,
)
from app.services.moex_service import (
    get_bond_cached,
    get_bond_preview,
    get_coupon_calendar_cached,
)
from app.services.portfolio_service import (
    build_portfolio_list,
    calc_portfolio_ytm,
    calc_coupon_income,
)
from app.schemas.portfolio import AddBondRequest, SellBondRequest, ScreenerRequest
from app.constants import (
    INCOME_TTL,
    CHART_RANGE_TTL,
    CHART_ALL_TTL,
    SCREENER_TTL,
    MAX_CHART_POINTS,
    STATS_TTL,
    SHARPE_TTL,
    TAX_TTL,
    DEFAULT_PAGE_SIZE,
    MAX_PAGE_SIZE,
    TIMEFRAME_DAYS,
)

logger = logging.getLogger(__name__)
portfolio_bp = Blueprint("portfolio", __name__)


def _etag(payload: dict) -> str:
    """Быстрый ETag из MD5 тела ответа (первые 16 символов)."""
    import json
    raw = json.dumps(payload, ensure_ascii=False, sort_keys=True)
    return hashlib.md5(raw.encode()).hexdigest()[:16]


def _bust_user_cache(user_id: int) -> None:
    """Инвалидирует кэши, зависящие от состава портфеля пользователя."""
    current_year = date.today().year
    for key in [
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


@portfolio_bp.route("/api/portfolio/<int:bond_id>", methods=["DELETE"])
@login_required
def delete_position(bond_id):
    """Физическое удаление лота из портфеля и соответствующей транзакции покупки."""
    bond = BondPortfolio.query.filter_by(id=bond_id, user_id=current_user.id).first()
    if not bond:
        return jsonify({"status": "error", "message": "Позиция не найдена"}), 404

    # Находим и удаляем соответствующую транзакцию покупки
    tx = Transaction.query.filter_by(
        user_id=current_user.id,
        isin=bond.isin,
        tx_type="buy",
        amount=bond.amount,
        price=bond.buy_price,
        tx_date=bond.purchase_date,
    ).first()
    if tx:
        db.session.delete(tx)

    db.session.delete(bond)
    db.session.commit()
    _bust_user_cache(current_user.id)
    return jsonify({"status": "success", "message": "Позиция успешно удалена"})


@portfolio_bp.route("/api/portfolio/reset", methods=["DELETE"])
@login_required
def reset_portfolio():
    """Полностью удаляет все позиции и транзакции пользователя."""
    data = request.get_json() or {}
    password = data.get("password")
    if not password or not current_user.check_password(password):
        return jsonify({"status": "error", "message": "Неверный пароль"}), 403

    Transaction.query.filter_by(user_id=current_user.id).delete()
    BondPortfolio.query.filter_by(user_id=current_user.id).delete()
    db.session.commit()
    _bust_user_cache(current_user.id)
    return jsonify({"status": "success", "message": "Портфель успешно сброшен"})


@portfolio_bp.route("/api/portfolio", methods=["GET"])
@login_required
def get_portfolio():
    page = max(request.args.get("page", 1, type=int), 1)
    per_page = min(
        request.args.get("per_page", DEFAULT_PAGE_SIZE, type=int), MAX_PAGE_SIZE
    )

    q = BondPortfolio.query.filter_by(user_id=current_user.id, is_sold=False)
    total_count = q.count()
    all_active = q.order_by(BondPortfolio.id).all()

    all_bonds, total_val = build_portfolio_list(all_active)

    # Сохраняем обновлённые last_price из MOEX в БД (build_portfolio_list пишет в ORM)
    try:
        db.session.commit()
    except Exception:
        db.session.rollback()

    ytm = calc_portfolio_ytm(all_bonds, total_val)

    # Средневзвешенная дюрация портфеля (веса по рублевой стоимости)
    valid_dur_bonds = [b for b in all_bonds if b.get("modified_duration") is not None and b["modified_duration"] > 0]
    total_valid_dur_val = sum(b["current_value_rub"] for b in valid_dur_bonds)
    if total_valid_dur_val > 0:
        avg_dur = sum(b["modified_duration"] * b["current_value_rub"] for b in valid_dur_bonds) / total_valid_dur_val
        portfolio_duration = round(avg_dur, 2)
    else:
        portfolio_duration = 0.0

    # Срезаем список облигаций для текущей страницы
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
def update_bond_notes(bond_id: int):
    """Обновляет заметку к позиции портфеля."""
    bond = BondPortfolio.query.filter_by(
        id=bond_id, user_id=current_user.id
    ).first_or_404()
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
        bond = BondPortfolio.query.filter_by(
            user_id=t.user_id,
            isin=t.isin,
            is_sold=True,
            amount=t.amount,
            sell_date=t.tx_date,
        ).first()
        if bond:
            buy_p = float(bond.buy_price)
            sell_p = float(bond.sell_price) if bond.sell_price else float(t.price)
            commission = (
                float(bond.broker_commission) if bond.broker_commission else commission
            )
            pnl = (sell_p - buy_p) * t.amount - commission
            pnl_pct = (pnl / (buy_p * t.amount) * 100) if buy_p else 0.0
            if bond.purchase_date:
                purchase_date = bond.purchase_date.strftime("%Y-%m-%d")
    else:
        purchase_date = t.tx_date.strftime("%Y-%m-%d")

    moex_data = get_bond_cached(t.isin) or {}
    facevalue = float(moex_data.get("facevalue") or 1000)

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
        "facevalue": facevalue,
    }


@portfolio_bp.route("/api/portfolio/history", methods=["GET"])
@login_required
def portfolio_history():
    page = max(request.args.get("page", 1, type=int), 1)
    per_page = min(
        request.args.get("per_page", DEFAULT_PAGE_SIZE, type=int), MAX_PAGE_SIZE
    )
    date_from_str = request.args.get("date_from", "").strip()
    date_to_str = request.args.get("date_to", "").strip()
    tx_type = request.args.get("tx_type")

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
                commission=0.0,
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
                    commission=b.broker_commission,
                )
                db.session.add(sell_tx)
        db.session.commit()

    if tx_type is None:
        tx_type = "sell"

    query = Transaction.query.filter_by(user_id=current_user.id)
    if tx_type in ("buy", "sell", "coupon"):
        query = query.filter_by(tx_type=tx_type)

    if date_from_str:
        try:
            query = query.filter(
                Transaction.tx_date
                >= datetime.strptime(date_from_str, "%Y-%m-%d").date()
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
    tx_list = (
        query.order_by(Transaction.tx_date.desc(), Transaction.id.desc())
        .offset((page - 1) * per_page)
        .limit(per_page)
        .all()
    )
    return jsonify(
        {
            "status": "success",
            "trades": [build_transaction_entry(t) for t in tx_list],
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

    existing = BondPortfolio.query.filter_by(
        user_id=current_user.id, isin=isin, is_sold=False
    ).first()
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
    db.session.add(
        Transaction(
            user_id=current_user.id,
            isin=isin,
            name=bond_title,
            tx_type="buy",
            amount=int(req.amount),
            price=float(req.buy_price),
            currency=currency,
            tx_date=purchase_date,
        )
    )
    db.session.commit()
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

    db.session.add(
        Transaction(
            user_id=current_user.id,
            isin=bond.isin,
            name=bond.name,
            tx_type="sell",
            amount=sell_qty,
            price=sell_price,
            commission=req.broker_commission,
            tx_date=sold_bond.sell_date,
            currency=bond.currency or "RUB",
        )
    )
    db.session.commit()
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
    active = BondPortfolio.query.filter_by(user_id=current_user.id, is_sold=False).all()
    events = []
    
    grouped = {}
    for bond in active:
        key = bond.secid or bond.isin
        if key not in grouped:
            grouped[key] = {"name": bond.name or bond.isin, "isin": bond.isin, "amount": 0}
        grouped[key]["amount"] += bond.amount
        
    for target, data in grouped.items():
        for c in get_coupon_calendar_cached(target):
            val = c.get("value")
            if val is None:
                val = 0.0
            events.append(
                {
                    "name": data["name"],
                    "isin": data["isin"],
                    "date": c["date"],
                    "total_payout": round(val * data["amount"], 2),
                }
            )
    events.sort(key=lambda x: x["date"])
    return jsonify(events[:10])


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


@portfolio_bp.route("/api/portfolio/allocation", methods=["GET"])
@login_required
def portfolio_allocation():
    active = BondPortfolio.query.filter_by(user_id=current_user.id, is_sold=False).all()
    slices = [
        {
            "name": b.name or b.isin,
            "value": round(
                (float(b.last_price) if b.last_price else float(b.buy_price))
                * b.amount,
                2,
            ),
        }
        for b in active
    ]
    slices.sort(key=lambda x: x["value"], reverse=True)
    return jsonify(slices)


@portfolio_bp.route("/api/watchlist", methods=["GET"])
@login_required
def get_watchlist():
    items = (
        Watchlist.query.filter_by(user_id=current_user.id)
        .order_by(Watchlist.added_at.desc())
        .all()
    )
    result = []
    for item in items:
        moex_data = get_bond_cached(item.isin) or {}
        result.append(
            {
                "isin": item.isin,
                "name": item.name or item.isin,
                "added_at": item.added_at.strftime("%Y-%m-%d"),
                "price": moex_data.get("price"),
                "ytm": moex_data.get("ytm"),
                "nkd": moex_data.get("nkd"),
            }
        )
    return jsonify(result)


@portfolio_bp.route("/api/watchlist", methods=["POST"])
@login_required
def add_to_watchlist():
    data = request.get_json() or {}
    isin = data.get("isin", "").upper().strip()
    if not isin:
        return jsonify({"status": "error", "message": "ISIN обязателен."}), 400
    if Watchlist.query.filter_by(user_id=current_user.id, isin=isin).first():
        return jsonify({"status": "error", "message": "Облигация уже в списке наблюдения."}), 400

    moex_data = get_moex_bond(isin)
    if not moex_data:
        return jsonify({"status": "error", "message": "Облигация не найдена на Московской Бирже."}), 404

    item = Watchlist(
        user_id=current_user.id,
        isin=isin,
        secid=moex_data["secid"],
        name=moex_data.get("name", isin),
    )
    db.session.add(item)
    db.session.commit()
    return jsonify({"status": "success", "message": "Облигация добавлена в список наблюдения."}), 201


@portfolio_bp.route("/api/watchlist/<isin>", methods=["DELETE"])
@login_required
def remove_from_watchlist(isin):
    isin = isin.upper().strip()
    item = Watchlist.query.filter_by(user_id=current_user.id, isin=isin).first()
    if not item:
        return jsonify({"status": "error", "message": "Элемент не найден в списке наблюдения."}), 404
    db.session.delete(item)
    db.session.commit()
    return jsonify({"status": "success", "message": "Удалено из списка наблюдения."})


@portfolio_bp.route("/api/screener", methods=["POST"])
@login_required
def screener():
    try:
        req = ScreenerRequest.model_validate(request.get_json() or {})
    except ValidationError as e:
        first_error = e.errors()[0]["msg"].replace("Value error, ", "")
        return jsonify({"status": "error", "message": first_error}), 400

    cache_key = f"screener:{hashlib.md5(request.data).hexdigest()}"
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
    """Возвращает купонные выплаты в ближайшие N дней (для колокольчика)."""
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
                events.append(
                    {
                        "isin": bond.isin,
                        "name": bond.name or bond.isin,
                        "coupon_date": coupon_date_str[:10],
                        "coupon_value": c.get("value") or c.get("couponvalue"),
                        "amount": bond.amount,
                        "days_left": (coupon_date - today).days,
                    }
                )

    events.sort(key=lambda x: x["coupon_date"])
    return jsonify({"count": len(events), "events": events})


@portfolio_bp.route("/api/portfolio/sparkline/<isin>", methods=["GET"])
@login_required
def get_portfolio_sparkline(isin: str):
    """Возвращает динамический SVG-микрографик цены облигации за 30 дней."""
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
        full = get_bond_history_all(moex_data["secid"], moex_data.get("facevalue", 1000))
        prices = full.get("data", [])[-30:]  # последние 30 точек
        
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
                f'</svg>'
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
def get_price_alerts():
    """Возвращает все ценовые алерты текущего пользователя."""
    alerts = PriceAlert.query.filter_by(user_id=current_user.id).order_by(PriceAlert.created_at.desc()).all()
    return jsonify([
        {
            "id": a.id,
            "isin": a.isin,
            "name": a.name or a.isin,
            "target_price": float(a.target_price),
            "condition": a.condition,
            "is_triggered": a.is_triggered,
            "created_at": a.created_at.strftime("%Y-%m-%d %H:%M:%S"),
        }
        for a in alerts
    ])


@portfolio_bp.route("/api/alerts", methods=["POST"])
@login_required
def create_price_alert():
    """Создаёт новый ценовой алерт."""
    data = request.get_json() or {}
    isin = str(data.get("isin", "")).strip().upper()
    target_price = data.get("target_price")
    condition = str(data.get("condition", "<=")).strip()
    
    if not isin or target_price is None or condition not in (">=", "<="):
        return jsonify({"status": "error", "message": "Некорректные параметры алерта."}), 400
        
    try:
        target_val = float(target_price)
    except (ValueError, TypeError):
        return jsonify({"status": "error", "message": "Цена должна быть числом."}), 400
        
    moex_data = get_moex_bond(isin)
    bond_name = moex_data.get("name", isin) if moex_data else isin
    
    new_alert = PriceAlert(
        user_id=current_user.id,
        isin=isin,
        name=bond_name,
        target_price=target_val,
        condition=condition,
        is_triggered=False,
    )
    db.session.add(new_alert)
    db.session.commit()
    
    return jsonify({
        "status": "success",
        "message": f"Алерт на цену {target_val} ₽ успешно установлен для {bond_name}.",
        "alert": {
            "id": new_alert.id,
            "isin": new_alert.isin,
            "name": new_alert.name,
            "target_price": target_val,
            "condition": new_alert.condition,
            "is_triggered": False,
        }
    }), 201


@portfolio_bp.route("/api/alerts/<int:alert_id>", methods=["DELETE"])
@login_required
def delete_price_alert(alert_id: int):
    """Удаляет ценовой алерт."""
    alert = PriceAlert.query.filter_by(id=alert_id, user_id=current_user.id).first()
    if not alert:
        return jsonify({"status": "error", "message": "Алерт не найден."}), 404
        
    db.session.delete(alert)
    db.session.commit()
    return jsonify({"status": "success", "message": "Алерт успешно удалён."})
