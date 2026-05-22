import logging
from typing import Optional

import requests
from datetime import datetime
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
    after_log,
)

from constants import MOEX_REQUEST_TIMEOUT, MOEX_MAX_HISTORY_OFFSET

logger = logging.getLogger(__name__)

_TIMEOUT = MOEX_REQUEST_TIMEOUT


@retry(
    retry=retry_if_exception_type(requests.RequestException),
    stop=stop_after_attempt(3),
    wait=wait_exponential(min=1, max=4),
    reraise=True,
    after=after_log(logger, logging.WARNING),
)
def _fetch_json(url: str) -> dict:
    resp = requests.get(url, timeout=_TIMEOUT)
    resp.raise_for_status()
    return resp.json()


def get_moex_bond(isin_code: str) -> Optional[dict]:
    isin_code = isin_code.strip().upper()
    try:
        search_res = _fetch_json(f"https://iss.moex.com/iss/securities.json?q={isin_code}")
        if not search_res.get('securities') or not search_res['securities']['data']:
            return None

        sec_cols = search_res['securities']['columns']
        sec_data = search_res['securities']['data'][0]
        secid = sec_data[sec_cols.index('secid')]

        res = _fetch_json(
            f"https://iss.moex.com/iss/engines/stock/markets/bonds/securities/{secid}.json"
        )
        if not res.get('securities') or not res['securities']['data']:
            return None

        sec_cols = res['securities']['columns']
        sec_data = res['securities']['data'][0]
        mkt_cols = res['marketdata']['columns']
        mkt_data = res['marketdata']['data'][0] if res['marketdata']['data'] else []

        def get_val(data, cols, name):
            if not data or name not in cols:
                return None
            return data[cols.index(name)]

        facevalue = get_val(sec_data, sec_cols, 'FACEVALUE') or 1000
        last_pct = get_val(mkt_data, mkt_cols, 'LAST') or get_val(sec_data, sec_cols, 'PREVPRICE')
        if not last_pct:
            last_pct = 100
        price_rub = (last_pct / 100) * facevalue

        return {
            'secid': secid,
            'name': get_val(sec_data, sec_cols, 'SHORTNAME'),
            'price': round(price_rub, 2),
            'facevalue': facevalue,
            'nkd': round(get_val(sec_data, sec_cols, 'ACCRUEDINT') or 0, 2),
            'ytm': round(
                get_val(mkt_data, mkt_cols, 'DURATION_MUTATION_YIELD')
                or get_val(sec_data, sec_cols, 'YIELDTOOFFER')
                or 0,
                2,
            ),
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
            if not res.get('history') or not res['history'].get('data'):
                break

            columns = res['history']['columns']
            date_idx = columns.index('TRADEDATE')
            close_idx = columns.index('CLOSE')
            accint_idx = columns.index('ACCINT')
            yield_idx = columns.index('YIELDCLOSE')

            page_data = res['history']['data']
            if not page_data:
                break

            for row in page_data:
                if row[close_idx] is not None:
                    labels.append(row[date_idx])
                    prices.append(round((float(row[close_idx]) / 100) * facevalue, 2))
                    nkd_history.append(round(float(row[accint_idx]) if row[accint_idx] else 0, 2))
                    ytm_history.append(round(float(row[yield_idx]) if row[yield_idx] else 0, 2))

            if len(page_data) < 100:
                break
            start_offset += 100
    except Exception as e:
        logger.error("MOEX history pagination error for %s: %s", secid, e)
    return {"labels": labels, "data": prices, "nkd": nkd_history, "ytm": ytm_history}


def get_coupon_calendar(secid: str) -> list[dict]:
    """Возвращает ближайшие купонные выплаты для облигации."""
    try:
        res = _fetch_json(
            f"https://iss.moex.com/iss/statistics/engines/stock/markets"
            f"/bonds/bondization/{secid}.json"
        )
        calendar = []
        if res.get('coupons') and res['coupons'].get('data'):
            cols = res['coupons']['columns']
            for row in res['coupons']['data']:
                calendar.append({
                    "date": row[cols.index('coupondate')],
                    "value": row[cols.index('value')],
                })
        return calendar[:6]
    except Exception as e:
        logger.warning("MOEX coupon calendar error for %s: %s", secid, e)
        return []


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


def get_rgbi_history(from_date: Optional[str] = None, to_date: Optional[str] = None) -> dict:
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
    limit: int = 100,
) -> list[dict]:
    """Fetch bonds list from MOEX with optional YTM / maturity filtering."""
    try:
        url = (
            "https://iss.moex.com/iss/engines/stock/markets/bonds/securities.json"
            "?securities.columns=SECID,ISIN,SHORTNAME,YIELDTOOFFER,MATDATE,COUPONVALUE"
            f"&start=0&limit={limit}"
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
            results.append({
                "secid": gv(row, "SECID"),
                "isin": isin,
                "name": gv(row, "SHORTNAME") or gv(row, "SECID"),
                "ytm": round(float(ytm_val), 2) if ytm_val is not None else None,
                "matdate": mat_date,
                "coupon": gv(row, "COUPONVALUE"),
            })
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
