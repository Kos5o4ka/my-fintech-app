"""Сервис MOEX — кэшированный доступ к MOEX ISS API."""

import logging
from typing import Optional

from app.extensions import cache
from app.moex import get_moex_bond, get_bond_details
from app.constants import MOEX_BOND_TTL, BOND_PREVIEW_TTL, COUPON_CALENDAR_TTL

logger = logging.getLogger(__name__)


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


def prefetch_bonds_batch(isins: list[str]) -> None:
    """Один HTTP-запрос к MOEX для всех ISIN, прогревает кэш.

    Вместо N запросов get_moex_bond — один batch к
    /iss/engines/stock/markets/bonds/securities.json?securities=...

    Только прогревает кэш. ISIN, по которым MOEX вернул неполные данные,
    подтянутся индивидуально позже через get_bond_cached.
    """
    if not isins:
        return

    # Только те, что ещё не в кэше — экономим работу.
    missing: list[str] = []
    seen: set[str] = set()
    for isin in isins:
        norm = isin.strip().upper()
        if not norm or norm in seen:
            continue
        seen.add(norm)
        if cache.get(f"moex_bond:{norm}") is None:
            missing.append(norm)

    if not missing:
        return

    # MOEX securities= принимает до 10 SECID за раз. Чанкуем.
    from app.moex import _fetch_json, get_gold_price

    CHUNK = 10
    for i in range(0, len(missing), CHUNK):
        chunk = missing[i : i + CHUNK]
        try:
            url = (
                "https://iss.moex.com/iss/engines/stock/markets/bonds/securities.json"
                f"?securities={','.join(chunk)}"
                "&iss.meta=off"
            )
            res = _fetch_json(url)
        except Exception as exc:
            logger.warning("MOEX batch prefetch failed for chunk: %s", exc)
            continue

        sec = res.get("securities") or {}
        mkt = res.get("marketdata") or {}
        sec_cols = sec.get("columns") or []
        mkt_cols = mkt.get("columns") or []
        sec_rows = sec.get("data") or []
        mkt_rows = mkt.get("data") or []

        if not sec_cols or not sec_rows:
            continue

        # Индексируем marketdata по SECID для быстрого lookup.
        mkt_by_secid: dict = {}
        if mkt_cols and "SECID" in mkt_cols:
            sid_idx = mkt_cols.index("SECID")
            for row in mkt_rows:
                if row and len(row) > sid_idx:
                    mkt_by_secid[row[sid_idx]] = row

        def _get(row, cols, name):
            if not row or name not in cols:
                return None
            return row[cols.index(name)]

        for sec_row in sec_rows:
            secid = _get(sec_row, sec_cols, "SECID")
            if not secid:
                continue
            isin = _get(sec_row, sec_cols, "ISIN") or secid
            mkt_row = mkt_by_secid.get(secid, [])

            faceunit = (
                _get(sec_row, sec_cols, "FACEUNIT")
                or _get(sec_row, sec_cols, "CURRENCYID")
                or "SUR"
            )
            faceunit_str = str(faceunit).strip().upper()
            if faceunit_str in ("SUR", "RUB", "RUR"):
                currency = "RUB"
            elif faceunit_str in ("USD", "USD000000TOD"):
                currency = "USD"
            elif faceunit_str in ("CNY", "CNYRUB"):
                currency = "CNY"
            elif faceunit_str in ("EUR", "EUR000000TOD"):
                currency = "EUR"
            elif faceunit_str in ("GLD", "GOLD", "ГРАММ", "ГР"):
                currency = "GLD"
            else:
                currency = "RUB"

            try:
                if currency == "GLD":
                    gld_grams = float(_get(sec_row, sec_cols, "FACEVALUE") or 1)
                    facevalue = gld_grams * get_gold_price()
                else:
                    facevalue = float(_get(sec_row, sec_cols, "FACEVALUE") or 1000)
            except (TypeError, ValueError):
                facevalue = 1000.0

            last_pct = (
                _get(mkt_row, mkt_cols, "LAST")
                or _get(sec_row, sec_cols, "PREVPRICE")
                or 100
            )
            try:
                price_rub = (float(last_pct) / 100.0) * facevalue
            except (TypeError, ValueError):
                continue

            ytm_val = (
                _get(mkt_row, mkt_cols, "YIELD")
                or _get(mkt_row, mkt_cols, "YIELDATWAPRICE")
                or _get(sec_row, sec_cols, "YIELDATPREVWAPRICE")
                or 0
            )
            try:
                ytm = float(ytm_val)
            except (TypeError, ValueError):
                ytm = 0.0

            try:
                nkd = round(float(_get(sec_row, sec_cols, "ACCRUEDINT") or 0), 2)
            except (TypeError, ValueError):
                nkd = 0.0

            result = {
                "secid": secid,
                "name": _get(sec_row, sec_cols, "SHORTNAME"),
                "price": round(price_rub, 2),
                "facevalue": facevalue,
                "nkd": nkd,
                "ytm": round(ytm, 2),
                "currency": currency,
            }
            # Кэшируем по обоим ключам: ISIN и SECID — обычно совпадают, но не всегда.
            try:
                cache.set(f"moex_bond:{isin}", result, timeout=MOEX_BOND_TTL)
                if secid != isin:
                    cache.set(f"moex_bond:{secid}", result, timeout=MOEX_BOND_TTL)
            except Exception:
                pass


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
        from app.moex import get_coupon_calendar

        result = get_coupon_calendar(secid)
        if result:
            try:
                cache.set(key, result, timeout=COUPON_CALENDAR_TTL)
            except Exception:
                pass
    return result or []


def get_all_coupons_cached(secid: str) -> list[dict]:
    """Возвращает купонный календарь (включая прошлые купоны) с 12-часовым кэшем."""
    secid = secid.strip().upper()
    key = f"moex_all_coupons:{secid}"
    result = cache.get(key)
    if result is None:
        from app.moex import get_coupon_calendar

        result = get_coupon_calendar(secid, include_past=True)
        if result:
            try:
                cache.set(key, result, timeout=COUPON_CALENDAR_TTL)
            except Exception:
                pass
    return result or []
