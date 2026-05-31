"""Налоговый сервис — НДФЛ по ст. 214.1 НК РФ, ЛДВ, FIFO-учёт продаж.

Только финансовая математика и SQL-чтение Transaction. Никаких HTTP-ответов.
"""

from __future__ import annotations

from datetime import date

from app.constants import LDV_ANNUAL_DEDUCTION, LDV_YEARS_THRESHOLD, calc_ndfl
from app.models import BondPortfolio, Transaction
from app.moex import get_currency_rates


def calc_tax_basis_per_trade(bond: BondPortfolio, rates: dict) -> dict:
    """Налоговая база одной закрытой сделки по ст. 214.1 НК РФ.

    Доход   = цена продажи + НКД при продаже.
    Расходы = цена покупки + НКД при покупке + комиссия брокера.
    Валютные сделки пересчитываются в RUB по курсу из ``rates``.
    """
    buy_p = float(bond.buy_price)
    sell_p = float(bond.sell_price) if bond.sell_price else buy_p
    comm = float(bond.broker_commission) if bond.broker_commission else 0.0
    nkd_buy = float(getattr(bond, "nkd_at_buy", 0) or 0)
    nkd_sell = float(getattr(bond, "nkd_at_sell", 0) or 0)
    currency = bond.currency or "RUB"
    rate = 1.0 if currency in ("RUB", "GLD") else rates.get(currency, 1.0)
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

    Вычет = ``LDV_ANNUAL_DEDUCTION`` × количество полных лет владения.
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

    Требует наличия записей в Transaction с ``tx_type='buy'`` — иначе сделка
    некорректно учтётся (отдать вызывающему исключение мы не можем: legacy-вызовы
    рассчитывают на dict).
    """
    buys = (
        Transaction.query.filter_by(user_id=user_id, isin=isin, tx_type="buy")
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
    active_bonds: list[BondPortfolio],  # noqa: ARG001 — оставлен для обратной совместимости
    year: int,
) -> dict:
    """Расчёт НДФЛ за календарный год по реализованным сделкам.

    Купонный доход НЕ включается: с 2021 г. брокер удерживает налог
    у источника в момент выплаты — двойной учёт недопустим.
    """
    rates = get_currency_rates()
    year_start = date(year, 1, 1)
    year_end = date(year, 12, 31)

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
            after_ldv = apply_ldv(pnl, days_held)
            ldv_deduction = round(pnl - after_ldv, 2)
            ldv_applied = ldv_deduction > 0
            total_pnl += after_ldv
            total_ldv_deduction += ldv_deduction
        else:
            after_ldv = pnl
            ldv_deduction = 0.0
            ldv_applied = False
            total_pnl += pnl

        trades.append(
            {
                "isin": bond.isin,
                "name": bond.name or bond.isin,
                "pnl": pnl,
                "tax_basis": tb["tax_basis"],
                "ldv_applied": ldv_applied,
                "ldv_deduction": ldv_deduction,
                "days_held": days_held,
            }
        )

    taxable_basis = max(total_pnl, 0.0)
    tax = calc_ndfl(taxable_basis)
    return {
        "year": year,
        "sales_income": round(taxable_basis, 2),
        "coupon_income": 0.0,
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
