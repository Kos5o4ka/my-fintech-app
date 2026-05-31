"""Сервис портфеля — P&L, доходность, купонный доход, налоги, Sharpe Ratio, CRUD."""

import logging
import math
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, date
from typing import Optional

from app.extensions import db
from app.models import BondPortfolio, Transaction, Watchlist, PriceAlert
from app.services.moex_service import (
    get_all_coupons_cached,
    get_bond_cached,
    get_coupon_calendar_cached,
    prefetch_bonds_batch,
)
from app.constants import calc_ndfl, LDV_YEARS_THRESHOLD, LDV_ANNUAL_DEDUCTION
from app.moex import get_currency_rates, get_gcurve_rate

logger = logging.getLogger(__name__)


# ── CRUD / Query helpers ─────────────────────────────────────────────────────


def get_active_bonds(user_id: int) -> list[BondPortfolio]:
    return BondPortfolio.query.filter_by(user_id=user_id, is_sold=False).all()


def get_sold_bonds(user_id: int) -> list[BondPortfolio]:
    return BondPortfolio.query.filter_by(user_id=user_id, is_sold=True).all()


def get_sold_bonds_in_range(
    user_id: int, year_start: date, year_end: date
) -> list[BondPortfolio]:
    return BondPortfolio.query.filter(
        BondPortfolio.user_id == user_id,
        BondPortfolio.is_sold == True,  # noqa: E712
        BondPortfolio.sell_date >= year_start,
        BondPortfolio.sell_date <= year_end,
    ).all()


def get_bond_or_none(bond_id: int, user_id: int) -> Optional[BondPortfolio]:
    return BondPortfolio.query.filter_by(id=bond_id, user_id=user_id).first()


def get_bond_by_id(bond_id: int) -> Optional[BondPortfolio]:
    return db.session.get(BondPortfolio, bond_id)


def delete_position(bond_id: int, user_id: int) -> Optional[str]:
    """Удаляет позицию и связанную транзакцию покупки. Возвращает None если не найдена."""
    bond = get_bond_or_none(bond_id, user_id)
    if not bond:
        return None

    tx = Transaction.query.filter_by(
        user_id=user_id,
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
    return "ok"


def reset_portfolio(user_id: int) -> None:
    Transaction.query.filter_by(user_id=user_id).delete()
    BondPortfolio.query.filter_by(user_id=user_id).delete()
    db.session.commit()


def add_bond(
    user_id: int,
    isin: str,
    secid: str,
    name: str,
    amount: int,
    buy_price: float,
    last_price: float,
    purchase_date: date,
    currency: str = "RUB",
    notes: Optional[str] = None,
) -> tuple[BondPortfolio, int]:
    """Добавляет облигацию + транзакцию. Возвращает (bond, existing_amount)."""
    existing = BondPortfolio.query.filter_by(
        user_id=user_id, isin=isin, is_sold=False
    ).first()
    existing_amount = existing.amount if existing else 0

    new_bond = BondPortfolio(
        user_id=user_id,
        isin=isin,
        secid=secid,
        name=name,
        amount=amount,
        buy_price=buy_price,
        last_price=last_price,
        purchase_date=purchase_date,
        is_sold=False,
        currency=currency,
        notes=notes,
    )
    db.session.add(new_bond)
    db.session.add(
        Transaction(
            user_id=user_id,
            isin=isin,
            name=name,
            tx_type="buy",
            amount=amount,
            price=buy_price,
            currency=currency,
            tx_date=purchase_date,
        )
    )
    db.session.commit()
    return new_bond, existing_amount


def sell_bond(
    bond: BondPortfolio,
    sell_price: float,
    sell_qty: int,
    broker_commission: Optional[float],
    user_id: int,
) -> str:
    """Продаёт (частично или полностью). Возвращает сообщение."""
    if sell_qty < bond.amount:
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
            broker_commission=broker_commission,
            notes=bond.notes,
        )
        db.session.add(sold_bond)
        message = f"Частично продано {sell_qty} шт. облигации {bond.name}."
    else:
        sell_qty = bond.amount
        bond.is_sold = True
        bond.sell_date = date.today()
        bond.sell_price = sell_price
        if broker_commission is not None:
            bond.broker_commission = broker_commission
        sold_bond = bond
        message = f"Облигация {bond.name} полностью продана и переведена в архив."

    db.session.add(
        Transaction(
            user_id=user_id,
            isin=bond.isin,
            name=bond.name,
            tx_type="sell",
            amount=sell_qty,
            price=sell_price,
            commission=broker_commission,
            tx_date=sold_bond.sell_date,
            currency=bond.currency or "RUB",
        )
    )
    db.session.commit()
    return message


def update_bond_notes(bond_id: int, user_id: int, notes: str) -> Optional[str]:
    """Обновляет заметку. Возвращает None если позиция не найдена."""
    bond = BondPortfolio.query.filter_by(id=bond_id, user_id=user_id).first_or_404()
    bond.notes = notes if notes else None
    db.session.commit()
    return bond.notes or ""


def flush_portfolio_prices() -> None:
    """Коммитит обновлённые last_price из build_portfolio_list."""
    try:
        db.session.commit()
    except Exception:
        db.session.rollback()


def build_transaction_entry(
    t: Transaction, sold_bonds_map: Optional[dict] = None
) -> dict:
    """Строит словарь данных одной транзакции для API.

    sold_bonds_map — опциональный dict {(isin, amount, sell_date): BondPortfolio}
    для избежания N+1 запросов. Если не передан, делается отдельный запрос.
    """
    buy_p = float(t.price)
    sell_p = float(t.price)
    commission = float(t.commission) if t.commission else 0.0
    pnl = 0.0
    pnl_pct = 0.0
    sell_date = None
    purchase_date = None

    if t.tx_type == "sell":
        sell_date = t.tx_date.strftime("%Y-%m-%d")
        if sold_bonds_map is not None:
            bond = sold_bonds_map.get((t.isin, t.amount, t.tx_date))
        else:
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


def ensure_transactions_exist(user_id: int) -> None:
    """Мигрирует legacy-позиции в таблицу Transaction если та пуста."""
    tx_count = Transaction.query.filter_by(user_id=user_id).count()
    if tx_count > 0:
        return
    bonds = BondPortfolio.query.filter_by(user_id=user_id).all()
    for b in bonds:
        db.session.add(
            Transaction(
                user_id=user_id,
                isin=b.isin,
                name=b.name,
                tx_type="buy",
                amount=b.amount,
                price=b.buy_price,
                tx_date=b.purchase_date,
                commission=0.0,
            )
        )
        if b.is_sold:
            db.session.add(
                Transaction(
                    user_id=user_id,
                    isin=b.isin,
                    name=b.name,
                    tx_type="sell",
                    amount=b.amount,
                    price=b.sell_price if b.sell_price is not None else b.buy_price,
                    tx_date=b.sell_date if b.sell_date is not None else b.purchase_date,
                    commission=b.broker_commission,
                )
            )
    db.session.commit()


def query_transactions(
    user_id: int,
    tx_type: Optional[str],
    date_from: Optional[date],
    date_to: Optional[date],
    page: int,
    per_page: int,
) -> tuple[list[dict], int]:
    """Возвращает (список транзакций, total_count)."""
    query = Transaction.query.filter_by(user_id=user_id)
    if tx_type in ("buy", "sell", "coupon"):
        query = query.filter_by(tx_type=tx_type)
    if date_from:
        query = query.filter(Transaction.tx_date >= date_from)
    if date_to:
        query = query.filter(Transaction.tx_date <= date_to)

    total_count = query.count()
    tx_list = (
        query.order_by(Transaction.tx_date.desc(), Transaction.id.desc())
        .offset((page - 1) * per_page)
        .limit(per_page)
        .all()
    )

    # Bulk-load sold BondPortfolio для всех sell-транзакций одним запросом → нет N+1.
    sold_keys = [
        (t.isin, t.amount, t.tx_date) for t in tx_list if t.tx_type == "sell"
    ]
    sold_bonds_map: dict = {}
    if sold_keys:
        isins = {k[0] for k in sold_keys}
        sold = BondPortfolio.query.filter(
            BondPortfolio.user_id == user_id,
            BondPortfolio.is_sold == True,  # noqa: E712
            BondPortfolio.isin.in_(isins),
        ).all()
        for b in sold:
            sold_bonds_map[(b.isin, b.amount, b.sell_date)] = b

    return (
        [build_transaction_entry(t, sold_bonds_map=sold_bonds_map) for t in tx_list],
        total_count,
    )


def get_allocation(user_id: int) -> list[dict]:
    """Аллокация активного портфеля для pie-chart."""
    active = get_active_bonds(user_id)
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
    return slices


# ── Calendar (вынесено в calendar_service.py) ────────────────────────────────
from app.services.calendar_service import get_calendar_events as get_coupon_calendar_events  # noqa: E402,F401
from app.services.calendar_service import get_upcoming_coupons  # noqa: E402,F401


# ── Watchlist / Price Alerts (вынесены, см. *_service.py) ────────────────────
# Re-export для обратной совместимости. Новый код должен импортировать напрямую
# из app.services.watchlist_service / alerts_service.
from app.services.watchlist_service import list_items as get_watchlist  # noqa: E402,F401
from app.services.watchlist_service import _legacy_add as add_to_watchlist  # noqa: E402,F401
from app.services.watchlist_service import _legacy_remove as remove_from_watchlist  # noqa: E402,F401
from app.services.alerts_service import list_alerts as get_price_alerts  # noqa: E402,F401
from app.services.alerts_service import create_alert as create_price_alert  # noqa: E402,F401
from app.services.alerts_service import _legacy_delete as delete_price_alert  # noqa: E402,F401


def normalize_bond_price(price: float, facevalue: float) -> float:
    """Конвертация цены в рубли. 
    Поскольку в БД цены хранятся преимущественно в % (до 300%),
    мы конвертируем их в рубли. Если цена > 300, считаем, что это старая запись в абсолютных рублях.
    """
    if price <= 0:
        return price
    if price <= 300.0:
        return round((price / 100.0) * facevalue, 2)
    return price


def heal_amortized_buy_price(
    buy_price: float, last_price: float, facevalue: float
) -> Optional[float]:
    """Heal buy_price для амортизируемых облигаций после импорта из Tinkoff.

    Если buy_price аномально низкий (< 30%) но last_price нормальный (≥ 60%) —
    скорее всего T-Invest отдал averagePositionPrice от исходного номинала,
    а MOEX отдаёт текущий (амортизированный) номинал.
    Корректное значение ~ buy_price × (исходный_nom / текущий_nom).
    Возвращает None если heal не нужен.
    """
    if facevalue <= 150.0 or buy_price <= 0 or last_price <= 0:
        return None
    # heal только когда buy явно аномальный, а last в нормальном диапазоне
    if not (0.0 < buy_price < 30.0 and 60.0 <= last_price <= 200.0):
        return None
    ratio = last_price / buy_price if buy_price else 0
    if ratio < 5:
        return None
    # Подбираем множитель так, чтобы heal-цена попадала в диапазон [60, 200].
    candidates = [10.0, 100.0]
    for mult in candidates:
        healed = buy_price * mult
        if 60.0 <= healed <= 200.0:
            return round(healed, 2)
    return None


def build_portfolio_entry(bond: BondPortfolio, rates: Optional[dict] = None) -> dict:
    """Строит словарь с данными одной активной позиции, включая P&L и MOEX-данные.

    rates — курсы валют, передаются снаружи чтобы избежать N+1 запросов.
    """
    if rates is None:
        rates = get_currency_rates()
    currency = bond.currency or "RUB"
    buy_p = float(bond.buy_price)

    moex_data: dict = get_bond_cached(bond.isin) or {}
    moex_price = moex_data.get("price")
    facevalue = float(moex_data.get("facevalue") or 1000)

    # MOEX price is already in RUB, but for consistency we calculate it from percentage if possible
    last_p_rub = None
    last_p_pct = None
    if moex_price is not None:
        last_p_rub = float(moex_price)
        last_p_pct = (last_p_rub / facevalue) * 100 if facevalue else 0.0
    elif bond.last_price is not None:
        last_p_rub = normalize_bond_price(float(bond.last_price), facevalue)
        last_p_pct = float(bond.last_price) if float(bond.last_price) <= 300 else (last_p_rub / facevalue) * 100
    else:
        last_p_rub = normalize_bond_price(buy_p, facevalue)
        last_p_pct = buy_p if buy_p <= 300 else (last_p_rub / facevalue) * 100

    # Применяем нормализацию к buy_price без сохранения в БД (сохраняем проценты)
    buy_p_rub = normalize_bond_price(buy_p, facevalue)
    buy_p_pct = buy_p if buy_p <= 300 else (buy_p_rub / facevalue) * 100

    current_value = bond.amount * last_p_rub
    pnl = (last_p_rub - buy_p_rub) * bond.amount
    pnl_pct = ((last_p_rub - buy_p_rub) / buy_p_rub * 100) if buy_p_rub else 0.0

    # Расчет рублевого эквивалента
    rate = 1.0 if currency in ["RUB", "GLD"] else rates.get(currency, 1.0)
    current_value_rub = current_value * rate
    pnl_rub = pnl * rate
    buy_price_rub = round(buy_p_rub * rate, 2) if currency != "RUB" else None
    last_price_rub = round(last_p_rub * rate, 2) if currency != "RUB" else None

    # Расчет дюрации — защищаемся от любых проблем с расчётом, чтобы
    # отдельная "плохая" облигация не сломала весь портфель.
    try:
        dur = calc_bond_duration(
            bond.isin, last_p_rub, facevalue, moex_data.get("ytm", 0.0), bond.amount
        )
    except Exception as exc:
        logger.warning("calc_bond_duration failed for %s: %s", bond.isin, exc)
        dur = {"macaulay_duration": 0.0, "modified_duration": 0.0}

    # Расчет YTM по цене покупки
    nkd = moex_data.get("nkd", 0.0)
    try:
        ytm_calculated = calc_bond_ytm(
            bond.isin, buy_p_rub, facevalue, nkd, bond.purchase_date
        )
    except Exception as exc:
        logger.warning("calc_bond_ytm failed for %s: %s", bond.isin, exc)
        ytm_calculated = None
    if ytm_calculated is None:
        ytm_calculated = moex_data.get("ytm", 0.0)

    # Флоатеры и замещайки:
    # Замещайки обычно в USD/EUR и имеют специфичные названия или тикеры.
    # Но мы уже отмечаем is_substitute если currency != "RUB".
    # Иногда замещайки могут иметь currency="RUB" но FaceUnit - USD.
    # Мы это решаем в get_moex_bond (currency выставляется по FACEUNIT).
    is_substitute = currency != "RUB" or "ЗО" in (bond.name or "") or "-ЗД" in (bond.name or "")

    name_upper = (bond.name or "").upper()
    is_floater = "ФЛОАТЕР" in name_upper or " ПК" in name_upper or "ОФЗ 29" in name_upper or "ОФЗ-ПК" in name_upper

    return {
        "id": bond.id,
        "isin": bond.isin,
        "name": bond.name or "Облигация",
        "amount": bond.amount,
        "buy_price": buy_p_pct,
        "buy_price_rub_calc": round(buy_p_rub, 2),
        "last_price": last_p_pct,
        "facevalue": facevalue,
        "current_value": round(current_value, 2),
        "current_value_rub": round(current_value_rub, 2),
        "purchase_date": bond.purchase_date.strftime("%Y-%m-%d"),
        "nkd": moex_data.get("nkd", 0.0),
        "ytm": ytm_calculated,
        "pnl": round(pnl, 2),
        "pnl_rub": round(pnl_rub, 2),
        "pnl_pct": round(pnl_pct, 2),
        "currency": currency,
        "is_substitute": is_substitute,
        "is_floater": is_floater,
        "rate_rub": round(rate, 4) if currency != "RUB" else None,
        "buy_price_rub": buy_price_rub,
        "last_price_rub": last_price_rub,
        "notes": bond.notes or "",
        "macaulay_duration": dur["macaulay_duration"],
        "modified_duration": dur["modified_duration"],
    }


def build_portfolio_list(active_bonds: list[BondPortfolio]) -> tuple[list[dict], float]:
    """Возвращает (список позиций, суммарная стоимость портфеля в RUB)."""
    # Прогрев MOEX-кэша одним batch-запросом → 1 HTTP вместо N.
    prefetch_bonds_batch([b.isin for b in active_bonds])
    rates = get_currency_rates()  # один запрос на весь список
    portfolio_list: list[dict] = []
    total_value = 0.0
    for bond in active_bonds:
        try:
            entry = build_portfolio_entry(bond, rates=rates)
            total_value += entry["current_value_rub"]
            portfolio_list.append(entry)
        except Exception as exc:
            # Одна сломанная позиция не должна выкинуть весь портфель.
            logger.warning(
                "build_portfolio_entry failed for bond_id=%s isin=%s: %s",
                bond.id,
                bond.isin,
                exc,
            )
    return portfolio_list, total_value


def calc_portfolio_ytm(portfolio_list: list[dict], total_value: float) -> float:
    """Средневзвешенная YTM портфеля (веса только по бумагам с валидным YTM).

    Поддерживает как 'current_value_rub' (multi-currency), так и устаревший
    'current_value' ключ для обратной совместимости с unit/property-тестами.
    """
    valid_bonds = [
        b for b in portfolio_list if b.get("ytm") is not None and b["ytm"] != 0.0
    ]
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
        "name": getattr(bond, "name", None) or "Облигация",
        "amount": bond.amount,
        "buy_price": buy_p,
        "sell_price": round(sell_p, 2),
        "commission": round(commission, 2),
        "pnl": round(pnl, 2),
        "pnl_pct": round(pnl_pct, 2),
        "currency": getattr(bond, "currency", None) or "RUB",
        "purchase_date": bond.purchase_date.strftime("%Y-%m-%d")
        if bond.purchase_date
        else None,
        "sell_date": bond.sell_date.strftime("%Y-%m-%d") if bond.sell_date else None,
    }


def calc_coupon_income(active_bonds: list[BondPortfolio]) -> dict[str, float]:
    """Прогноз купонного дохода в разрезах 30/90/365 дней в пересчете на RUB.

    Купонные календари загружаются параллельно через ThreadPoolExecutor.
    """
    rates = get_currency_rates()
    today = date.today()
    windows: dict[str, int] = {"30d": 30, "90d": 90, "365d": 365}
    totals: dict[str, float] = {k: 0.0 for k in windows}

    # Уникальные targets для параллельной загрузки
    targets = list({bond.secid or bond.isin for bond in active_bonds})
    calendars: dict[str, list] = {}
    with ThreadPoolExecutor(max_workers=8) as executor:
        futures = {executor.submit(get_coupon_calendar_cached, t): t for t in targets}
        for future in as_completed(futures):
            calendars[futures[future]] = future.result() or []

    for bond in active_bonds:
        target = bond.secid or bond.isin
        currency = bond.currency or "RUB"
        rate = 1.0 if currency in ["RUB", "GLD"] else rates.get(currency, 1.0)
        for c in calendars.get(target, []):
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


def calc_coupons_received(
    active_bonds: list[BondPortfolio],
    period_from: Optional[date] = None,
    period_to: Optional[date] = None,
) -> dict:
    """Сумма полученных купонов по активным позициям из исторических данных MOEX.

    Для каждой активной облигации берёт ВСЕ известные купоны и оставляет те,
    у которых дата попала в [max(purchase_date, period_from), period_to=today].
    Возвращает {total: float, by_isin: {isin: amount}}.
    """
    today = date.today()
    period_to = period_to or today
    rates = get_currency_rates()

    targets = list({bond.secid or bond.isin for bond in active_bonds})
    calendars: dict[str, list] = {}
    if targets:
        with ThreadPoolExecutor(max_workers=8) as executor:
            futures = {
                executor.submit(get_all_coupons_cached, t): t for t in targets
            }
            for future in as_completed(futures):
                try:
                    calendars[futures[future]] = future.result() or []
                except Exception:
                    calendars[futures[future]] = []

    total = 0.0
    by_isin: dict[str, float] = defaultdict(float)

    for bond in active_bonds:
        target = bond.secid or bond.isin
        currency = bond.currency or "RUB"
        rate = 1.0 if currency in ("RUB", "GLD") else rates.get(currency, 1.0)
        # Окно: от даты покупки до today (либо переданного period_to).
        lo_dates = [period_from, bond.purchase_date]
        lo_dates = [d for d in lo_dates if d is not None]
        lo = max(lo_dates) if lo_dates else None
        for c in calendars.get(target, []):
            c_date_str = c.get("date") or c.get("coupondate") or ""
            if not c_date_str:
                continue
            try:
                c_date = datetime.strptime(c_date_str[:10], "%Y-%m-%d").date()
            except ValueError:
                continue
            if lo and c_date < lo:
                continue
            if c_date > period_to:
                continue
            val = c.get("value") or 0.0
            if not val:
                continue
            payout = float(val) * bond.amount * rate
            total += payout
            by_isin[bond.isin] += payout

    return {
        "total": round(total, 2),
        "by_isin": {k: round(v, 2) for k, v in by_isin.items()},
    }


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
        currency = bond.currency or "RUB"
        rate = 1.0 if currency in ["RUB", "GLD"] else rates.get(currency, 1.0)
        monthly[group_date.strftime("%Y-%m")] += (
            (sell_p - float(bond.buy_price)) * bond.amount * rate
        )
    return dict(monthly)



# ── Tax & Risk (вынесены в tax_service.py / risk_service.py) ─────────────────
# Re-export для обратной совместимости с blueprints и тестами.
# Новый код должен импортировать из соответствующего сервиса напрямую.
from app.services.tax_service import (  # noqa: E402,F401
    apply_ldv,
    calc_fifo_pnl,
    calc_tax_basis_per_trade,
    calc_tax_report,
)
from app.services.risk_service import (  # noqa: E402,F401
    calc_bond_duration,
    calc_bond_ytm,
    calc_portfolio_diversification,
    calc_sharpe_ratio,
)
