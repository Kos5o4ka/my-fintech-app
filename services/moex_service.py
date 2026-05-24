"""Сервис MOEX — кэшированный доступ к MOEX ISS API."""
from typing import Optional

from extensions import cache
from moex import get_moex_bond, get_bond_details
from constants import MOEX_BOND_TTL, BOND_PREVIEW_TTL, COUPON_CALENDAR_TTL


def get_bond_cached(isin: str) -> Optional[dict]:
    """Возвращает данные облигации с 15-минутным кэшем."""
    key = f"moex_bond:{isin}"
    result: Optional[dict] = cache.get(key)
    if result is None:
        result = get_moex_bond(isin)
        if result is not None:
            try:
                cache.set(key, result, timeout=MOEX_BOND_TTL)
            except Exception:
                pass
    return result


def get_bond_preview(isin: str) -> Optional[dict]:
    """Возвращает превью облигации (цена + детали) с 5-минутным кэшем."""
    cache_key = f"bond_preview:{isin}"
    cached: Optional[dict] = cache.get(cache_key)
    if cached:
        return cached

    moex_data = get_moex_bond(isin)
    if not moex_data:
        return None

    details = get_bond_details(moex_data["secid"])
    result: dict = {
        "status": "ok",
        "name": moex_data.get("name"),
        "price": moex_data.get("price"),
        "ytm": moex_data.get("ytm"),
        "nkd": moex_data.get("nkd"),
        "facevalue": moex_data.get("facevalue"),
        "currency": moex_data.get("currency", "RUB"),
        **details,
    }
    try:
        cache.set(cache_key, result, timeout=BOND_PREVIEW_TTL)
    except Exception:
        pass
    return result


def get_coupon_calendar_cached(secid: str) -> list[dict]:
    """Возвращает купонный календарь облигации с 12-часовым кэшем."""
    secid = secid.strip().upper()
    key = f"moex_coupons:{secid}"
    result = cache.get(key)
    if result is None:
        from moex import get_coupon_calendar
        result = get_coupon_calendar(secid)
        if result:
            try:
                cache.set(key, result, timeout=COUPON_CALENDAR_TTL)
            except Exception:
                pass
    return result or []
