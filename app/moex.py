import logging
import time
from threading import Lock
from typing import Optional

import requests
from datetime import date
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
    after_log,
)

from app.constants import (
    MOEX_REQUEST_TIMEOUT,
    MOEX_MAX_HISTORY_OFFSET,
    MOEX_CIRCUIT_FAIL_THRESHOLD,
    MOEX_CIRCUIT_OPEN_SECONDS,
)

logger = logging.getLogger(__name__)

_TIMEOUT = MOEX_REQUEST_TIMEOUT

# ── Circuit breaker ───────────────────────────────────────────────────────────
# После MOEX_CIRCUIT_FAIL_THRESHOLD ошибок подряд все запросы
# блокируются на MOEX_CIRCUIT_OPEN_SECONDS секунд (10 мин).
_cb_lock = Lock()
_cb_fail_count: int = 0
_cb_open_until: float = 0.0


def _circuit_check() -> None:
    """Бросает RuntimeError, если автомат открыт."""
    from app.extensions import cache

    try:
        open_until = cache.get("moex_cb:open_until") or 0.0
    except Exception:
        # Резервный фолбэк на локальную память при сбое кэша
        global _cb_open_until
        open_until = _cb_open_until

    with _cb_lock:
        if time.time() < open_until:
            remaining = int(open_until - time.time())
            raise RuntimeError(f"MOEX недоступен, повтор через {remaining} с.")


def _circuit_success() -> None:
    from app.extensions import cache

    global _cb_fail_count
    with _cb_lock:
        _cb_fail_count = 0
    try:
        cache.delete("moex_cb:fail_count")
    except Exception:
        pass


def _circuit_failure() -> None:
    from app.extensions import cache

    global _cb_fail_count, _cb_open_until
    with _cb_lock:
        _cb_fail_count += 1

        # Интеграция с распределенным кэшем
        try:
            fail_count = (cache.get("moex_cb:fail_count") or 0) + 1
            cache.set("moex_cb:fail_count", fail_count, timeout=86400)
        except Exception:
            fail_count = _cb_fail_count

        if (
            fail_count >= MOEX_CIRCUIT_FAIL_THRESHOLD
            or _cb_fail_count >= MOEX_CIRCUIT_FAIL_THRESHOLD
        ):
            open_until = time.time() + MOEX_CIRCUIT_OPEN_SECONDS
            _cb_open_until = open_until
            _cb_fail_count = 0
            try:
                cache.set(
                    "moex_cb:open_until", open_until, timeout=MOEX_CIRCUIT_OPEN_SECONDS
                )
                cache.delete("moex_cb:fail_count")
            except Exception:
                pass
            logger.warning(
                "MOEX circuit breaker OPEN — слишком много ошибок, пауза %d с.",
                MOEX_CIRCUIT_OPEN_SECONDS,
            )


@retry(
    retry=retry_if_exception_type(requests.RequestException),
    stop=stop_after_attempt(3),
    wait=wait_exponential(min=1, max=4),
    reraise=True,
    after=after_log(logger, logging.WARNING),
)
def _fetch_json(url: str) -> dict:
    _circuit_check()
    try:
        resp = requests.get(url, timeout=_TIMEOUT)
        resp.raise_for_status()
        _circuit_success()
        return resp.json()
    except requests.RequestException:
        _circuit_failure()
        raise


def get_moex_bond(isin_code: str) -> Optional[dict]:
    isin_code = isin_code.strip().upper()
    try:
        search_res = _fetch_json(
            f"https://iss.moex.com/iss/securities.json?q={isin_code}"
        )
        if not search_res.get("securities") or not search_res["securities"]["data"]:
            return None

        sec_cols = search_res["securities"]["columns"]
        sec_data = search_res["securities"]["data"][0]
        secid = sec_data[sec_cols.index("secid")]

        board = (
            "TQOB"
            if (isin_code.startswith("SU") or isin_code.startswith("RU000A0"))
            else "TQCB"
        )
        res = None
        try:
            board_url = f"https://iss.moex.com/iss/engines/stock/markets/bonds/boards/{board}/securities/{secid}.json"
            res = _fetch_json(board_url)
            if not res.get("securities") or not res["securities"]["data"]:
                res = None
        except Exception:
            res = None

        if not res:
            res = _fetch_json(
                f"https://iss.moex.com/iss/engines/stock/markets/bonds/securities/{secid}.json"
            )

        if not res.get("securities") or not res["securities"]["data"]:
            return None

        sec_cols = res["securities"]["columns"]
        sec_data = res["securities"]["data"][0]
        mkt_cols = res["marketdata"]["columns"] if "marketdata" in res else []
        mkt_data = (
            res["marketdata"]["data"][0]
            if ("marketdata" in res and res["marketdata"]["data"])
            else []
        )

        def get_val(data, cols, name):
            if not data or name not in cols:
                return None
            return data[cols.index(name)]

        faceunit = (
            get_val(sec_data, sec_cols, "FACEUNIT")
            or get_val(sec_data, sec_cols, "CURRENCYID")
            or "SUR"
        )
        faceunit_str = str(faceunit).strip().upper()
        if faceunit_str in ["SUR", "RUB", "RUR"]:
            currency = "RUB"
        elif faceunit_str in ["USD", "USD000000TOD"]:
            currency = "USD"
        elif faceunit_str in ["CNY", "CNYRUB"]:
            currency = "CNY"
        elif faceunit_str in ["EUR", "EUR000000TOD"]:
            currency = "EUR"
        elif faceunit_str in ["GLD", "GOLD", "ГРАММ", "ГР"]:
            currency = "GLD"
        else:
            currency = "RUB"

        if currency == "GLD":
            gld_grams = float(get_val(sec_data, sec_cols, "FACEVALUE") or 1)
            facevalue = gld_grams * get_gold_price()
        else:
            facevalue = get_val(sec_data, sec_cols, "FACEVALUE") or 1000

        last_pct = get_val(mkt_data, mkt_cols, "LAST") or get_val(
            sec_data, sec_cols, "PREVPRICE"
        )
        if not last_pct:
            last_pct = 100
        price_rub = (last_pct / 100) * facevalue

        # Precedence: marketdata.YIELD -> marketdata.YIELDATWAPRICE -> securities.YIELDATPREVWAPRICE
        ytm_val = (
            get_val(mkt_data, mkt_cols, "YIELD")
            or get_val(mkt_data, mkt_cols, "YIELDATWAPRICE")
            or get_val(sec_data, sec_cols, "YIELDATPREVWAPRICE")
            or 0
        )
        try:
            ytm = float(ytm_val)
        except (TypeError, ValueError):
            ytm = 0.0

        return {
            "secid": secid,
            "name": get_val(sec_data, sec_cols, "SHORTNAME"),
            "price": round(price_rub, 2),
            "facevalue": facevalue,
            "nkd": round(get_val(sec_data, sec_cols, "ACCRUEDINT") or 0, 2),
            "ytm": round(ytm, 2),
            "currency": currency,
        }
    except Exception as e:
        logger.error("MOEX bond fetch error for %s: %s", isin_code, e)
        return None


def get_bond_history_all(secid: str, facevalue: float = 1000) -> dict:
    """Возвращает полную историю цен, НКД и YTM с пагинацией."""
    labels: list[str] = []
    prices: list[float] = []
    nkd_history: list[float] = []
    ytm_history: list[float] = []
    start_offset = 0
    try:
        while start_offset < MOEX_MAX_HISTORY_OFFSET:
            url = (
                f"https://iss.moex.com/iss/history/engines/stock/markets/bonds"
                f"/securities/{secid}.json"
                f"?history_shares.columns=TRADEDATE,CLOSE,ACCINT,YIELDCLOSE"
                f"&start={start_offset}"
            )
            res = _fetch_json(url)
            if not res.get("history") or not res["history"].get("data"):
                break

            columns = res["history"]["columns"]
            date_idx = columns.index("TRADEDATE")
            close_idx = columns.index("CLOSE")
            accint_idx = columns.index("ACCINT")
            yield_idx = columns.index("YIELDCLOSE")

            page_data = res["history"]["data"]
            if not page_data:
                break

            for row in page_data:
                if row[close_idx] is not None:
                    labels.append(row[date_idx])
                    prices.append(round((float(row[close_idx]) / 100) * facevalue, 2))
                    nkd_history.append(
                        round(float(row[accint_idx]) if row[accint_idx] else 0, 2)
                    )
                    ytm_history.append(
                        round(float(row[yield_idx]) if row[yield_idx] else 0, 2)
                    )

            if len(page_data) < 100:
                break
            start_offset += 100
    except Exception as e:
        logger.error("MOEX history pagination error for %s: %s", secid, e)
    return {"labels": labels, "data": prices, "nkd": nkd_history, "ytm": ytm_history}


def get_coupon_calendar(secid: str, include_past: bool = False) -> list[dict]:
    """Возвращает купонные выплаты для облигации."""
    try:
        res = _fetch_json(
            f"https://iss.moex.com/iss/statistics/engines/stock/markets"
            f"/bonds/bondization/{secid}.json"
        )
        calendar = []
        if res.get("coupons") and res["coupons"].get("data"):
            cols = res["coupons"]["columns"]
            for row in res["coupons"]["data"]:
                calendar.append(
                    {
                        "date": row[cols.index("coupondate")],
                        "value": row[cols.index("value")],
                    }
                )
        if include_past:
            return calendar
        today_str = date.today().isoformat()
        future = [c for c in calendar if c.get("date") and c["date"] >= today_str]
        return future[:12]
    except Exception as e:
        logger.warning("MOEX coupon calendar error for %s: %s", secid, e)
        return []


def get_bond_date_info(secid: str) -> dict:
    """Публичная обёртка для получения дат размещения и погашения облигации."""
    try:
        res = _fetch_json(f"https://iss.moex.com/iss/securities/{secid}.json")
        out: dict = {}
        if res.get("description") and res["description"].get("data"):
            for row in res["description"]["data"]:
                if row[0] == "ISSUEDATE" and row[2]:
                    out["issue_date"] = row[2]
                elif row[0] == "MATDATE" and row[2]:
                    out["mat_date"] = row[2]
        return out
    except Exception as e:
        logger.warning("Bond date info fetch error for %s: %s", secid, e)
        return {}


def get_bond_details(secid: str) -> dict:
    """Fetch supplementary metadata: maturity date, coupon rate, coupon frequency."""
    try:
        res = _fetch_json(f"https://iss.moex.com/iss/securities/{secid}.json")
        out: dict = {}
        if res.get("description") and res["description"].get("data"):
            for row in res["description"]["data"]:
                key, val = row[0], row[2]
                if key == "MATDATE" and val:
                    out["matdate"] = val
                elif key == "COUPONPERCENT" and val is not None:
                    try:
                        out["coupon_pct"] = float(val)
                    except (ValueError, TypeError):
                        pass
                elif key == "COUPONFREQUENCY" and val is not None:
                    try:
                        out["coupon_freq"] = int(float(val))
                    except (ValueError, TypeError):
                        pass
        return out
    except Exception as e:
        logger.warning("Bond details fetch error for %s: %s", secid, e)
        return {}


def get_rgbi_history(
    from_date: Optional[str] = None, to_date: Optional[str] = None
) -> dict:
    """Fetch RGBI index price history from MOEX ISS."""
    try:
        url = (
            "https://iss.moex.com/iss/history/engines/stock/markets/index"
            "/securities/RGBI.json"
            "?history.columns=TRADEDATE,CLOSE&limit=300"
        )
        if from_date:
            url += f"&from={from_date}"
        if to_date:
            url += f"&till={to_date}"
        res = _fetch_json(url)
        if not res.get("history") or not res["history"].get("data"):
            return {"labels": [], "data": []}
        cols = res["history"]["columns"]
        date_idx = cols.index("TRADEDATE")
        close_idx = cols.index("CLOSE")
        labels, prices = [], []
        for row in res["history"]["data"]:
            if row[close_idx] is not None:
                labels.append(row[date_idx])
                prices.append(round(float(row[close_idx]), 2))
        return {"labels": labels, "data": prices}
    except Exception as e:
        logger.error("RGBI history fetch error: %s", e)
        return {"labels": [], "data": []}


def get_screener_bonds(
    min_ytm: Optional[float] = None,
    max_ytm: Optional[float] = None,
    maturity_from: Optional[str] = None,
    maturity_to: Optional[str] = None,
    limit: int = 1000,
) -> list[dict]:
    """Fetch bonds list from MOEX with optional YTM / maturity filtering."""
    try:
        # Для охвата всего рынка запрашиваем не менее 1000 бумаг у MOEX
        fetch_limit = max(limit, 1000)
        url = (
            "https://iss.moex.com/iss/engines/stock/markets/bonds/securities.json"
            "?securities.columns=SECID,ISIN,SHORTNAME,YIELDTOOFFER,MATDATE,COUPONVALUE"
            f"&start=0&limit={fetch_limit}"
        )
        res = _fetch_json(url)
        if not res.get("securities") or not res["securities"].get("data"):
            return []
        cols = res["securities"]["columns"]

        def gv(row, name):
            return row[cols.index(name)] if name in cols else None

        results = []
        for row in res["securities"]["data"]:
            isin = gv(row, "ISIN")
            if not isin:
                continue
            ytm_val = gv(row, "YIELDTOOFFER")
            mat_date = gv(row, "MATDATE")
            if ytm_val is not None:
                ytm_f = float(ytm_val)
                if min_ytm is not None and ytm_f < min_ytm:
                    continue
                if max_ytm is not None and ytm_f > max_ytm:
                    continue
            elif min_ytm is not None:
                continue
            if mat_date:
                if maturity_from and mat_date < maturity_from:
                    continue
                if maturity_to and mat_date > maturity_to:
                    continue
            elif maturity_from is not None or maturity_to is not None:
                continue
            results.append(
                {
                    "secid": gv(row, "SECID"),
                    "isin": isin,
                    "name": gv(row, "SHORTNAME") or gv(row, "SECID"),
                    "ytm": round(float(ytm_val), 2) if ytm_val is not None else None,
                    "matdate": mat_date,
                    "coupon": gv(row, "COUPONVALUE"),
                }
            )
        return results
    except Exception as e:
        logger.error("MOEX screener error: %s", e)
        return []


def search_bonds(query: str, limit: int = 10) -> list[dict]:
    try:
        url = (
            "https://iss.moex.com/iss/securities.json"
            f"?q={requests.utils.quote(query.strip())}"
            "&group_by=group&group_by_filter=stock_bonds"
            f"&limit={limit}"
            "&securities.columns=secid,isin,shortname,name"
        )
        res = _fetch_json(url)
        if not res.get("securities") or not res["securities"].get("data"):
            return []
        cols = res["securities"]["columns"]
        results = []
        for row in res["securities"]["data"]:
            secid = row[cols.index("secid")] if "secid" in cols else ""
            isin = row[cols.index("isin")] if "isin" in cols else ""
            shortname = row[cols.index("shortname")] if "shortname" in cols else ""
            name = row[cols.index("name")] if "name" in cols else ""
            display_name = shortname or name or secid
            if not isin:
                continue
            results.append({"secid": secid, "isin": isin, "name": display_name})
        return results
    except Exception as e:
        logger.error("MOEX search error for '%s': %s", query, e)
        return []


def get_currency_rates() -> dict[str, float]:
    """Возвращает текущие курсы валют (USD, CNY, EUR) по отношению к RUB.
    Использует кэш на 1 час (3600 с). При ошибке/закрытии биржи возвращает
    резервные значения.
    """
    from app.extensions import cache

    key = "moex_currency_rates"
    try:
        cached = cache.get(key)
        if cached:
            return cached
    except Exception:
        pass

    # Сначала пробуем CBR как базовый фолбэк (актуальнее хардкода)
    try:
        from app.cbr import get_rates as _cbr_rates

        cbr = _cbr_rates({"USD", "EUR", "CNY"})
        rates = {"RUB": 1.0, **cbr}
    except Exception:
        rates = {"RUB": 1.0, "USD": 90.0, "CNY": 12.5, "EUR": 98.0}
    tickers = {"USD": "USD000UTSTOM", "CNY": "CNYRUB_TOM", "EUR": "EUR_RUB__TOM"}

    for currency, ticker in tickers.items():
        try:
            url = f"https://iss.moex.com/iss/engines/currency/markets/selt/boards/CETS/securities/{ticker}.json"
            res = _fetch_json(url)
            if res.get("marketdata") and res["marketdata"].get("data"):
                m_cols = res["marketdata"]["columns"]
                m_data = res["marketdata"]["data"][0]
                price = None

                for col in ["LAST", "CURRENTVALUE", "WAPRICE"]:
                    if col in m_cols:
                        val = m_data[m_cols.index(col)]
                        if val is not None:
                            price = float(val)
                            break
                if not price and "securities" in res and res["securities"].get("data"):
                    s_cols = res["securities"]["columns"]
                    s_data = res["securities"]["data"][0]
                    if "PREVPRICE" in s_cols:
                        val = s_data[s_cols.index("PREVPRICE")]
                        if val is not None:
                            price = float(val)

                if price:
                    rates[currency] = round(price, 4)
        except Exception as e:
            logger.warning("Failed to fetch MOEX exchange rate for %s: %s", currency, e)

    try:
        cache.set(key, rates, timeout=3600)
    except Exception:
        pass

    return rates


def get_gcurve_rate(maturity_years: float, trade_date: Optional[str] = None) -> float:
    """Безрисковая ставка с кривой КБД (G-curve) MOEX на заданный срок.

    Линейная интерполяция между соседними точками кривой.
    Кэш 24 часа (кривая публикуется раз в день).
    При сбое или отсутствии Flask-контекста возвращает fallback 0.155.
    """
    try:
        from flask import current_app

        current_app._get_current_object()  # бросает RuntimeError если нет контекста
    except RuntimeError:
        return 0.155

    from app.extensions import cache

    cache_key = f"gcurve:{trade_date or 'latest'}:{maturity_years:.2f}"
    try:
        cached = cache.get(cache_key)
        if cached is not None:
            return float(cached)
    except Exception:
        pass

    try:
        url = "https://iss.moex.com/iss/engines/stock/markets/index/securities/GCURVE.json"
        if trade_date:
            url += f"?date={trade_date}"
        res = _fetch_json(url)
        cols = res["history"]["columns"]
        curve: dict[float, float] = {}
        for row in res["history"]["data"]:
            period = row[cols.index("PERIOD")]
            value = row[cols.index("VALUE")]
            if period is not None and value is not None:
                curve[float(period)] = float(value)

        if not curve:
            raise ValueError("G-curve data empty")

        periods = sorted(curve.keys())
        if maturity_years <= periods[0]:
            rate_pct = curve[periods[0]]
        elif maturity_years >= periods[-1]:
            rate_pct = curve[periods[-1]]
        else:
            lo = max(p for p in periods if p <= maturity_years)
            hi = min(p for p in periods if p >= maturity_years)
            t = (maturity_years - lo) / (hi - lo) if hi != lo else 0
            rate_pct = curve[lo] + t * (curve[hi] - curve[lo])

        rate = round(rate_pct / 100, 6)
        try:
            cache.set(cache_key, rate, timeout=86400)
            cache.set("gcurve:fallback", rate, timeout=86400 * 7)
        except Exception:
            pass
        return rate

    except Exception as e:
        logger.warning("G-curve fetch failed: %s", e)
        try:
            fallback = cache.get("gcurve:fallback")
            if fallback is not None:
                return float(fallback)
        except Exception:
            pass
        return 0.155


def get_gold_price() -> float:
    """Возвращает текущую спотовую стоимость золота (GLDRUB_TOM) в рублях за грамм.
    Кэш на 1 час, резервное значение — 7000.0 рублей.
    """
    from app.extensions import cache

    key = "moex_gold_price"
    try:
        cached = cache.get(key)
        if cached:
            return float(cached)
    except Exception:
        pass

    gold_price = 7000.0
    try:
        url = "https://iss.moex.com/iss/engines/commodity/markets/bullion/boards/USDR/securities/GLDRUB_TOM.json"
        res = _fetch_json(url)
        if res.get("marketdata") and res["marketdata"].get("data"):
            m_cols = res["marketdata"]["columns"]
            m_data = res["marketdata"]["data"][0]
            price = None
            for col in ["LAST", "CURRENTVALUE", "WAPRICE"]:
                if col in m_cols:
                    val = m_data[m_cols.index(col)]
                    if val is not None:
                        price = float(val)
                        break
            if not price and "securities" in res and res["securities"].get("data"):
                s_cols = res["securities"]["columns"]
                s_data = res["securities"]["data"][0]
                if "PREVPRICE" in s_cols:
                    val = s_data[s_cols.index("PREVPRICE")]
                    if val is not None:
                        price = float(val)
            if price:
                gold_price = round(price, 2)
    except Exception as e:
        logger.warning("Failed to fetch MOEX gold spot price: %s", e)

    try:
        cache.set(key, gold_price, timeout=3600)
    except Exception:
        pass

    return gold_price
