"""Сервис портфеля — P&L, доходность, купонный доход, налоги, Sharpe Ratio."""

import logging
import math
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, date
from typing import Optional

from models import BondPortfolio
from services.moex_service import get_bond_cached, get_coupon_calendar_cached
from constants import calc_ndfl, LDV_YEARS_THRESHOLD, LDV_ANNUAL_DEDUCTION
from moex import get_currency_rates, get_gcurve_rate
from extensions import db

logger = logging.getLogger(__name__)


def normalize_bond_price(price: float, facevalue: float) -> float:
    """Интеллектуальное определение и конвертация процентных цен в рубли.

    Если цена выглядит как процент (30-200%) при номинале > 150 ₽ — пересчитывает в рубли.
    """
    if price <= 0 or facevalue <= 150.0:
        return price
    is_valid_pct = (30.0 <= price <= 200.0)
    pct_if_rub = (price / facevalue) * 100.0
    is_valid_rub = (30.0 <= pct_if_rub <= 200.0)
    if is_valid_pct and not is_valid_rub:
        return round((price / 100.0) * facevalue, 2)
    return price


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

    # Применяем интеллектуальное автоисправление цены покупки, если требуется
    healed_buy_price = normalize_bond_price(buy_p, facevalue)
    if healed_buy_price != buy_p:
        buy_p = healed_buy_price
        bond.buy_price = buy_p
        
        # Синхронизируем цену во всех связанных транзакциях покупки
        from models import Transaction
        txs = Transaction.query.filter_by(user_id=bond.user_id, isin=bond.isin, tx_type='buy').all()
        for tx in txs:
            tx.price = normalize_bond_price(float(tx.price), facevalue)
        # db.session.commit() убран из гетера для чистоты архитектуры (коммитится на уровне роута)

    if moex_price is not None:
        last_p = float(moex_price)
    else:
        last_p = float(bond.last_price) if bond.last_price is not None else buy_p

    current_value = bond.amount * last_p
    pnl = (last_p - buy_p) * bond.amount
    pnl_pct = ((last_p - buy_p) / buy_p * 100) if buy_p else 0.0

    # Расчет рублевого эквивалента
    rate = 1.0 if currency in ["RUB", "GLD"] else rates.get(currency, 1.0)
    current_value_rub = current_value * rate
    pnl_rub = pnl * rate
    buy_price_rub = round(buy_p * rate, 2) if currency != "RUB" else None
    last_price_rub = round(last_p * rate, 2) if currency != "RUB" else None

    # Расчет дюрации
    dur = calc_bond_duration(bond.isin, last_p, facevalue, moex_data.get("ytm", 0.0), bond.amount)

    return {
        "id": bond.id,
        "isin": bond.isin,
        "name": bond.name or "Облигация",
        "amount": bond.amount,
        "buy_price": buy_p,
        "last_price": last_p,
        "facevalue": facevalue,
        "current_value": round(current_value, 2),
        "current_value_rub": round(current_value_rub, 2),
        "purchase_date": bond.purchase_date.strftime("%Y-%m-%d"),
        "nkd": moex_data.get("nkd", 0.0),
        "ytm": moex_data.get("ytm", 0.0),
        "pnl": round(pnl, 2),
        "pnl_rub": round(pnl_rub, 2),
        "pnl_pct": round(pnl_pct, 2),
        "currency": currency,
        "rate_rub": round(rate, 4) if currency != "RUB" else None,
        "buy_price_rub": buy_price_rub,
        "last_price_rub": last_price_rub,
        "notes": bond.notes or "",
        "macaulay_duration": dur["macaulay_duration"],
        "modified_duration": dur["modified_duration"],
    }


def build_portfolio_list(active_bonds: list[BondPortfolio]) -> tuple[list[dict], float]:
    """Возвращает (список позиций, суммарная стоимость портфеля в RUB)."""
    rates = get_currency_rates()  # один запрос на весь список
    portfolio_list: list[dict] = []
    total_value = 0.0
    for bond in active_bonds:
        entry = build_portfolio_entry(bond, rates=rates)
        total_value += entry["current_value_rub"]
        portfolio_list.append(entry)
    return portfolio_list, total_value


def calc_portfolio_ytm(portfolio_list: list[dict], total_value: float) -> float:
    """Средневзвешенная YTM портфеля (веса только по бумагам с валидным YTM).

    Поддерживает как 'current_value_rub' (multi-currency), так и устаревший
    'current_value' ключ для обратной совместимости с unit/property-тестами.
    """
    valid_bonds = [b for b in portfolio_list if b.get("ytm") is not None and b["ytm"] != 0.0]
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


def calc_tax_basis_per_trade(bond: BondPortfolio, rates: dict) -> dict:
    """Налоговая база одной сделки по ст. 214.1 НК РФ.

    Доход = цена продажи + НКД при продаже.
    Расходы = цена покупки + НКД при покупке + комиссия брокера.
    """
    buy_p = float(bond.buy_price)
    sell_p = float(bond.sell_price) if bond.sell_price else buy_p
    comm = float(bond.broker_commission) if bond.broker_commission else 0.0
    nkd_buy = float(getattr(bond, "nkd_at_buy", 0) or 0)
    nkd_sell = float(getattr(bond, "nkd_at_sell", 0) or 0)
    currency = bond.currency or "RUB"
    rate = 1.0 if currency in ["RUB", "GLD"] else rates.get(currency, 1.0)
    n = bond.amount

    gross_income = (sell_p + nkd_sell) * n * rate
    expenses = (buy_p + nkd_buy) * n * rate + comm * rate
    pnl = gross_income - expenses
    days_held = (
        (bond.sell_date - bond.purchase_date).days
        if (bond.purchase_date and bond.sell_date)
        else 0
    )
    return {
        "gross_income": round(gross_income, 2),
        "expenses": round(expenses, 2),
        "pnl": round(pnl, 2),
        "tax_basis": round(max(pnl, 0.0), 2),
        "days_held": days_held,
    }


def apply_ldv(tax_basis: float, days_held: int) -> float:
    """Льгота на долгосрочное владение (ст. 219.1 НК РФ): минимум 3 года.

    Вычет = 3 000 000 ₽ × количество полных лет владения (не фиксировано 1 год).
    """
    if days_held < LDV_YEARS_THRESHOLD * 365:
        return tax_basis
    years_owned = days_held // 365
    return max(tax_basis - LDV_ANNUAL_DEDUCTION * years_owned, 0.0)


def calc_fifo_pnl(
    isin: str,
    user_id: int,
    sell_amount: int,
    sell_price: float,
    sell_nkd: float,
    sell_commission: float,
    rates: dict,
) -> dict:
    """P&L одной продажи по методу FIFO (ст. 214.1 НК РФ).

    Требует наличия записей в таблице Transaction с tx_type='buy'.
    """
    from models import Transaction

    buys = (
        Transaction.query
        .filter_by(user_id=user_id, isin=isin, tx_type="buy")
        .order_by(Transaction.tx_date.asc(), Transaction.id.asc())
        .all()
    )
    remaining = sell_amount
    total_cost = 0.0
    for buy in buys:
        if remaining <= 0:
            break
        used = min(buy.amount, remaining)
        nkd = float(getattr(buy, "nkd", None) or 0)
        buy_cost = (float(buy.price) + nkd) * used
        buy_comm = float(buy.commission or 0) * (used / buy.amount)
        total_cost += buy_cost + buy_comm
        remaining -= used

    # Определяем валюту из первой транзакции покупки (не хардкодим RUB)
    buy_currency = buys[0].currency if buys else "RUB"
    rate = 1.0 if buy_currency in ("RUB", "GLD") else rates.get(buy_currency, 1.0)
    sell_income = (sell_price + sell_nkd) * sell_amount * rate
    expenses = total_cost * rate + sell_commission * rate
    pnl = sell_income - expenses
    return {
        "tax_basis": round(max(pnl, 0.0), 2),
        "pnl": round(pnl, 2),
    }


def calc_tax_report(
    sold_bonds: list[BondPortfolio],
    active_bonds: list[BondPortfolio],
    year: int,
) -> dict:
    """Расчёт НДФЛ по ст. 214.1 НК РФ с дохода от продаж ценных бумаг за год.

    Купонный доход НЕ включается: с 2021 г. брокер удерживает налог
    у источника в момент выплаты — двойной учёт недопустим.
    """
    rates = get_currency_rates()
    year_start = date(year, 1, 1)
    year_end = date(year, 12, 31)

    # Суммируем сырой P&L (может быть отрицательным — убыток зачитывается по ст. 214.1)
    total_pnl = 0.0
    total_ldv_deduction = 0.0
    trades = []
    for bond in sold_bonds:
        if bond.sell_date and not (year_start <= bond.sell_date <= year_end):
            continue
        tb = calc_tax_basis_per_trade(bond, rates)
        pnl = tb["pnl"]
        days_held = tb["days_held"]

        if pnl > 0:
            # ЛДВ применяется только к прибыльным позициям
            after_ldv = apply_ldv(pnl, days_held)
            ldv_deduction = round(pnl - after_ldv, 2)
            ldv_applied = ldv_deduction > 0
            total_pnl += after_ldv
            total_ldv_deduction += ldv_deduction
        else:
            # Убыток уменьшает налоговую базу в текущем году
            after_ldv = pnl
            ldv_deduction = 0.0
            ldv_applied = False
            total_pnl += pnl

        trades.append({
            "isin": bond.isin,
            "name": bond.name or bond.isin,
            "pnl": pnl,
            "tax_basis": tb["tax_basis"],
            "ldv_applied": ldv_applied,
            "ldv_deduction": ldv_deduction,
            "days_held": days_held,
        })

    # Итоговая налоговая база не может быть отрицательной (убыток → перенос на будущее)
    taxable_basis = max(total_pnl, 0.0)
    tax = calc_ndfl(taxable_basis)
    return {
        "year": year,
        "sales_income": round(taxable_basis, 2),
        "total_income": round(taxable_basis, 2),
        "total_ldv_deduction": round(total_ldv_deduction, 2),
        "tax": round(tax, 2),
        "tax_13pct": round(tax, 2),  # обратная совместимость с фронтендом
        "trades": trades,
        "disclaimer": (
            "Расчёт носит ознакомительный характер. Применяется к налоговым резидентам РФ. "
            "Ставки НДФЛ для операций с ценными бумагами (ст. 214.1 НК РФ): "
            "13% с суммы до 2 400 000 ₽, 15% с суммы превышения. "
            "ЛДВ (пп. 1 п. 1 ст. 219.1 НК РФ) доступна только резидентам РФ. "
            "Брокер является налоговым агентом и удерживает налог самостоятельно. "
            "Купонный доход уже обложен у источника — не учитывается повторно."
        ),
    }


def calc_sharpe_ratio(
    sold_bonds: list,
    rf_annual: Optional[float] = None,
) -> Optional[dict]:
    """Коэффициент Шарпа на основе доходностей закрытых позиций.

    Дисперсия считается по формуле Бесселя (n-1) — выборка, не генеральная совокупность.
    rf_annual — годовая безрисковая ставка. Если не передана, берётся с G-curve MOEX.
    Требует ≥ 3 закрытых позиций.
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
    # sample variance (формула Бесселя: делим на n-1)
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


def calc_bond_duration(isin: str, last_price: float, facevalue: float, ytm_pct: float, amount: int) -> dict:
    """Рассчитывает дюрацию Маколея и модифицированную дюрацию облигации (в годах)."""
    import datetime
    from services.moex_service import get_coupon_calendar_cached
    
    today = datetime.date.today()
    coupons = get_coupon_calendar_cached(isin)
    
    # Если YTM не задана или некорректна, возвращаем заглушку по времени до погашения
    ytm = ytm_pct / 100.0 if ytm_pct and ytm_pct > 0 else 0.15  # fallback YTM 15%
    
    if not coupons:
        # Пытаемся получить дату погашения из деталей
        from services.moex_service import get_bond_preview
        details = get_bond_preview(isin) or {}
        matdate_str = details.get("matdate")
        if matdate_str:
            try:
                matdate = datetime.datetime.strptime(matdate_str[:10], "%Y-%m-%d").date()
                years = max((matdate - today).days / 365.25, 0.1)
                return {
                    "macaulay_duration": round(years, 2),
                    "modified_duration": round(years / (1 + ytm), 2),
                }
            except Exception:
                pass
        return {"macaulay_duration": 0.0, "modified_duration": 0.0}

    pv_sum = 0.0
    weighted_t_sum = 0.0
    
    # Сортируем купоны по дате
    coupons_sorted = sorted(coupons, key=lambda x: x["date"])
    
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
        # На последнем купоне выплачивается номинал (погашение)
        if i == len(coupons_sorted) - 1:
            val += facevalue
            
        pv_cf = val / ((1 + ytm) ** t)
        pv_sum += pv_cf
        weighted_t_sum += t * pv_cf

    if pv_sum <= 0:
        return {"macaulay_duration": 0.0, "modified_duration": 0.0}

    macaulay_dur = weighted_t_sum / pv_sum
    modified_dur = macaulay_dur / (1 + ytm)
    
    return {
        "macaulay_duration": round(macaulay_dur, 2),
        "modified_duration": round(modified_dur, 2),
    }


def calc_portfolio_diversification(active_bonds: list) -> dict:
    """Рассчитывает диверсификацию по HHI индексу (Herfindahl-Hirschman Index)
    в трех разрезах: по активам, по валютам и по эмитентам (ОФЗ vs Корпоративные).
    """
    from collections import defaultdict
    if not active_bonds:
        return {
            "assets": {"hhi": 0.0, "status": "Нет данных", "weights": []},
            "currencies": {"hhi": 0.0, "status": "Нет данных", "weights": []},
            "issuers": {"hhi": 0.0, "status": "Нет данных", "weights": []},
        }

    rates = get_currency_rates()
    total_val_rub = 0.0
    asset_vals = {}
    currency_vals = defaultdict(float)
    issuer_vals = defaultdict(float)

    for bond in active_bonds:
        currency = bond.currency or "RUB"
        rate = 1.0 if currency in ["RUB", "GLD"] else rates.get(currency, 1.0)
        # Получаем актуальную цену (последняя известная или цена покупки)
        price = float(bond.last_price) if bond.last_price is not None else float(bond.buy_price)
        val_rub = price * bond.amount * rate
        
        total_val_rub += val_rub
        key_name = bond.name or bond.isin
        asset_vals[key_name] = asset_vals.get(key_name, 0.0) + val_rub
        currency_vals[currency] += val_rub
        
        # Определяем тип эмитента по ISIN
        # ОФЗ обычно начинаются с SU, государственные/муниципальные — RU000A0
        isin = bond.isin.upper().strip()
        if isin.startswith("SU") or isin.startswith("RU000A0J") or "ОФЗ" in (bond.name or "").upper():
            issuer_type = "Гос. облигации (ОФЗ)"
        else:
            issuer_type = "Корпоративные облигации"
        issuer_vals[issuer_type] += val_rub

    if total_val_rub <= 0:
        return {
            "assets": {"hhi": 0.0, "status": "Нет данных", "weights": []},
            "currencies": {"hhi": 0.0, "status": "Нет данных", "weights": []},
            "issuers": {"hhi": 0.0, "status": "Нет данных", "weights": []},
        }

    # Вспомогательная функция для расчета HHI и статуса
    def _calc_hhi_metrics(vals_dict: dict) -> dict:
        weights = []
        hhi = 0.0
        for name, val in vals_dict.items():
            w = (val / total_val_rub) * 100.0
            weights.append({"name": name, "weight": round(w, 2), "value_rub": round(val, 2)})
            hhi += w ** 2
            
        weights.sort(key=lambda x: x["weight"], reverse=True)
        
        # Статусы концентрации по классификации HHI
        if hhi < 1500:
            status = "Отличная диверсификация"
            color = "success"
        elif hhi <= 2500:
            status = "Умеренная концентрация"
            color = "warning"
        else:
            status = "Высокая концентрация (высокий риск)"
            color = "danger"
            
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
