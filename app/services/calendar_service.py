"""Купонный календарь и ближайшие выплаты."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date, timedelta

from app.models import BondPortfolio
from app.services.moex_service import get_coupon_calendar_cached


def _load_calendars_parallel(targets: list[str]) -> dict[str, list]:
    """Параллельно загружает купонные календари по уникальным targets (isin/secid)."""
    calendars: dict[str, list] = {}
    if not targets:
        return calendars
    with ThreadPoolExecutor(max_workers=8) as executor:
        futures = {executor.submit(get_coupon_calendar_cached, t): t for t in targets}
        for future in as_completed(futures):
            try:
                calendars[futures[future]] = future.result() or []
            except Exception:
                calendars[futures[future]] = []
    return calendars


def get_calendar_events(
    user_id: int, limit: int = 10, days: int | None = None
) -> list[dict]:
    """Ближайшие купонные выплаты по активным позициям.

    days — если задано, отдаёт только выплаты в ближайшие N дней.
    limit — максимум возвращаемых событий (default 10 для совместимости).
    """
    active = BondPortfolio.query.filter_by(user_id=user_id, is_sold=False).all()
    grouped: dict[str, dict] = {}
    for bond in active:
        key = bond.secid or bond.isin
        if key not in grouped:
            grouped[key] = {
                "name": bond.name or bond.isin,
                "isin": bond.isin,
                "amount": 0,
            }
        grouped[key]["amount"] += bond.amount

    calendars = _load_calendars_parallel(list(grouped.keys()))

    today = date.today()
    horizon = today + timedelta(days=days) if days else None

    events: list[dict] = []
    for target, data in grouped.items():
        for c in calendars.get(target, []):
            val = c.get("value") or 0.0
            c_date_str = c.get("date") or ""
            if not c_date_str:
                continue
            if horizon is not None:
                try:
                    c_date = date.fromisoformat(c_date_str[:10])
                except ValueError:
                    continue
                if not (today <= c_date <= horizon):
                    continue
            events.append(
                {
                    "name": data["name"],
                    "isin": data["isin"],
                    "date": c_date_str,
                    "total_payout": round(val * data["amount"], 2),
                    "coupon_value": float(val) if val else 0.0,
                    "amount": data["amount"],
                }
            )
    events.sort(key=lambda x: x["date"])
    return events[:limit]


def get_upcoming_coupons(user_id: int, days: int) -> list[dict]:
    """Купонные выплаты в ближайшие N дней (для колокольчика уведомлений)."""
    today = date.today()
    horizon = today + timedelta(days=days)
    active = BondPortfolio.query.filter_by(user_id=user_id, is_sold=False).all()

    # Параллельная загрузка по уникальным isin → быстрее в N раз.
    calendars = _load_calendars_parallel(list({b.isin for b in active}))

    events: list[dict] = []
    for bond in active:
        coupons = calendars.get(bond.isin, [])
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
    return events
